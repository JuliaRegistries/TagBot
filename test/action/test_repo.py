import os

from base64 import b64encode
from datetime import datetime, timedelta, timezone
from stat import S_IREAD, S_IWRITE, S_IEXEC
from subprocess import DEVNULL
from unittest.mock import Mock, call, mock_open, patch, PropertyMock

import pytest

from github import GithubException, UnknownObjectException
from github.Requester import requests

from tagbot.action import TAGBOT_WEB, Abort, InvalidProject
from tagbot.action.repo import Repo

RequestException = requests.RequestException


def _repo(
    *,
    repo="",
    registry="",
    github="",
    github_api="",
    token="x",
    changelog="",
    ignore=[],
    ssh=False,
    gpg=False,
    draft=False,
    registry_ssh="",
    user="",
    email="",
    lookback=3,
    branch=None,
    subdir=None,
    tag_prefix=None,
):
    return Repo(
        repo=repo,
        registry=registry,
        github=github,
        github_api=github_api,
        token=token,
        changelog=changelog,
        changelog_ignore=ignore,
        ssh=ssh,
        gpg=gpg,
        draft=draft,
        registry_ssh=registry_ssh,
        user=user,
        email=email,
        lookback=lookback,
        branch=branch,
        subdir=subdir,
        tag_prefix=tag_prefix,
    )


@patch("tagbot.action.repo.Github")
def test_constructor(mock_github):
    # Mock the Github instance and its get_repo method
    mock_gh_instance = Mock()
    mock_github.return_value = mock_gh_instance
    mock_gh_instance.get_repo.return_value = Mock()  # Mock registry repo

    r = _repo(
        github="github.com", github_api="api.github.com", registry="test/registry"
    )
    assert r._gh_url == "https://github.com"
    assert r._gh_api == "https://api.github.com"
    assert r._git._github == "github.com"

    r = _repo(
        github="https://github.com",
        github_api="https://api.github.com",
        registry="test/registry",
    )
    assert r._gh_url == "https://github.com"
    assert r._gh_api == "https://api.github.com"
    assert r._git._github == "github.com"


def test_project():
    r = _repo()
    r._repo.get_contents = Mock(
        return_value=Mock(decoded_content=b"""name = "FooBar"\nuuid="abc-def"\n""")
    )
    assert r._project("name") == "FooBar"
    assert r._project("uuid") == "abc-def"
    assert r._project("name") == "FooBar"
    r._repo.get_contents.assert_called_once_with("Project.toml")
    r._repo.get_contents.side_effect = UnknownObjectException(404, "???", {})
    r._Repo__project = None
    with pytest.raises(InvalidProject):
        r._project("name")


def test_project_malformed_toml():
    """Test that malformed Project.toml raises InvalidProject."""
    r = _repo()
    r._repo.get_contents = Mock(
        return_value=Mock(decoded_content=b"""name = "FooBar"\nuuid""")
    )
    r._Repo__project = None
    with pytest.raises(InvalidProject, match="Failed to parse Project.toml"):
        r._project("name")


def test_project_subdir():
    r = _repo(subdir="path/to/FooBar.jl")
    r._repo.get_contents = Mock(
        return_value=Mock(decoded_content=b"""name = "FooBar"\nuuid="abc-def"\n""")
    )
    assert r._project("name") == "FooBar"
    assert r._project("uuid") == "abc-def"
    r._repo.get_contents.assert_called_once_with("path/to/FooBar.jl/Project.toml")
    r._repo.get_contents.side_effect = UnknownObjectException(404, "???", {})
    r._Repo__project = None
    with pytest.raises(InvalidProject):
        r._project("name")


def test_registry_path():
    r = _repo()
    r._registry = Mock()
    r._registry.get_contents.return_value.sha = "123"
    r._registry.get_git_blob.return_value.content = b64encode(
        b"""
        [packages]
        abc-def = { path = "B/Bar" }
        """
    )
    r._project = lambda _k: "abc-ddd"
    assert r._registry_path is None
    r._project = lambda _k: "abc-def"
    assert r._registry_path == "B/Bar"
    assert r._registry_path == "B/Bar"
    assert r._registry.get_contents.call_count == 2


def test_registry_path_with_uppercase_uuid():
    """Test that uppercase UUIDs are normalized to lowercase for registry lookup."""
    r = _repo()
    r._registry = Mock()
    r._registry.get_contents.return_value.sha = "123"
    r._registry.get_git_blob.return_value.content = b64encode(
        b"""
        [packages]
        abc-def = { path = "B/Bar" }
        """
    )
    # Test with uppercase UUID
    r._project = lambda _k: "ABC-DEF"
    assert r._registry_path == "B/Bar"


@patch("tagbot.action.repo.logger")
def test_registry_path_malformed_toml(logger):
    """Test that malformed Registry.toml returns None and logs warning."""
    r = _repo()
    logger.reset_mock()  # Clear any warnings from _repo() initialization
    r._registry = Mock()
    r._registry.get_contents.return_value.sha = "123"
    # Malformed TOML content (missing closing bracket)
    r._registry.get_git_blob.return_value.content = b64encode(b"[packages\nkey")
    r._project = lambda _k: "abc-def"
    result = r._registry_path
    assert result is None
    logger.warning.assert_called_once()
    assert "Failed to parse Registry.toml" in logger.warning.call_args[0][0]
    assert "malformed TOML" in logger.warning.call_args[0][0]


