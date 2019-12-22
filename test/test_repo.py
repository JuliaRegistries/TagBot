from datetime import datetime, timedelta
from io import StringIO
from unittest.mock import Mock, patch

from github import UnknownObjectException

from tagbot.repo import Repo


def _repo(*, name="", registry="", token="", changelog=""):
    return Repo(name, registry, token, changelog)


@patch("builtins.open", return_value=StringIO("""name = "FooBar"\nuuid="abc-def"\n"""))
@patch("os.path.isfile", return_value=True)
def test_project(isfile, open):
    r = _repo()
    r._git.path = Mock(return_value="path")
    assert r._project("name") == "FooBar"
    assert r._project("uuid") == "abc-def"
    assert r._project("name") == "FooBar"
    r._git.path.assert_called_once_with("Project.toml")
    isfile.assert_called_once_with("path")


def test_registry_path():
    r = _repo()
    r._registry = Mock()
    r._registry.get_contents.return_value.decoded_content = b"""
    [packages]
    abc-def = { path = "B/Bar" }
    """
    r._project = lambda _k: "abc-ddd"
    assert r._registry_path is None
    r._project = lambda _k: "abc-def"
    assert r._registry_path == "B/Bar"
    assert r._registry_path == "B/Bar"
    assert r._registry.get_contents.call_count == 2


def test_release_exists():
    r = _repo()
    r._repo = Mock()
    r._repo.get_release.side_effect = [1, UnknownObjectException(0, 0)]
    assert r._release_exists("v1.2.3")
    r._repo.get_release.assert_called_with("v1.2.3")
    assert not r._release_exists("v3.2.1")
    r._repo.get_release.assert_called_with("v3.2.1")


def test_create_release_branch_pr():
    r = _repo()
    r._repo = Mock(default_branch="default")
    r._create_release_branch_pr("v1.2.3", "branch")
    r._repo.create_pull.assert_called_once_with(
        title="Merge release branch for v1.2.3", body="", head="branch", base="default",
    )


@patch("tagbot.repo.error")
@patch("tagbot.repo.warn")
@patch("tagbot.repo.info")
def test_filter_map_versions(info, warn, error):
    r = _repo()
    r._git.commit_sha_of_tree = lambda tree: None if tree == "abc" else "sha"
    r._git.invalid_tag_exists = lambda v, _sha: v == "v2.3.4"
    r._release_exists = lambda v: v == "v3.4.5"
    versions = {"1.2.3": "abc", "2.3.4": "bcd", "3.4.5": "cde", "4.5.6": "def"}
    assert r._filter_map_versions(versions) == {"v4.5.6": "sha"}
    info.assert_called_once_with("Release v3.4.5 already exists")
    warn.assert_called_once_with(
        "No matching commit was found for version v1.2.3 (abc)"
    )
    error.assert_called_once_with(
        "Existing tag v2.3.4 points at the wrong commit (expected sha)"
    )


@patch("tagbot.repo.debug")
def test_versions(debug):
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
    debug.assert_not_called()
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
    debug.assert_not_called()
    r._registry.get_commits.return_value = []
    assert r._versions(min_age=delta) == {}
    debug.assert_called_with("No registry commits were found")
    r._registry.get_contents.side_effect = UnknownObjectException(0, 0)
    assert r._versions() == {}
    debug.assert_called_with("Versions.toml was not found")


def test_new_versions():
    r = _repo()
    r._versions = (
        lambda min_age=None: {"1.2.3": "abc"}
        if min_age
        else {"1.2.3": "abc", "2.3.4": "bcd"}
    )
    r._filter_map_versions = lambda vs: vs
    assert r.new_versions() == {"2.3.4": "bcd"}


@patch("requests.post")
def test_create_dispatch_event(post):
    r = _repo(token="x")
    r._repo = Mock(full_name="Foo/Bar")
    r.create_dispatch_event({"a": "b", "c": "d"})
    post.assert_called_once_with(
        "https://api.github.com/repos/Foo/Bar/dispatches",
        headers={
            "Accept": "application/vnd.github.everest-preview+json",
            "Authorization": f"token x",
        },
        json={"event_type": "TagBot", "client_payload": {"a": "b", "c": "d"}},
    )


def test_handle_release_branch():
    r = _repo()
    r._create_release_branch_pr = Mock()
    r._git = Mock(
        fetch_branch=Mock(side_effect=[False, True, True]),
        can_fast_forward=Mock(side_effect=[True, False]),
    )
    r.handle_release_branch("v1")
    r._git.fetch_branch.assert_called_with("release-1")
    r._git.can_fast_forward.assert_not_called()
    r.handle_release_branch("v2")
    r._git.fetch_branch.assert_called_with("release-2")
    r._git.can_fast_forward.assert_called_with("release-2")
    r._git.merge_and_delete_branch.assert_called_with("release-2")
    r.handle_release_branch("v3")
    r._git.fetch_branch.assert_called_with("release-3")
    r._git.can_fast_forward.assert_called_with("release-3")
    r._create_release_branch_pr.assert_called_with("v3", "release-3")


def test_changelog():
    r = _repo()
    r._changelog = Mock()
    r.changelog("v1.2.3", "abcdef")
    r._changelog.get.assert_called_once_with("v1.2.3", "abcdef")


def test_create_release():
    r = _repo()
    r._git.commit_sha_of_default = Mock(return_value="a")
    r._repo = Mock(default_branch="default")
    r.create_release("v1.2.3", "a", "hi")
    r._repo.create_git_release.assert_called_with(
        "v1.2.3", "v1.2.3", "hi", target_commitish="default",
    )
    r.create_release("v1.2.3", "b", "hi")
    r._repo.create_git_release.assert_called_with(
        "v1.2.3", "v1.2.3", "hi", target_commitish="b",
    )
