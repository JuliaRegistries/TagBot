import os
import subprocess

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
    changelog_format="custom",
    ssh=False,
    gpg=False,
    draft=False,
    registry_ssh="",
    user="",
    email="",
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
        changelog_format=changelog_format,
        ssh=ssh,
        gpg=gpg,
        draft=draft,
        registry_ssh=registry_ssh,
        user=user,
        email=email,
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


def test_project_invalid_encoding():
    """Invalid UTF-8 in Project.toml raises InvalidProject."""
    r = _repo()
    r._repo.get_contents = Mock(return_value=Mock(decoded_content=b"name = \xff\xfe"))
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
    r._registry.get_git_blob.return_value.content = b64encode(b"""
        [packages]
        abc-def = { path = "B/Bar" }
        """)
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
    r._registry.get_git_blob.return_value.content = b64encode(b"""
        [packages]
        abc-def = { path = "B/Bar" }
        """)
    # Test with uppercase UUID
    r._project = lambda _k: "ABC-DEF"
    assert r._registry_path == "B/Bar"


def test_registry_path_with_uppercase_registry_uuid():
    """Test that uppercase UUIDs in the registry are normalized for matching."""
    r = _repo()
    r._registry = Mock()
    r._registry.get_contents.return_value.sha = "123"
    # Registry has uppercase UUID
    r._registry.get_git_blob.return_value.content = b64encode(b"""
        [packages]
        ABC-DEF-1234 = { path = "P/Package" }
        """)
    # Project has lowercase UUID
    r._project = lambda _k: "abc-def-1234"
    assert r._registry_path == "P/Package"


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
    r._registry.get_git_blob.return_value.content = b64encode(b"\x80\x81[packages]")
    r._project = lambda _k: "abc-def"
    result = r._registry_path
    assert result is None
    logger.warning.assert_called_once()
    assert "Failed to parse Registry.toml" in logger.warning.call_args[0][0]
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
    assert "Failed to parse Registry.toml" in logger.warning.call_args[0][0]
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
    r._registry.get_contents.return_value.decoded_content = b"name = \n[incomplete"
    with pytest.raises(InvalidProject, match="Failed to parse Package.toml"):
        _ = r._registry_url


def test_registry_url_invalid_encoding():
    """Test that invalid UTF-8 encoding in Package.toml raises InvalidProject."""
    r = _repo()
    r._Repo__registry_path = "E/Example"
    r._registry = Mock()
    # Invalid UTF-8 bytes (0x80 and 0x81 are not valid UTF-8 start bytes)
    r._registry.get_contents.return_value.decoded_content = b"\x80\x81"
    with pytest.raises(InvalidProject, match="Failed to parse Package.toml"):
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
    r._registry_pr = Mock(return_value=None)
    assert r._release_branch("v1.0.0") == "a"

    r = _repo(branch="b")
    r._registry_pr = Mock(return_value=None)
    assert r._release_branch("v1.0.0") == "b"

    # Test PR branch has highest priority
    r = _repo(branch="config-branch")
    r._repo = Mock(default_branch="default-branch")
    pr_body = "foo\n- Branch: pr-branch\nbar"
    r._registry_pr = Mock(return_value=Mock(body=pr_body))
    assert r._release_branch("v1.0.0") == "pr-branch"

    # Test that missing branch in PR falls back to config
    r = _repo(branch="config-branch")
    r._repo = Mock(default_branch="default-branch")
    r._registry_pr = Mock(return_value=Mock(body="no branch here"))
    assert r._release_branch("v1.0.0") == "config-branch"


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


def test_maybe_decode_private_key_invalid():
    r = _repo()
    with pytest.raises(ValueError) as exc_info:
        r._maybe_decode_private_key("not valid base64 or key!!!")
    assert "does not appear to be a valid private key" in str(exc_info.value)