@patch("tagbot.action.repo.logger")
def test_registry_path_invalid_encoding(logger):
    """Invalid UTF-8 in Registry.toml returns None and logs warning."""
    r = _repo()
    logger.reset_mock()  # Clear any warnings from _repo() initialization
    r._registry = Mock()
    r._registry.get_contents.return_value.sha = "123"
    # Mock get_git_blob to return content with invalid UTF-8 bytes
    r._registry.get_git_blob.return_value.content = b64encode(b"\xff\xfe[packages]")
    r._project = lambda _k: "abc-def"
    result = r._registry_path
    assert result is None
    logger.warning.assert_called_once()
    assert "Failed to load Registry.toml" in logger.warning.call_args[0][0]
    assert "UnicodeDecodeError" in logger.warning.call_args[0][0]


@patch("tagbot.action.repo.logger")
def test_registry_path_file_not_found(logger):
    """Test that missing Registry.toml file returns None and logs warning."""
    r = _repo(registry_ssh="key")  # Use SSH to trigger clone path
    logger.reset_mock()  # Clear any warnings from _repo() initialization
    r._clone_registry = True
    r._Repo__registry_clone_dir = "/nonexistent/path"
    r._project = lambda _k: "abc-def"
    result = r._registry_path
    assert result is None
    logger.warning.assert_called_once()
    assert "Failed to load Registry.toml" in logger.warning.call_args[0][0]
    assert "FileNotFoundError" in logger.warning.call_args[0][0]


@patch("tagbot.action.repo.logger")
def test_registry_path_missing_packages_key(logger):
    """Missing 'packages' key returns None and logs warning."""
    r = _repo()
    logger.reset_mock()  # Clear any warnings from _repo() initialization
    r._registry = Mock()
    r._registry.get_contents.return_value.sha = "123"
    # Valid TOML but missing required 'packages' section
    r._registry.get_git_blob.return_value.content = b64encode(b"[foo]\nbar=1")
    r._project = lambda _k: "abc-def"
    result = r._registry_path
    assert result is None
    logger.warning.assert_called_once()
    assert "missing the 'packages' key" in logger.warning.call_args[0][0]


def test_registry_url():
    r = _repo()
    r._Repo__registry_path = "E/Example"
    r._registry = Mock()
    r._registry.get_contents.return_value.decoded_content = b"""
    name = "Example"
    uuid = "7876af07-990d-54b4-ab0e-23690620f79a"
    repo = "https://github.com/JuliaLang/Example.jl.git"
    """
    assert r._registry_url == "https://github.com/JuliaLang/Example.jl.git"
    assert r._registry_url == "https://github.com/JuliaLang/Example.jl.git"
    assert r._registry.get_contents.call_count == 1


def test_registry_url_malformed_toml():
    """Test that malformed Package.toml raises InvalidProject."""
    r = _repo()
    r._Repo__registry_path = "E/Example"
    r._registry = Mock()
    # Malformed TOML content
    r._registry.get_contents.return_value.decoded_content = b"name = "
    with pytest.raises(InvalidProject, match="Failed to parse Package.toml"):
        _ = r._registry_url


def test_registry_url_invalid_encoding():
    """Test that invalid UTF-8 encoding in Package.toml raises InvalidProject."""
    r = _repo()
    r._Repo__registry_path = "E/Example"
    r._registry = Mock()
    # Invalid UTF-8 bytes (0xFF is not valid UTF-8)
    r._registry.get_contents.return_value.decoded_content = b"name = \xff\xfe"
    with pytest.raises(InvalidProject, match="encoding error"):
        _ = r._registry_url


def test_registry_url_missing_repo_key():
    """Missing 'repo' key in Package.toml raises InvalidProject."""
    r = _repo()
    r._Repo__registry_path = "E/Example"
    r._registry = Mock()
    # Valid TOML but missing required 'repo' field
    r._registry.get_contents.return_value.decoded_content = b"name = 'Example'\n"
    with pytest.raises(InvalidProject, match="missing the 'repo' key"):
        _ = r._registry_url


def test_release_branch():
    r = _repo()
    r._repo = Mock(default_branch="a")
    assert r._release_branch == "a"
    r = _repo(branch="b")
    assert r._release_branch == "b"


def test_only():
    r = _repo()
    assert r._only(1) == 1
    assert r._only([1]) == 1
    assert r._only([[1]]) == [1]


def test_maybe_decode_private_key():
    r = _repo()
    plain = "BEGIN OPENSSH PRIVATE KEY foo bar"
    b64 = b64encode(plain.encode()).decode()
    assert r._maybe_decode_private_key(plain) == plain
    assert r._maybe_decode_private_key(b64) == plain


