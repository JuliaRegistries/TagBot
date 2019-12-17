import tagbot

from datetime import datetime, timedelta
from io import StringIO
from unittest.mock import Mock, call, patch

from github import UnknownObjectException

from tagbot.repo import Repo


@patch("builtins.open", return_value=StringIO("""name = "FooBar"\nuuid="abc-def"\n"""))
@patch("os.path.isfile", return_value=True)
def test_project(isfile, open):
    r = Repo("", "", "")
    r._dir = lambda: ""
    assert r._project("name") == "FooBar"
    assert r._project("uuid") == "abc-def"
    assert r._project("name") == "FooBar"
    isfile.assert_called_once()


def test_registry_path():
    r = Repo("", "registry", "")
    gh = r._Repo__gh = Mock()
    gh.get_repo.return_value.get_contents.return_value.decoded_content = b"""
    [packages]
    abc-def = { path = "B/Bar" }
    """
    r._project = lambda _k: "abc-ddd"
    assert r._registry_path() is None
    gh.get_repo.assert_called_once_with("registry")
    r._project = lambda _k: "abc-def"
    assert r._registry_path() == "B/Bar"
    assert r._registry_path() == "B/Bar"
    assert gh.get_repo.call_count == 2


@patch("tagbot.repo.mkdtemp", return_value="dest")
@patch("tagbot.repo.git")
def test_dir(git, mkdtemp):
    r = Repo("Foo/Bar", "", "x")
    assert r._dir() == "dest"
    assert r._dir() == "dest"
    mkdtemp.assert_called_once()
    git.assert_called_once_with("clone", "https://oauth2:x@github.com/Foo/Bar", "dest")


@patch("tagbot.repo.git", return_value="a b\n c d\n d e\n")
def test_commit_from_tree(git):
    r = Repo("", "", "")
    r._dir = lambda: "dir"
    assert r._commit_from_tree("b") == "a"
    assert r._commit_from_tree("e") == "d"
    assert r._commit_from_tree("c") is None


@patch(
    "tagbot.repo.git",
    side_effect=[
        "",
        "v2.3.4",
        "fedcba refs/tags/v2.3.4^{}",
        "v3.4.5",
        "abcdef refs/tags/v3.4.5^{}",
    ],
)
def test_invalid_tag_exists(git):
    r = Repo("", "", "")
    r._dir = lambda: "dir"
    assert not r._invalid_tag_exists("v1.2.3", "abcdef")
    git.assert_called_with("tag", "--list", "v1.2.3", repo="dir")
    assert r._invalid_tag_exists("v2.3.4", "abcdef")
    git.assert_has_calls(
        [
            call("tag", "--list", "v2.3.4", repo="dir"),
            call("show-ref", "-d", "v2.3.4", repo="dir"),
        ]
    )
    assert not r._invalid_tag_exists("v3.4.5", "abcdef")
    git.assert_has_calls(
        [
            call("tag", "--list", "v3.4.5", repo="dir"),
            call("show-ref", "-d", "v3.4.5", repo="dir"),
        ]
    )


def test_release_exists():
    r = Repo("", "", "")
    gh = r._Repo__gh = Mock()
    get_release = gh.get_repo.return_value.get_release
    get_release.side_effect = [1, UnknownObjectException(0, 0)]
    assert r._release_exists("v1.2.3")
    get_release.assert_called_with("v1.2.3")
    assert not r._release_exists("v3.2.1")
    get_release.assert_called_with("v3.2.1")


@patch("tagbot.repo.error")
@patch("tagbot.repo.warn")
@patch("tagbot.repo.info")
def test_filter_map_versions(info, warn, error):
    r = Repo("", "", "")
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


@patch("tagbot.repo.debug")
def test_versions(debug):
    r = Repo("", "registry", "")
    r._filter_map_versions = lambda vs: vs
    r._registry_path = lambda: "path"
    gh = r._Repo__gh = Mock()
    gh_repo = gh.get_repo.return_value
    gh_repo.get_contents.return_value.decoded_content = b"""
    ["1.2.3"]
    git-tree-sha1 = "abc"

    ["2.3.4"]
    git-tree-sha1 = "bcd"
    """
    assert r._versions() == {"1.2.3": "abc", "2.3.4": "bcd"}
    gh.get_repo.assert_called_with("registry")
    gh_repo.get_contents.assert_called_with("path/Versions.toml")
    debug.assert_not_called()
    commit = Mock()
    commit.commit.sha = "abcdef"
    gh_repo.get_commits.return_value = [commit]
    delta = timedelta(days=3)
    assert r._versions(min_age=delta) == {"1.2.3": "abc", "2.3.4": "bcd"}
    gh_repo.get_commits.assert_called_once()
    [call] = gh_repo.get_commits.mock_calls
    assert not call.args and len(call.kwargs) == 1 and "until" in call.kwargs
    assert isinstance(call.kwargs["until"], datetime)
    gh_repo.get_contents.assert_called_with("path/Versions.toml", ref="abcdef")
    debug.assert_not_called()
    gh_repo.get_commits.return_value = []
    assert r._versions(min_age=delta) == {}
    debug.assert_called_with("No registry commits were found")
    gh_repo.get_contents.side_effect = UnknownObjectException(0, 0)
    assert r._versions() == {}
    debug.assert_called_with("Versions.toml was not found")


def test_new_versions():
    r = Repo("", "", "")
    r._versions = (
        lambda min_age=None: {"1.2.3": "abc"}
        if min_age
        else {"1.2.3": "abc", "2.3.4": "bcd"}
    )
    r._filter_map_versions = lambda vs: vs
    assert r.new_versions() == {"2.3.4": "bcd"}


@patch("requests.post")
def test_create_dispatch_event(post):
    r = Repo("Foo/Bar", "", "x")
    r.create_dispatch_event({"a": "b", "c": "d"})
    post.assert_called_once_with(
        "https://api.github.com/repos/Foo/Bar/dispatches",
        headers={
            "Accept": "application/vnd.github.everest-preview+json",
            "Authorization": f"token x",
        },
        json={"event_type": "TagBot", "client_payload": {"a": "b", "c": "d"}},
    )


@patch("tagbot.repo.get_changelog")
def test_changelog(get_changelog):
    r = Repo("Foo/Bar", "Bar/Baz", "x")
    r._project = lambda k: k
    r.changelog("v1.2.3")
    get_changelog.assert_called_once_with(
        name="name",
        registry="Bar/Baz",
        repo="Foo/Bar",
        token="x",
        uuid="uuid",
        version="v1.2.3",
    )


@patch("tagbot.repo.git")
def test_create_release(git):
    r = Repo("Foo/Bar", "", "")
    r._dir = lambda: "dir"
    gh = r._Repo__gh = Mock()
    gh_repo = gh.get_repo.return_value
    gh_repo.default_branch = "master"
    git.return_value = "abcdef"
    r.create_release("v1.2.3", "abcdef", "hi")
    gh.get_repo.assert_called_once_with("Foo/Bar", lazy=True)
    gh_repo.create_git_release.assert_called_once_with(
        "v1.2.3", "v1.2.3", "hi", target_commitish="master"
    )
    git.return_value = "aaaaaa"
    r.create_release("v3.2.1", "abcdef", None)
    gh_repo.create_git_release.assert_called_with(
        "v3.2.1", "v3.2.1", "", target_commitish="abcdef"
    )