def test_validate_ssh_key(caplog):
    r = _repo()
    # Valid keys should not produce warnings
    caplog.clear()
    r._validate_ssh_key("-----BEGIN OPENSSH PRIVATE KEY-----\ndata\n-----END")
    assert "does not appear to be a valid private key" not in caplog.text
    assert "SSH key is empty" not in caplog.text

    caplog.clear()
    r._validate_ssh_key("-----BEGIN RSA PRIVATE KEY-----\ndata")
    assert "does not appear to be a valid private key" not in caplog.text

    caplog.clear()
    r._validate_ssh_key("-----BEGIN EC PRIVATE KEY-----\ndata")
    assert "does not appear to be a valid private key" not in caplog.text

    caplog.clear()
    r._validate_ssh_key("-----BEGIN PRIVATE KEY-----\ndata")
    assert "does not appear to be a valid private key" not in caplog.text

    # Empty key should warn
    caplog.clear()
    r._validate_ssh_key("")
    assert "SSH key is empty" in caplog.text

    caplog.clear()
    r._validate_ssh_key("   ")
    assert "SSH key is empty" in caplog.text

    # Invalid keys should warn
    caplog.clear()
    r._validate_ssh_key("ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAB")
    assert "does not appear to be a valid private key" in caplog.text
    assert "private key, not the public key" in caplog.text

    caplog.clear()
    r._validate_ssh_key("just some random text")
    assert "does not appear to be a valid private key" in caplog.text