def test_create_release_branch_pr():
    r = _repo()
    r._repo = Mock(default_branch="default")
    r._create_release_branch_pr("v1.2.3", "branch")
    r._repo.create_pull.assert_called_once_with(
        title="Merge release branch for v1.2.3", body="", head="branch", base="default"
    )

    r._repo = Mock(default_branch="default")
    r._create_release_branch_pr("Foo-v1.2.3", "branch")
    r._repo.create_pull.assert_called_once_with(
        title="Merge release branch for Foo-v1.2.3",
        body="",
        head="branch",
        base="default",
    )


def test_registry_pr():
    r = _repo()
    r._Repo__project = {"name": "PkgName", "uuid": "abcdef0123456789"}
    r._registry = Mock(owner=Mock(login="Owner"))
    now = datetime.now(timezone.utc)
    owner_pr = Mock(merged_at=now)
    r._registry.get_pulls.return_value = [owner_pr]
    r._Repo__registry_url = "https://github.com/Org/pkgname.jl.git"
    assert r._registry_pr("v1.2.3") is owner_pr
    r._registry.get_pulls.assert_called_once_with(
        head="Owner:registrator-pkgname-abcdef01-v1.2.3-d745cc13b3", state="closed"
    )
    r._registry.get_pulls.side_effect = [[], [Mock(closed_at=now - timedelta(days=10))]]
    assert r._registry_pr("v2.3.4") is None
    calls = [
        call(
            head="Owner:registrator-pkgname-abcdef01-v2.3.4-d745cc13b3", state="closed"
        ),
        call(state="closed"),
    ]
    r._registry.get_pulls.assert_has_calls(calls)
    good_pr = Mock(
        closed_at=now - timedelta(days=2),
        merged=True,
        head=Mock(ref="registrator-pkgname-abcdef01-v3.4.5-d745cc13b3"),
    )
    r._registry.get_pulls.side_effect = [[], [good_pr]]
    assert r._registry_pr("v3.4.5") is good_pr
    calls = [
        call(
            head="Owner:registrator-pkgname-abcdef01-v3.4.5-d745cc13b3", state="closed"
        ),
        call(state="closed"),
    ]
    r._registry.get_pulls.assert_has_calls(calls)


@patch("tagbot.action.repo.logger")
def test_commit_sha_from_registry_pr(logger):
    r = _repo()
    r._registry_pr = Mock(return_value=None)
    assert r._commit_sha_from_registry_pr("v1.2.3", "abc") is None
    logger.info.assert_called_with("Did not find registry PR")
    r._registry_pr.return_value = Mock(body="")
    assert r._commit_sha_from_registry_pr("v2.3.4", "bcd") is None
    logger.info.assert_called_with("Registry PR body did not match")
    r._registry_pr.return_value.body = f"foo\n- Commit: {'a' * 32}\nbar"
    r._repo.get_commit = Mock()
    r._repo.get_commit.return_value.commit.tree.sha = "def"
    r._repo.get_commit.return_value.sha = "sha"
    assert r._commit_sha_from_registry_pr("v3.4.5", "cde") is None
    r._repo.get_commit.assert_called_with("a" * 32)
    logger.warning.assert_called_with(
        "Tree SHA of commit from registry PR does not match"
    )
    assert r._commit_sha_from_registry_pr("v4.5.6", "def") == "sha"


def test_commit_sha_of_tree_from_branch():
    r = _repo()
    since = datetime.now(timezone.utc)
    r._repo.get_commits = Mock(return_value=[Mock(sha="abc"), Mock(sha="sha")])
    r._repo.get_commits.return_value[1].commit.tree.sha = "tree"
    assert r._commit_sha_of_tree_from_branch("master", "tree", since) == "sha"
    r._repo.get_commits.assert_called_with(sha="master", since=since)
    r._repo.get_commits.return_value.pop()
    assert r._commit_sha_of_tree_from_branch("master", "tree", since) is None


@patch("tagbot.action.repo.logger")
def test_commit_sha_of_tree_from_branch_subdir(logger):
    r = _repo(subdir="path/to/package")
    since = datetime.now(timezone.utc)
    commits = [Mock(sha="abc"), Mock(sha="sha")]
    r._repo.get_commits = Mock(return_value=commits)
    r._git.command = Mock(side_effect=["other", "tree_hash"])

    assert r._commit_sha_of_tree_from_branch("master", "tree_hash", since) == "sha"

    r._repo.get_commits.assert_called_with(sha="master", since=since)
    r._git.command.assert_has_calls(
        [
            call("rev-parse", "abc:path/to/package"),
            call("rev-parse", "sha:path/to/package"),
        ]
    )
    logger.debug.assert_not_called()


