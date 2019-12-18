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
    r._Repo__dir = ""
    assert r._project("name") == "FooBar"
    assert r._project("uuid") == "abc-def"
    assert r._project("name") == "FooBar"
    isfile.assert_called_once()


@patch("tagbot.repo.Github")
def test_registry_path(Github):
    r = _repo()
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


@patch("tagbot.repo.Github")
@patch("tagbot.repo.mkdtemp", return_value="dest")
@patch("tagbot.repo.git")
def test_dir(git, mkdtemp, Github):
    r = _repo(token="x")
    r._repo.full_name = "Foo/Bar"
    assert r._dir == "dest"
    assert r._dir == "dest"
    mkdtemp.assert_called_once()
    git.assert_called_once_with("clone", "https://oauth2:x@github.com/Foo/Bar", "dest")


@patch("tagbot.repo.git", return_value="a b\n c d\n d e\n")
def test_commit_from_tree(git):
    r = _repo()
    r._Repo__dir = "dir"
    assert r._commit_from_tree("b") == "a"
    assert r._commit_from_tree("e") == "d"
    assert r._commit_from_tree("c") is None


@patch("tagbot.repo.git", side_effect=["v1.2.3", ""])
def test_tag_exists(git):
    r = _repo()
    r._Repo__dir = "dir"
    assert r._tag_exists("v1.2.3")
    git.assert_called_with("tag", "--list", "v1.2.3", repo="dir")
    assert not r._tag_exists("v3.2.1")
    git.assert_called_with("tag", "--list", "v3.2.1", repo="dir")


@patch("tagbot.repo.Github")
def test_release_exists(Github):
    r = _repo()
    r._repo.get_release.side_effect = [1, UnknownObjectException(0, 0)]
    assert r._release_exists("v1.2.3")
    r._repo.get_release.assert_called_with("v1.2.3")
    assert not r._release_exists("v3.2.1")
    r._repo.get_release.assert_called_with("v3.2.1")


@patch(
    "tagbot.repo.git",
    side_effect=[
        "fedcba refs/tags/v2.3.4^{}",
        "abcdef refs/tags/v3.4.5^{}",
        "abcdef refs/tags/v4.5.6",
    ],
)
def test_invalid_tag_exists(git):
    r = _repo()
    r._Repo__dir = "dir"
    r._tag_exists = lambda _v: False
    assert not r._invalid_tag_exists("v1.2.3", "abcdef")
    r._tag_exists = lambda _v: True
    assert r._invalid_tag_exists("v2.3.4", "abcdef")
    git.assert_called_with("show-ref", "-d", "v2.3.4", repo="dir")
    assert not r._invalid_tag_exists("v3.4.5", "abcdef")
    git.assert_called_with("show-ref", "-d", "v3.4.5", repo="dir")
    assert not r._invalid_tag_exists("v4.5.6", "abcdef")
    git.assert_called_with("show-ref", "-d", "v4.5.6", repo="dir")


@patch("tagbot.repo.error")
@patch("tagbot.repo.warn")
@patch("tagbot.repo.info")
def test_filter_map_versions(info, warn, error):
    r = _repo()
    r._commit_from_tree = lambda tree: None if tree == "abc" else "sha"
    r._invalid_tag_exists = lambda v, _sha: v == "v2.3.4"
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


@patch("tagbot.repo.Github")
@patch("tagbot.repo.debug")
def test_versions(debug, Github):
    r = _repo()
    r._Repo__registry_path = "path"
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
    args, kwargs = r._registry.get_commits.mock_calls[0][1:]
    assert not args
    assert len(kwargs) == 1 and "until" in kwargs
    assert isinstance(kwargs["until"], datetime)
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


@patch("tagbot.repo.Github")
@patch("requests.post")
def test_create_dispatch_event(post, Github):
    r = _repo(token="x")
    r._repo.full_name = "Foo/Bar"
    r.create_dispatch_event({"a": "b", "c": "d"})
    post.assert_called_once_with(
        "https://api.github.com/repos/Foo/Bar/dispatches",
        headers={
            "Accept": "application/vnd.github.everest-preview+json",
            "Authorization": f"token x",
        },
        json={"event_type": "TagBot", "client_payload": {"a": "b", "c": "d"}},
    )


def test_changelog():
    r = _repo()
    r._changelog = Mock()
    r.changelog("v1.2.3")
    r._changelog.get.assert_called_once_with("v1.2.3")


@patch("tagbot.repo.Github")
@patch("tagbot.repo.git")
def test_create_release(git, Github):
    r = _repo(name="Foo/Bar")
    r._Repo__dir = "dir"
    r._repo.default_branch = "master"
    git.return_value = "abcdef"
    r.create_release("v1.2.3", "abcdef", "hi")
    r._repo.create_git_release.assert_called_once_with(
        "v1.2.3", "v1.2.3", "hi", target_commitish="master"
    )
    git.return_value = "aaaaaa"
    r.create_release("v3.2.1", "abcdef", None)
    r._repo.create_git_release.assert_called_with(
        "v3.2.1", "v3.2.1", "", target_commitish="abcdef"
    )