@patch("subprocess.run")
def test_test_ssh_connection_success(run, caplog):
    r = _repo()
    caplog.clear()
    caplog.set_level("INFO")
    run.return_value = Mock(
        stdout="", stderr="Hi there! You've successfully authenticated"
    )
    r._test_ssh_connection("ssh -i key -o UserKnownHostsFile=hosts", "github.com")
    run.assert_called_once_with(
        ["ssh", "-i", "key", "-o", "UserKnownHostsFile=hosts", "-T", "git@github.com"],
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert "SSH key authentication successful" in caplog.text


@patch("subprocess.run")
def test_test_ssh_connection_permission_denied(run, caplog):
    r = _repo()
    caplog.clear()
    run.return_value = Mock(
        stdout="", stderr="git@github.com: Permission denied (publickey)."
    )
    r._test_ssh_connection("ssh -i key", "github.com")
    assert "Permission denied" in caplog.text
    assert "deploy key is added to the repository" in caplog.text


@patch("subprocess.run")
def test_test_ssh_connection_timeout(run, caplog):
    r = _repo()
    caplog.clear()
    run.side_effect = subprocess.TimeoutExpired(cmd="ssh", timeout=30)
    r._test_ssh_connection("ssh -i key", "github.com")
    assert "SSH connection test timed out" in caplog.text


@patch("subprocess.run")
def test_test_ssh_connection_other_error(run, caplog):
    r = _repo()
    caplog.clear()
    caplog.set_level("DEBUG")
    run.side_effect = OSError("Network error")
    r._test_ssh_connection("ssh -i key", "github.com")
    assert "SSH connection test failed" in caplog.text


@patch("subprocess.run")
def test_test_ssh_connection_unknown_output(run, caplog):
    r = _repo()
    caplog.clear()
    caplog.set_level("INFO")
    run.return_value = Mock(stdout="some other output", stderr="")
    r._test_ssh_connection("ssh -i key", "github.com")
    # Should just debug log, no warning or info
    assert "SSH key authentication successful" not in caplog.text
    assert "Permission denied" not in caplog.text


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
    # Test finding PR in cache (now the only lookup path)
    good_pr = Mock(
        closed_at=now,
        merged=True,
        head=Mock(ref="registrator-pkgname-abcdef01-v1.2.3-d745cc13b3"),
    )
    r._registry.get_pulls.return_value = [good_pr]
    r._Repo__registry_url = "https://github.com/Org/pkgname.jl.git"
    assert r._registry_pr("v1.2.3") is good_pr
    # Cache is built with get_pulls(state="closed", sort="updated", direction="desc")
    r._registry.get_pulls.assert_called_once_with(
        state="closed", sort="updated", direction="desc"
    )
    # Reset for next test - need fresh repo to avoid cache
    r2 = _repo()
    r2._Repo__project = {"name": "PkgName", "uuid": "abcdef0123456789"}
    r2._registry = Mock(owner=Mock(login="Owner"))
    r2._Repo__registry_url = "https://github.com/Org/pkgname.jl.git"
    r2._registry.get_pulls.return_value = []
    assert r2._registry_pr("v2.3.4") is None
    # Only one call to build the cache
    assert r2._registry.get_pulls.call_count == 1


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


@patch("tagbot.action.repo.logger")
def test_branch_from_registry_pr(logger):
    """Test extracting branch from registry PR body."""
    r = _repo()

    # No PR found
    r._registry_pr = Mock(return_value=None)
    assert r._branch_from_registry_pr("v1.0.0") is None

    # PR body without branch info
    r._registry_pr.return_value = Mock(body="foo\nbar\nbaz")
    assert r._branch_from_registry_pr("v1.0.0") is None

    # PR body is None
    r._registry_pr.return_value.body = None
    assert r._branch_from_registry_pr("v1.0.0") is None

    # PR body with "- Branch: <branch_name>" format
    r._registry_pr.return_value.body = "foo\n- Branch: my-release-branch\nbar"
    assert r._branch_from_registry_pr("v1.0.0") == "my-release-branch"
    logger.debug.assert_called_with(
        "Found branch 'my-release-branch' in registry PR for v1.0.0"
    )

    # PR body with "Branch: <branch_name>" format (without dash) should NOT match
    r._registry_pr.return_value.body = "foo\nBranch: another-branch\nbar"
    assert r._branch_from_registry_pr("v2.0.0") is None

    # PR body with extra whitespace
    r._registry_pr.return_value.body = "foo\n-   Branch:   spaced-branch  \nbar"
    assert r._branch_from_registry_pr("v3.0.0") == "spaced-branch"


def test_commit_sha_of_tree():
    """Test tree→commit lookup using git log cache."""
    r = _repo()
    # Mock git command to return commit:tree pairs
    r._git.command = Mock(return_value="sha1 tree1\nsha2 tree2\nsha3 tree3")
    # First lookup builds cache and finds match
    assert r._commit_sha_of_tree("tree1") == "sha1"
    r._git.command.assert_called_once_with("log", "--all", "--format=%H %T")
    # Second lookup uses cache (no additional git command)
    assert r._commit_sha_of_tree("tree2") == "sha2"
    assert r._git.command.call_count == 1  # Still just one call
    # Non-existent tree returns None
    assert r._commit_sha_of_tree("nonexistent") is None


def test_commit_sha_of_tree_subdir_fallback():
    """Test subdirectory tree→commit cache."""
    r = _repo(subdir="path/to/package")
    # git log returns commit SHAs
    r._git.command = Mock(return_value="abc123\ndef456\nghi789")
    # _subdir_tree_hash called for each commit, match on second
    with patch.object(
        r, "_subdir_tree_hash", side_effect=["other", "tree_hash", "another"]
    ):
        assert r._commit_sha_of_tree("tree_hash") == "def456"
        r._git.command.assert_called_once_with("log", "--all", "--format=%H")
        # Cache is built, so subsequent lookups don't call git again
        assert r._commit_sha_of_tree("other") == "abc123"
        assert r._git.command.call_count == 1


def test_commit_sha_of_tree_subdir_fallback_no_match():
    """Test subdirectory cache returns None when no match found."""
    r = _repo(subdir="path/to/package")
    r._git.command = Mock(return_value="abc123\ndef456")
    # No matching subdir tree hash
    with patch.object(r, "_subdir_tree_hash", return_value="other_tree"):
        assert r._commit_sha_of_tree("tree_hash") is None
        assert r._subdir_tree_hash.call_count == 2


def test_commit_sha_of_tag():
    r = _repo()
    # Mock get_git_matching_refs to return tags (used by _build_tags_cache)
    mock_ref1 = Mock(ref="refs/tags/v1.2.3")
    mock_ref1.object.type = "commit"
    mock_ref1.object.sha = "c"
    mock_ref2 = Mock(ref="refs/tags/v2.3.4")
    mock_ref2.object.type = "tag"
    mock_ref2.object.sha = "tag_sha"
    r._repo.get_git_matching_refs = Mock(return_value=[mock_ref1, mock_ref2])
    r._repo.get_git_tag = Mock()
    r._repo.get_git_tag.return_value.object.sha = "t"

    # Test commit tag
    assert r._commit_sha_of_tag("v1.2.3") == "c"
    # Test annotated tag (needs resolution)
    assert r._commit_sha_of_tag("v2.3.4") == "t"
    r._repo.get_git_tag.assert_called_with("tag_sha")
    # Test non-existent tag
    assert r._commit_sha_of_tag("v3.4.5") is None


def test_build_tags_cache():
    """Test _build_tags_cache builds cache from git matching refs."""
    r = _repo()
    mock_ref1 = Mock(ref="refs/tags/v1.0.0")
    mock_ref1.object.type = "commit"
    mock_ref1.object.sha = "abc123"
    mock_ref2 = Mock(ref="refs/tags/v2.0.0")
    mock_ref2.object.type = "tag"
    mock_ref2.object.sha = "def456"
    # get_git_matching_refs("tags/") only returns tag refs
    r._repo.get_git_matching_refs = Mock(return_value=[mock_ref1, mock_ref2])

    cache = r._build_tags_cache()
    assert cache == {"v1.0.0": "abc123", "v2.0.0": "annotated:def456"}
    # Cache should be reused on second call
    r._repo.get_git_matching_refs.reset_mock()
    cache2 = r._build_tags_cache()
    assert cache2 == cache
    r._repo.get_git_matching_refs.assert_not_called()


@patch("tagbot.action.repo.logger")
@patch("tagbot.action.repo.time.sleep")
def test_build_tags_cache_retry(mock_sleep, logger):
    """Test _build_tags_cache retries on failure."""
    r = _repo()
    logger.reset_mock()  # Clear any warnings from _repo() initialization
    mock_ref = Mock(ref="refs/tags/v1.0.0")
    mock_ref.object.type = "commit"
    mock_ref.object.sha = "abc123"
    # Fail twice, succeed on third attempt
    r._repo.get_git_matching_refs = Mock(
        side_effect=[Exception("API error"), Exception("API error"), [mock_ref]]
    )

    cache = r._build_tags_cache(retries=3)
    assert cache == {"v1.0.0": "abc123"}
    assert r._repo.get_git_matching_refs.call_count == 3
    assert mock_sleep.call_count == 2  # Sleep between retries
    assert logger.warning.call_count == 2


@patch("tagbot.action.repo.logger")
@patch("tagbot.action.repo.time.sleep")
def test_build_tags_cache_all_retries_fail(mock_sleep, logger):
    """Test _build_tags_cache returns empty cache after all retries fail."""
    r = _repo()
    r._repo.get_git_matching_refs = Mock(side_effect=Exception("API error"))

    cache = r._build_tags_cache(retries=3)
    assert cache == {}
    assert r._repo.get_git_matching_refs.call_count == 3
    logger.error.assert_called_once()
    assert "after 3 attempts" in logger.error.call_args[0][0]


def test_highest_existing_version():
    """Test _highest_existing_version finds highest semver tag."""
    r = _repo()
    r._build_tags_cache = Mock(
        return_value={
            "v1.0.0": "abc",
            "v2.5.0": "def",
            "v2.4.9": "ghi",
            "v3.0.0-rc1": "jkl",  # Pre-release, lower than 3.0.0
            "not-a-version": "mno",  # Invalid semver, should be skipped
        }
    )
    from semver import VersionInfo

    result = r._highest_existing_version()
    assert result == VersionInfo.parse("3.0.0-rc1")


def test_highest_existing_version_empty():
    """Test _highest_existing_version with no tags."""
    r = _repo()
    r._build_tags_cache = Mock(return_value={})
    assert r._highest_existing_version() is None


def test_highest_existing_version_with_prefix():
    """Test _highest_existing_version respects tag prefix."""
    r = _repo(subdir="path/to/pkg")
    r._Repo__project = {"name": "MyPkg"}
    r._build_tags_cache = Mock(
        return_value={
            "v1.0.0": "abc",  # Wrong prefix
            "MyPkg-v2.0.0": "def",  # Correct prefix
            "MyPkg-v1.5.0": "ghi",  # Correct prefix
        }
    )
    from semver import VersionInfo

    result = r._highest_existing_version()
    assert result == VersionInfo.parse("2.0.0")


@patch("tagbot.action.repo.logger")
def test_version_with_latest_commit_respects_existing_tags(logger):
    """Test that backfilled releases aren't marked latest when newer tags exist."""
    r = _repo()
    from semver import VersionInfo

    # Existing tag v2.0.0 is higher than new version v1.5.0
    r._highest_existing_version = Mock(return_value=VersionInfo.parse("2.0.0"))
    r._Repo__commit_datetimes = {}

    result = r.version_with_latest_commit({"v1.5.0": "abc123"})
    assert result is None
    logger.info.assert_called()
    assert "v2.0.0 is newer" in logger.info.call_args[0][0]


@patch("tagbot.action.repo.logger")
def test_version_with_latest_commit_marks_latest_when_newer(logger):
    """Test that new version is marked latest when it's higher than existing."""
    r = _repo()
    from semver import VersionInfo

    # Existing tag v1.0.0 is lower than new version v2.0.0
    r._highest_existing_version = Mock(return_value=VersionInfo.parse("1.0.0"))
    r._Repo__commit_datetimes = {}
    r._repo.get_commit = Mock()
    r._repo.get_commit.return_value.commit.author.date = datetime.now(timezone.utc)

    result = r.version_with_latest_commit({"v2.0.0": "abc123"})
    assert result == "v2.0.0"


def test_commit_sha_of_release_branch():
    r = _repo()
    r._repo = Mock(default_branch="a")
    r._registry_pr = Mock(return_value=None)
    r._repo.get_branch.return_value.commit.sha = "sha"
    assert r._commit_sha_of_release_branch("v1.0.0") == "sha"
    r._repo.get_branch.assert_called_with("a")


@patch("tagbot.action.repo.logger")
def test_filter_map_versions(logger):
    r = _repo()
    # Mock the caches to avoid real API calls
    r._build_tags_cache = Mock(return_value={})
    r._commit_sha_from_registry_pr = Mock(return_value=None)
    r._commit_sha_of_tree = Mock(return_value=None)
    # No tree or registry PR found - should skip
    assert not r._filter_map_versions({"1.2.3": "tree1"})
    logger.debug.assert_called_with(
        "Skipping v1.2.3: no matching tree or registry PR found"
    )
    # Tree lookup (primary) should be called first
    r._commit_sha_of_tree.assert_called_with("tree1")
    # Registry PR fallback should be called when tree not found
    r._commit_sha_from_registry_pr.assert_called_with("v1.2.3", "tree1")
    # Tree found - should include (no registry PR lookup needed)
    r._commit_sha_of_tree.return_value = "sha"
    r._commit_sha_from_registry_pr.reset_mock()
    assert r._filter_map_versions({"4.5.6": "tree4"}) == {"v4.5.6": "sha"}
    r._commit_sha_from_registry_pr.assert_not_called()
    # Tag exists - skip it silently (no per-version logging for performance)
    r._build_tags_cache.return_value = {"v2.3.4": "existing_sha"}
    assert not r._filter_map_versions({"2.3.4": "tree2"})
    # Registry PR fallback works when tree not found
    r._build_tags_cache.return_value = {}
    r._commit_sha_of_tree.return_value = None
    r._commit_sha_from_registry_pr.return_value = "pr_sha"
    assert r._filter_map_versions({"5.6.7": "tree5"}) == {"v5.6.7": "pr_sha"}


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
        with patch("tagbot.action.repo._get_tagbot_version", return_value="1.2.3"):
            r._report_error("ahh")
    post.assert_called_with(
        f"{TAGBOT_WEB}/report",
        json={
            "image": "id",
            "repo": "Foo/Bar",
            "run": "url",
            "stacktrace": "ahh",
            "version": "1.2.3",
        },
    )


@patch("requests.post")
def test_report_error_with_manual_intervention(post):
    post.return_value.json.return_value = {"status": "ok"}
    r = _repo(token="x")
    r._repo = Mock(full_name="Foo/Bar", private=False)
    r._image_id = Mock(return_value="id")
    r._run_url = Mock(return_value="url")
    r._manual_intervention_issue_url = "https://github.com/Foo/Bar/issues/42"
    with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
        with patch("tagbot.action.repo._get_tagbot_version", return_value="1.2.3"):
            r._report_error("ahh")
    post.assert_called_with(
        f"{TAGBOT_WEB}/report",
        json={
            "image": "id",
            "repo": "Foo/Bar",
            "run": "url",
            "stacktrace": "ahh",
            "version": "1.2.3",
            "manual_intervention_url": "https://github.com/Foo/Bar/issues/42",
        },
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
    contents.decoded_content = b"""repo = "https://GH.COM/Foo/Bar.jl"\n"""
    assert r.is_registered()
    # TODO: We should test for the InvalidProject behaviour,
    # but I'm not really sure how it's possible.


def test_new_versions():
    r = _repo()
    r._versions = lambda min_age=None: (
        {"1.2.3": "abc", "3.4.5": "cde", "2.3.4": "bcd"}
    )
    r._filter_map_versions = lambda vs: vs
    expected = [("1.2.3", "abc"), ("2.3.4", "bcd"), ("3.4.5", "cde")]
    assert list(r.new_versions().items()) == expected


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
    run.assert_any_call(
        ["ssh-keyscan", "-t", "rsa", "gh.com"],
        check=True,
        stdout=open.return_value,
        stderr=DEVNULL,
    )
    # Also verify SSH connection test was called
    run.assert_any_call(
        ["ssh", "-i", "abc", "-o", "UserKnownHostsFile=xyz", "-T", "git@gh.com"],
        text=True,
        capture_output=True,
        timeout=30,
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
    run.assert_any_call(["ssh-agent"], check=True, text=True, capture_output=True)
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
    r._registry_pr = Mock(return_value=None)
    r._git.create_tag = Mock()
    r._repo = Mock(default_branch="default")
    r._repo.get_branch.return_value.commit.sha = "a"
    r._repo.create_git_tag.return_value.sha = "t"
    r._repo.get_releases = Mock(return_value=[])
    r._changelog.get = Mock(return_value="l")
    r.create_release("v1", "a")
    r._git.create_tag.assert_called_with("v1", "a", "l")
    r._repo.create_git_release.assert_called_with(
        "v1",
        "v1",
        "l",
        target_commitish="default",
        draft=False,
        make_latest="true",
        generate_release_notes=False,
    )
    r.create_release("v1", "b")
    r._repo.create_git_release.assert_called_with(
        "v1",
        "v1",
        "l",
        target_commitish="b",
        draft=False,
        make_latest="true",
        generate_release_notes=False,
    )
    r.create_release("v1", "c")
    r._git.create_tag.assert_called_with("v1", "c", "l")
    r._draft = True
    r._git.create_tag.reset_mock()
    r.create_release("v1", "d")
    r._git.create_tag.assert_not_called()
    r._repo.create_git_release.assert_called_with(
        "v1",
        "v1",
        "l",
        target_commitish="d",
        draft=True,
        make_latest="true",
        generate_release_notes=False,
    )
    # Test is_latest=False
    r._draft = False
    r.create_release("v0.9", "e", is_latest=False)
    r._repo.create_git_release.assert_called_with(
        "v0.9",
        "v0.9",
        "l",
        target_commitish="e",
        draft=False,
        make_latest="false",
        generate_release_notes=False,
    )


def test_create_release_skips_existing():
    """Test that create_release skips if release already exists."""
    r = _repo(user="user", email="email")
    r._commit_sha_of_release_branch = Mock(return_value=None)
    r._git.create_tag = Mock()
    r._repo = Mock(default_branch="default")
    r._changelog.get = Mock(return_value="l")
    # Simulate existing release with same tag
    existing_release = Mock(tag_name="v1.0.0")
    r._repo.get_releases = Mock(return_value=[existing_release])
    r.create_release("v1.0.0", "abc123")
    # Should not create tag or release
    r._git.create_tag.assert_not_called()
    r._repo.create_git_release.assert_not_called()
    r._changelog.get.assert_not_called()

    # Different tag should proceed
    r._repo.get_releases = Mock(return_value=[existing_release])
    r.create_release("v2.0.0", "def456")
    r._git.create_tag.assert_called_with("v2.0.0", "def456", "l")
    r._repo.create_git_release.assert_called()


def test_create_release_handles_existing_release_error():
    r = _repo(user="user", email="email")
    r._commit_sha_of_release_branch = Mock(return_value=None)
    r._git.create_tag = Mock()
    r._repo = Mock(default_branch="default")
    r._repo.get_releases = Mock(return_value=[])
    r._changelog.get = Mock(return_value="l")
    r._repo.create_git_release.side_effect = GithubException(
        422, {"errors": [{"code": "already_exists"}]}, {}
    )

    r.create_release("v1.0.0", "abc123")

    r._git.create_tag.assert_called_once()
    r._repo.create_git_release.assert_called_once()


def test_create_release_subdir():
    r = _repo(user="user", email="email", subdir="path/to/Foo.jl")
    r._registry_pr = Mock(return_value=None)
    r._repo.get_contents = Mock(
        return_value=Mock(decoded_content=b"""name = "Foo"\nuuid="abc-def"\n""")
    )
    assert r._tag_prefix() == "Foo-v"
    r._git.create_tag = Mock()
    r._repo = Mock(default_branch="default")
    r._repo.get_branch.return_value.commit.sha = "a"
    r._repo.create_git_tag.return_value.sha = "t"
    r._repo.get_releases = Mock(return_value=[])
    r._changelog.get = Mock(return_value="l")
    r.create_release("v1", "a")
    r._git.create_tag.assert_called_with("Foo-v1", "a", "l")
    r._repo.create_git_release.assert_called_with(
        "Foo-v1",
        "Foo-v1",
        "l",
        target_commitish="default",
        draft=False,
        make_latest="true",
        generate_release_notes=False,
    )
    r.create_release("v1", "b")
    r._repo.create_git_release.assert_called_with(
        "Foo-v1",
        "Foo-v1",
        "l",
        target_commitish="b",
        draft=False,
        make_latest="true",
        generate_release_notes=False,
    )
    r.create_release("v1", "c")
    r._git.create_tag.assert_called_with("Foo-v1", "c", "l")
    r._draft = True
    r._git.create_tag.reset_mock()
    r.create_release("v1", "d")
    r._git.create_tag.assert_not_called()
    r._repo.create_git_release.assert_called_with(
        "Foo-v1",
        "Foo-v1",
        "l",
        target_commitish="d",
        draft=True,
        make_latest="true",
        generate_release_notes=False,
    )


@patch("tagbot.action.repo.logger")
def test_create_release_handles_403_error(logger):
    """Test that 403 permission error logs appropriate message and re-raises."""
    r = _repo(user="user", email="email")
    r._commit_sha_of_release_branch = Mock(return_value=None)
    r._git.create_tag = Mock()
    r._repo = Mock(default_branch="default")
    r._repo.get_releases = Mock(return_value=[])
    r._changelog.get = Mock(return_value="l")
    r._repo.create_git_release.side_effect = GithubException(
        403, {"message": "Resource not accessible by integration"}, {}
    )

    with pytest.raises(GithubException) as exc_info:
        r.create_release("v1.0.0", "abc123")

    # Verify exception is properly re-raised
    assert exc_info.value.status == 403

    # Verify error message was logged
    logger.error.assert_called()
    error_call = logger.error.call_args[0][0]
    assert "Release creation blocked" in error_call
    assert "token lacks required permissions" in error_call
    assert "PAT" in error_call
    assert "contents:write" in error_call


@patch("tagbot.action.repo.logger")
def test_create_release_handles_401_error(logger):
    """Test that 401 authentication error logs appropriate message and re-raises."""
    r = _repo(user="user", email="email")
    r._commit_sha_of_release_branch = Mock(return_value=None)
    r._git.create_tag = Mock()
    r._repo = Mock(default_branch="default")
    r._repo.get_releases = Mock(return_value=[])
    r._changelog.get = Mock(return_value="l")
    r._repo.create_git_release.side_effect = GithubException(
        401, {"message": "Bad credentials"}, {}
    )

    with pytest.raises(GithubException) as exc_info:
        r.create_release("v1.0.0", "abc123")

    # Verify exception is properly re-raised
    assert exc_info.value.status == 401

    # Verify error message was logged
    logger.error.assert_called()
    error_call = logger.error.call_args[0][0]
    assert "Release creation failed" in error_call
    assert "bad credentials" in error_call
    assert "Refresh the token" in error_call
    assert "PAT" in error_call


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
def test_handle_error(mock_logger, format_exc):
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
    mock_logger.error.assert_called_with("Issue reporting failed")


@patch("traceback.format_exc", return_value="ahh")
@patch("tagbot.action.repo.logger")
def test_handle_error_403_checks_rate_limit(mock_logger, format_exc):
    r = _repo()
    r._report_error = Mock()
    r._check_rate_limit = Mock()
    try:
        r.handle_error(GithubException(403, "forbidden", {}))
    except Abort:
        pass
    r._check_rate_limit.assert_called_once()
    assert any("403" in str(call) for call in mock_logger.error.call_args_list)


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


@patch("tagbot.action.repo.Github")
def test_is_version_yanked(mock_github):
    """Test checking if a version is yanked in the registry."""
    mock_gh_instance = Mock()
    mock_github.return_value = mock_gh_instance
    mock_gh_instance.get_repo.return_value = Mock()

    r = _repo(registry="test/registry")
    r._Repo__versions_toml_cache = {
        "1.0.0": {"git-tree-sha1": "abc123"},
        "1.1.0": {"git-tree-sha1": "def456", "yanked": False},
        "1.2.0": {"git-tree-sha1": "ghi789", "yanked": True},
    }

    # Non-yanked version (no yanked key)
    assert r.is_version_yanked("v1.0.0") is False
    assert r.is_version_yanked("1.0.0") is False

    # Non-yanked version (yanked=False)
    assert r.is_version_yanked("v1.1.0") is False

    # Yanked version
    assert r.is_version_yanked("v1.2.0") is True
    assert r.is_version_yanked("1.2.0") is True

    # Version not in registry
    assert r.is_version_yanked("v9.9.9") is False

    # Empty cache (package not registered)
    r._Repo__versions_toml_cache = {}
    assert r.is_version_yanked("v1.0.0") is False