@patch("tagbot.action.repo.logger")
def test_commit_sha_of_tree_from_branch_subdir_rev_parse_failure(logger):
    r = _repo(subdir="path/to/package")
    since = datetime.now(timezone.utc)
    commits = [Mock(sha="abc"), Mock(sha="sha")]
    r._repo.get_commits = Mock(return_value=commits)
    r._git.command = Mock(side_effect=[Abort("missing"), "tree_hash"])

    assert r._commit_sha_of_tree_from_branch("master", "tree_hash", since) == "sha"

    r._repo.get_commits.assert_called_with(sha="master", since=since)
    logger.debug.assert_called_with(
        "rev-parse failed while inspecting %s", "abc:path/to/package"
    )
    r._git.command.assert_has_calls(
        [
            call("rev-parse", "abc:path/to/package"),
            call("rev-parse", "sha:path/to/package"),
        ]
    )


def test_commit_sha_of_tree():
    r = _repo()
    now = datetime.now(timezone.utc)
    r._repo = Mock(default_branch="master")
    branches = r._repo.get_branches.return_value = [Mock(), Mock()]
    branches[0].name = "foo"
    branches[1].name = "master"
    r._lookback = Mock(__rsub__=lambda x, y: now)
    r._commit_sha_of_tree_from_branch = Mock(side_effect=["sha1", None, "sha2"])
    assert r._commit_sha_of_tree("tree") == "sha1"
    r._repo.get_branches.assert_not_called()
    r._commit_sha_of_tree_from_branch.assert_called_once_with("master", "tree", now)
    assert r._commit_sha_of_tree("tree") == "sha2"
    r._commit_sha_of_tree_from_branch.assert_called_with("foo", "tree", now)
    r._commit_sha_of_tree_from_branch.side_effect = None
    r._commit_sha_of_tree_from_branch.return_value = None
    r._git.commit_sha_of_tree = Mock(side_effect=["sha", None])
    assert r._commit_sha_of_tree("tree") == "sha"
    assert r._commit_sha_of_tree("tree") is None


def test_commit_sha_of_tree_subdir_fallback():
    """Test subdirectory fallback when branch lookups fail."""
    r = _repo(subdir="path/to/package")
    now = datetime.now(timezone.utc)
    r._repo = Mock(default_branch="master")
    branches = r._repo.get_branches.return_value = [Mock()]
    branches[0].name = "master"
    r._lookback = Mock(__rsub__=lambda x, y: now)
    # Branch lookups return None (fail)
    r._commit_sha_of_tree_from_branch = Mock(return_value=None)
    # git log returns commit SHAs
    r._git.command = Mock(return_value="abc123\ndef456\nghi789")
    # _subdir_tree_hash called via helper, simulate finding match on second commit
    with patch.object(r, "_subdir_tree_hash", side_effect=[None, "tree_hash", "other"]):
        assert r._commit_sha_of_tree("tree_hash") == "def456"
        # Verify it iterated through commits
        assert r._subdir_tree_hash.call_count == 2


def test_commit_sha_of_tree_subdir_fallback_no_match():
    """Test subdirectory fallback returns None when no match found."""
    r = _repo(subdir="path/to/package")
    now = datetime.now(timezone.utc)
    r._repo = Mock(default_branch="master")
    branches = r._repo.get_branches.return_value = [Mock()]
    branches[0].name = "master"
    r._lookback = Mock(__rsub__=lambda x, y: now)
    r._commit_sha_of_tree_from_branch = Mock(return_value=None)
    r._git.command = Mock(return_value="abc123\ndef456")
    # No matches found
    with patch.object(r, "_subdir_tree_hash", return_value=None):
        assert r._commit_sha_of_tree("tree_hash") is None
        assert r._subdir_tree_hash.call_count == 2


def test_commit_sha_of_tag():
    r = _repo()
    r._repo.get_git_ref = Mock()
    r._repo.get_git_ref.return_value.object.type = "commit"
    r._repo.get_git_ref.return_value.object.sha = "c"
    assert r._commit_sha_of_tag("v1.2.3") == "c"
    r._repo.get_git_ref.assert_called_with("tags/v1.2.3")
    r._repo.get_git_ref.return_value.object.type = "tag"
    r._repo.get_git_tag = Mock()
    r._repo.get_git_tag.return_value.object.sha = "t"
    assert r._commit_sha_of_tag("v2.3.4") == "t"
    r._repo.get_git_tag.assert_called_with("c")
    r._repo.get_git_ref.return_value.object = None
    assert r._commit_sha_of_tag("v3.4.5") is None
    r._repo.get_git_ref.side_effect = UnknownObjectException(404, "???", {})
    assert r._commit_sha_of_tag("v4.5.6") is None


def test_commit_sha_of_release_branch():
    r = _repo()
    r._repo = Mock(default_branch="a")
    r._repo.get_branch.return_value.commit.sha = "sha"
    assert r._commit_sha_of_release_branch() == "sha"
    r._repo.get_branch.assert_called_with("a")


@patch("tagbot.action.repo.logger")
def test_filter_map_versions(logger):
    r = _repo()
    r._commit_sha_from_registry_pr = Mock(return_value=None)
    r._commit_sha_of_tree = Mock(return_value=None)
    assert not r._filter_map_versions({"1.2.3": "tree1"})
    logger.warning.assert_called_with(
        "No matching commit was found for version v1.2.3 (tree1)"
    )
    r._commit_sha_of_tree.return_value = "sha"
    r._commit_sha_of_tag = Mock(return_value="sha")
    assert not r._filter_map_versions({"2.3.4": "tree2"})
    logger.info.assert_called_with("Tag v2.3.4 already exists")
    r._commit_sha_of_tag.return_value = "abc"
    assert not r._filter_map_versions({"3.4.5": "tree3"})
    logger.error.assert_called_with(
        "Existing tag v3.4.5 points at the wrong commit (expected sha)"
    )
    r._commit_sha_of_tag.return_value = None
    assert r._filter_map_versions({"4.5.6": "tree4"}) == {"v4.5.6": "sha"}


@patch("tagbot.action.repo.logger")
def test_versions(logger):
    r = _repo()
    r._Repo__registry_path = "path"
    r._registry = Mock()
    r._registry.get_contents.return_value.decoded_content = b"""
    ["1.2.3"]
    git-tree-sha1 = "abc"

    ["2.3.4"]
    git-tree-sha1 = "bcd"
    """
    assert r._versions() == {"1.2.3": "abc", "2.3.4": "bcd"}
    r._registry.get_contents.assert_called_with("path/Versions.toml")
    logger.debug.assert_not_called()
    commit = Mock()
    commit.commit.sha = "abcdef"
    r._registry.get_commits.return_value = [commit]
    delta = timedelta(days=3)
    assert r._versions(min_age=delta) == {"1.2.3": "abc", "2.3.4": "bcd"}
    r._registry.get_commits.assert_called_once()
    assert len(r._registry.get_commits.mock_calls) == 1
    [c] = r._registry.get_commits.mock_calls
    assert not c.args and len(c.kwargs) == 1 and "until" in c.kwargs
    assert isinstance(c.kwargs["until"], datetime)
    r._registry.get_contents.assert_called_with("path/Versions.toml", ref="abcdef")
    logger.debug.assert_not_called()
    r._registry.get_commits.return_value = []
    assert r._versions(min_age=delta) == {}
    logger.debug.assert_called_with("No registry commits were found")
    r._registry.get_contents.side_effect = UnknownObjectException(404, "???", {})
    assert r._versions() == {}
    logger.debug.assert_called_with("Versions.toml was not found ({})")
    r._Repo__registry_path = Mock(__bool__=lambda self: False)
    assert r._versions() == {}
    logger.debug.assert_called_with("Package is not registered")


def test_run_url():
    r = _repo()
    r._repo = Mock(html_url="https://github.com/Foo/Bar")
    with patch.dict(os.environ, {"GITHUB_RUN_ID": "123"}):
        assert r._run_url() == "https://github.com/Foo/Bar/actions/runs/123"
    with patch.dict(os.environ, clear=True):
        assert r._run_url() == "https://github.com/Foo/Bar/actions"


@patch("tagbot.action.repo.logger")
@patch("docker.from_env")
def test_image_id(from_env, logger):
    r = _repo()
    from_env.return_value.containers.get.return_value.image.id = "sha"
    with patch.dict(os.environ, {"HOSTNAME": "foo"}):
        assert r._image_id() == "sha"
    with patch.dict(os.environ, clear=True):
        assert r._image_id() == "Unknown"
    logger.warning.assert_called_with("HOSTNAME is not set")


@patch("requests.post")
def test_report_error(post):
    post.return_value.json.return_value = {"status": "ok"}
    r = _repo(token="x")
    r._repo = Mock(full_name="Foo/Bar", private=True)
    r._image_id = Mock(return_value="id")
    r._run_url = Mock(return_value="url")
    r._report_error("ahh")
    post.assert_not_called()
    r._repo.private = False
    with patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}):
        r._report_error("ahh")
    post.assert_not_called()
    with patch.dict(os.environ, {}, clear=True):
        r._report_error("ahh")
    post.assert_not_called()
    with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
        r._report_error("ahh")
    post.assert_called_with(
        f"{TAGBOT_WEB}/report",
        json={"image": "id", "repo": "Foo/Bar", "run": "url", "stacktrace": "ahh"},
    )


@patch("requests.post")
def test_report_error_handles_bad_credentials(post):
    post.return_value.json.return_value = {"status": "ok"}
    r = _repo(token="x")
    r._repo = Mock(full_name="Foo/Bar")
    type(r._repo).private = PropertyMock(
        side_effect=GithubException(401, "Bad credentials", {})
    )
    r._image_id = Mock(return_value="id")
    r._run_url = Mock(return_value="url")
    r._report_error("ahh")
    post.assert_not_called()


def test_is_registered():
    r = _repo(github="gh.com")
    r._repo = Mock(full_name="Foo/Bar.jl")
    r._Repo__registry_path = Mock(__bool__=lambda self: False)
    r._registry.get_contents = Mock()
    contents = r._registry.get_contents.return_value
    contents.decoded_content = b"""repo = "https://gh.com/Foo/Bar.jl.git"\n"""
    assert not r.is_registered()
    r._registry.get_contents.assert_not_called()
    r._Repo__registry_path = "path"
    assert r.is_registered()
    r._registry.get_contents.assert_called_with("path/Package.toml")
    contents.decoded_content = b"""repo = "https://gh.com/Foo/Bar.jl"\n"""
    assert r.is_registered()
    contents.decoded_content = b"""repo = "https://gitlab.com/Foo/Bar.jl.git"\n"""
    assert not r.is_registered()
    contents.decoded_content = b"""repo = "git@gh.com:Foo/Bar.jl.git"\n"""
    assert r.is_registered()
    contents.decoded_content = b"""repo = "git@github.com:Foo/Bar.jl.git"\n"""
    assert not r.is_registered()
    # TODO: We should test for the InvalidProject behaviour,
    # but I'm not really sure how it's possible.


def test_new_versions():
    r = _repo()
    r._versions = lambda min_age=None: (
        {"1.2.3": "abc"}
        if min_age
        else {"1.2.3": "abc", "3.4.5": "cde", "2.3.4": "bcd"}
    )
    r._filter_map_versions = lambda vs: vs
    assert list(r.new_versions().items()) == [("2.3.4", "bcd"), ("3.4.5", "cde")]


def test_create_dispatch_event():
    r = _repo()
    r._repo = Mock(full_name="Foo/Bar")
    r.create_dispatch_event({"a": "b", "c": "d"})
    r._repo.create_repository_dispatch.assert_called_once_with(
        "TagBot", {"a": "b", "c": "d"}
    )


@patch("tagbot.action.repo.mkstemp", side_effect=[(0, "abc"), (0, "xyz")] * 3)
@patch("os.chmod")
@patch("subprocess.run")
@patch("pexpect.spawn")
def test_configure_ssh(spawn, run, chmod, mkstemp):
    r = _repo(github="gh.com", repo="foo")
    r._repo = Mock(ssh_url="sshurl")
    r._git.set_remote_url = Mock()
    r._git.config = Mock()
    open = mock_open()
    with patch("builtins.open", open):
        r.configure_ssh(" BEGIN OPENSSH PRIVATE KEY ", None)
    r._git.set_remote_url.assert_called_with("sshurl")
    open.assert_has_calls([call("abc", "w"), call("xyz", "w")], any_order=True)
    open.return_value.write.assert_called_with("BEGIN OPENSSH PRIVATE KEY\n")
    run.assert_called_with(
        ["ssh-keyscan", "-t", "rsa", "gh.com"],
        check=True,
        stdout=open.return_value,
        stderr=DEVNULL,
    )
    chmod.assert_called_with("abc", S_IREAD)
    r._git.config.assert_called_with(
        "core.sshCommand", "ssh -i abc -o UserKnownHostsFile=xyz", repo=""
    )
    with patch("builtins.open", open):
        r.configure_ssh("Zm9v", None)
    open.return_value.write.assert_any_call("foo\n")
    spawn.assert_not_called()
    run.return_value.stdout = """
    VAR1=value; export VAR1;
    VAR2=123; export VAR2;
    echo Agent pid 123;
    """
    with patch("builtins.open", open):
        r.configure_ssh("Zm9v", "mypassword")
    open.return_value.write.assert_called_with("foo\n")
    run.assert_called_with(["ssh-agent"], check=True, text=True, capture_output=True)
    assert os.getenv("VAR1") == "value"
    assert os.getenv("VAR2") == "123"
    spawn.assert_called_with("ssh-add abc")
    calls = [
        call.expect("Enter passphrase"),
        call.sendline("mypassword"),
        call.expect("Identity added"),
    ]
    spawn.return_value.assert_has_calls(calls)


@patch("tagbot.action.repo.GPG")
@patch("tagbot.action.repo.mkdtemp", return_value="gpgdir")
@patch("os.chmod")
def test_configure_gpg(chmod, mkdtemp, GPG):
    r = _repo()
    r._git.config = Mock()
    gpg = GPG.return_value
    gpg.import_keys.return_value = Mock(sec_imported=1, fingerprints=["k"], stderr="e")
    r.configure_gpg("BEGIN PGP PRIVATE KEY", None)
    assert os.getenv("GNUPGHOME") == "gpgdir"
    chmod.assert_called_with("gpgdir", S_IREAD | S_IWRITE | S_IEXEC)
    GPG.assert_called_with(gnupghome="gpgdir", use_agent=True)
    gpg.import_keys.assert_called_with("BEGIN PGP PRIVATE KEY", passphrase=None)
    calls = [call("tag.gpgSign", "true"), call("user.signingKey", "k")]
    r._git.config.assert_has_calls(calls)
    r.configure_gpg("Zm9v", None)
    gpg.import_keys.assert_called_with("foo", passphrase=None)
    gpg.sign.return_value = Mock(status="signature created")
    r.configure_gpg("Zm9v", "mypassword")
    gpg.sign.assert_called_with("test", passphrase="mypassword")
    gpg.sign.return_value = Mock(status=None, stderr="e")
    with pytest.raises(Abort):
        r.configure_gpg("Zm9v", "mypassword")
    gpg.import_keys.return_value.sec_imported = 0
    with pytest.raises(Abort):
        r.configure_gpg("Zm9v", None)


def test_handle_release_branch():
    r = _repo()
    r._create_release_branch_pr = Mock()
    r._git = Mock(
        fetch_branch=Mock(side_effect=[False, True, True, True, True]),
        is_merged=Mock(side_effect=[True, False, False, False]),
        can_fast_forward=Mock(side_effect=[True, False, False]),
    )
    r._pr_exists = Mock(side_effect=[True, False])
    r.handle_release_branch("v1")
    r._git.fetch_branch.assert_called_with("release-1")
    r._git.is_merged.assert_not_called()
    r.handle_release_branch("v2")
    r._git.is_merged.assert_called_with("release-2")
    r._git.can_fast_forward.assert_not_called()
    r.handle_release_branch("v3")
    r._git.merge_and_delete_branch.assert_called_with("release-3")
    r._pr_exists.assert_not_called()
    r.handle_release_branch("v4")
    r._pr_exists.assert_called_with("release-4")
    r._create_release_branch_pr.assert_not_called()
    r.handle_release_branch("v5")
    r._create_release_branch_pr.assert_called_with("v5", "release-5")


def test_handle_release_branch_subdir():
    r = _repo(subdir="path/to/Foo.jl")
    r._repo.get_contents = Mock(
        return_value=Mock(decoded_content=b"""name = "Foo"\nuuid="abc-def"\n""")
    )
    r._create_release_branch_pr = Mock()
    r._git = Mock(
        fetch_branch=Mock(side_effect=[False, True, True, True, True]),
        is_merged=Mock(side_effect=[True, False, False, False]),
        can_fast_forward=Mock(side_effect=[True, False, False]),
    )
    r._pr_exists = Mock(side_effect=[True, False])
    r.handle_release_branch("v1")
    r._git.fetch_branch.assert_called_with("release-Foo-1")
    r._git.is_merged.assert_not_called()
    r.handle_release_branch("v2")
    r._git.is_merged.assert_called_with("release-Foo-2")
    r._git.can_fast_forward.assert_not_called()
    r.handle_release_branch("v3")
    r._git.merge_and_delete_branch.assert_called_with("release-Foo-3")
    r._pr_exists.assert_not_called()
    r.handle_release_branch("v4")
    r._pr_exists.assert_called_with("release-Foo-4")
    r._create_release_branch_pr.assert_not_called()
    r.handle_release_branch("v5")
    r._create_release_branch_pr.assert_called_with("Foo-v5", "release-Foo-5")


def test_create_release():
    r = _repo(user="user", email="email")
    r._commit_sha_of_release_branch = Mock(return_value="a")
    r._git.create_tag = Mock()
    r._repo = Mock(default_branch="default")
    r._repo.create_git_tag.return_value.sha = "t"
    r._changelog.get = Mock(return_value="l")
    r.create_release("v1", "a")
    r._git.create_tag.assert_called_with("v1", "a", "l")
    r._repo.create_git_release.assert_called_with(
        "v1", "v1", "l", target_commitish="default", draft=False
    )
    r.create_release("v1", "b")
    r._repo.create_git_release.assert_called_with(
        "v1", "v1", "l", target_commitish="b", draft=False
    )
    r.create_release("v1", "c")
    r._git.create_tag.assert_called_with("v1", "c", "l")
    r._draft = True
    r._git.create_tag.reset_mock()
    r.create_release("v1", "d")
    r._git.create_tag.assert_not_called()
    r._repo.create_git_release.assert_called_with(
        "v1", "v1", "l", target_commitish="d", draft=True
    )


def test_create_release_subdir():
    r = _repo(user="user", email="email", subdir="path/to/Foo.jl")
    r._commit_sha_of_release_branch = Mock(return_value="a")
    r._repo.get_contents = Mock(
        return_value=Mock(decoded_content=b"""name = "Foo"\nuuid="abc-def"\n""")
    )
    assert r._tag_prefix() == "Foo-v"
    r._git.create_tag = Mock()
    r._repo = Mock(default_branch="default")
    r._repo.create_git_tag.return_value.sha = "t"
    r._changelog.get = Mock(return_value="l")
    r.create_release("v1", "a")
    r._git.create_tag.assert_called_with("Foo-v1", "a", "l")
    r._repo.create_git_release.assert_called_with(
        "Foo-v1", "Foo-v1", "l", target_commitish="default", draft=False
    )
    r.create_release("v1", "b")
    r._repo.create_git_release.assert_called_with(
        "Foo-v1", "Foo-v1", "l", target_commitish="b", draft=False
    )
    r.create_release("v1", "c")
    r._git.create_tag.assert_called_with("Foo-v1", "c", "l")
    r._draft = True
    r._git.create_tag.reset_mock()
    r.create_release("v1", "d")
    r._git.create_tag.assert_not_called()
    r._repo.create_git_release.assert_called_with(
        "Foo-v1", "Foo-v1", "l", target_commitish="d", draft=True
    )


@patch("tagbot.action.repo.logger")
def test_check_rate_limit(logger):
    r = _repo()
    mock_core = Mock()
    mock_core.remaining = 4500
    mock_core.limit = 5000
    mock_core.reset = "2024-01-01T00:00:00Z"
    mock_rate_limit = Mock()
    mock_rate_limit.resources.core = mock_core
    r._gh.get_rate_limit = Mock(return_value=mock_rate_limit)

    r._check_rate_limit()

    r._gh.get_rate_limit.assert_called_once()
    logger.info.assert_called_once()
    assert "4500/5000" in logger.info.call_args[0][0]


@patch("tagbot.action.repo.logger")
def test_check_rate_limit_error(logger):
    r = _repo()
    r._gh.get_rate_limit = Mock(side_effect=Exception("API error"))

    r._check_rate_limit()

    logger.debug.assert_called_once()
    assert "Could not check rate limit" in logger.debug.call_args[0][0]


@patch("traceback.format_exc", return_value="ahh")
@patch("tagbot.action.repo.logger")
def test_handle_error(logger, format_exc):
    r = _repo()
    r._report_error = Mock(side_effect=[None, RuntimeError("!")])
    r._check_rate_limit = Mock()
    r.handle_error(RequestException())
    r._report_error.assert_not_called()
    r.handle_error(GithubException(502, "oops", {}))
    r._report_error.assert_not_called()
    try:
        r.handle_error(GithubException(404, "???", {}))
    except Abort:
        assert True
    else:
        assert False
    r._report_error.assert_called_with("ahh")
    try:
        r.handle_error(RuntimeError("?"))
    except Abort:
        assert True
    else:
        assert False
    r._report_error.assert_called_with("ahh")
    logger.error.assert_called_with("Issue reporting failed")


@patch("traceback.format_exc", return_value="ahh")
@patch("tagbot.action.repo.logger")
def test_handle_error_403_checks_rate_limit(logger, format_exc):
    r = _repo()
    r._report_error = Mock()
    r._check_rate_limit = Mock()
    try:
        r.handle_error(GithubException(403, "forbidden", {}))
    except Abort:
        pass
    r._check_rate_limit.assert_called_once()
    assert any("403" in str(call) for call in logger.error.call_args_list)


def test_commit_sha_of_version():
    r = _repo()
    r._Repo__registry_path = ""
    r._registry.get_contents = Mock(
        return_value=Mock(decoded_content=b"""["3.4.5"]\ngit-tree-sha1 = "abc"\n""")
    )
    r._commit_sha_of_tree = Mock(return_value="def")
    assert r.commit_sha_of_version("v1.2.3") is None
    r._registry.get_contents.assert_not_called()
    r._Repo__registry_path = "path"
    assert r.commit_sha_of_version("v2.3.4") is None
    r._registry.get_contents.assert_called_with("path/Versions.toml")
    r._commit_sha_of_tree.assert_not_called()
    assert r.commit_sha_of_version("v3.4.5") == "def"
    r._commit_sha_of_tree.assert_called_with("abc")


def test_tag_prefix_and_get_version_tag():
    r = _repo()
    r._repo.get_contents = Mock(
        return_value=Mock(decoded_content=b"""name = "FooBar"\nuuid="abc-def"\n""")
    )
    assert r._tag_prefix() == "v"
    assert r._get_version_tag("v0.1.3") == "v0.1.3"
    assert r._get_version_tag("0.1.3") == "v0.1.3"

    r = _repo(subdir="")
    r._repo.get_contents = Mock(
        return_value=Mock(decoded_content=b"""name = "FooBar"\nuuid="abc-def"\n""")
    )
    assert r._tag_prefix() == "v"
    assert r._get_version_tag("v0.1.3") == "v0.1.3"
    assert r._get_version_tag("0.1.3") == "v0.1.3"

    r_subdir = _repo(subdir="FooBar")
    r_subdir._repo.get_contents = Mock(
        return_value=Mock(decoded_content=b"""name = "FooBar"\nuuid="abc-def"\n""")
    )
    assert r_subdir._tag_prefix() == "FooBar-v"
    assert r_subdir._get_version_tag("v0.1.3") == "FooBar-v0.1.3"
    assert r_subdir._get_version_tag("0.1.3") == "FooBar-v0.1.3"

    r_subdir = _repo(subdir="FooBar", tag_prefix="NO_PREFIX")
    r_subdir._repo.get_contents = Mock(
        return_value=Mock(decoded_content=b"""name = "FooBar"\nuuid="abc-def"\n""")
    )
    assert r._tag_prefix() == "v"
    assert r._get_version_tag("v0.1.3") == "v0.1.3"
    assert r._get_version_tag("0.1.3") == "v0.1.3"

    r_subdir = _repo(tag_prefix="MyFooBar")
    r_subdir._repo.get_contents = Mock(
        return_value=Mock(decoded_content=b"""name = "FooBar"\nuuid="abc-def"\n""")
    )
    assert r_subdir._tag_prefix() == "MyFooBar-v"
    assert r_subdir._get_version_tag("v0.1.3") == "MyFooBar-v0.1.3"
    assert r_subdir._get_version_tag("0.1.3") == "MyFooBar-v0.1.3"
