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


@patch("tagbot.repo.Github")
def test_registry_path(Github):
    r = Repo("", "", "")
    r._Repo__registry.get_contents.return_value.decoded_content = b"""
    [packages]
    abc-def = { path = "B/Bar" }
    """
    r._project = lambda _k: "abc-ddd"
    assert r._registry_path() is None
    r._project = lambda _k: "abc-def"
    assert r._registry_path() == "B/Bar"
    assert r._registry_path() == "B/Bar"
    assert r._Repo__registry.get_contents.call_count == 2


@patch("tagbot.repo.Github")
@patch("tagbot.repo.mkdtemp", return_value="dest")
@patch("tagbot.repo.git")
def test_dir(git, mkdtemp, Github):
    r = Repo("", "", "x")
    r._Repo__repo.full_name = "Foo/Bar"
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


@patch("tagbot.repo.git_check", side_effect=[True, False])
@patch("tagbot.repo.git", return_value="")
def test_fetch_branch(git, git_check):
    r = Repo("", "", "")
    r._dir = lambda: "dir"
    assert r._fetch_branch("master", "foo")
    git_check.assert_called_with("checkout", "foo", repo="dir")
    git.assert_called_with("checkout", "master", repo="dir")
    assert not r._fetch_branch("master", "bar")
    git_check.assert_called_with("checkout", "bar", repo="dir")


@patch("tagbot.repo.git", side_effect=["v1.2.3", ""])
def test_tag_exists(git):
    r = Repo("", "", "")
    r._dir = lambda: "dir"
    assert r._tag_exists("v1.2.3")
    git.assert_called_with("tag", "--list", "v1.2.3", repo="dir")
    assert not r._tag_exists("v3.2.1")
    git.assert_called_with("tag", "--list", "v3.2.1", repo="dir")


@patch("tagbot.repo.Github")
def test_release_exists(Github):
    r = Repo("", "", "")
    r._Repo__repo.get_release.side_effect = [1, UnknownObjectException(0, 0)]
    assert r._release_exists("v1.2.3")
    r._Repo__repo.get_release.assert_called_with("v1.2.3")
    assert not r._release_exists("v3.2.1")
    r._Repo__repo.get_release.assert_called_with("v3.2.1")


@patch(
    "tagbot.repo.git",
    side_effect=[
        "fedcba refs/tags/v2.3.4^{}",
        "abcdef refs/tags/v3.4.5^{}",
        "abcdef refs/tags/v4.5.6",
    ],
)
def test_invalid_tag_exists(git):
    r = Repo("", "", "")
    r._dir = lambda: "dir"
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


@patch("tagbot.repo.Github")
@patch("tagbot.repo.debug")
def test_versions(debug, Github):
    r = Repo("", "", "")
    r._filter_map_versions = lambda vs: vs
    r._registry_path = lambda: "path"
    registry = r._Repo__registry
    registry.get_contents.return_value.decoded_content = b"""
    ["1.2.3"]
    git-tree-sha1 = "abc"

    ["2.3.4"]
    git-tree-sha1 = "bcd"
    """
    assert r._versions() == {"1.2.3": "abc", "2.3.4": "bcd"}
    registry.get_contents.assert_called_with("path/Versions.toml")
    debug.assert_not_called()
    commit = Mock()
    commit.commit.sha = "abcdef"
    registry.get_commits.return_value = [commit]
    delta = timedelta(days=3)
    assert r._versions(min_age=delta) == {"1.2.3": "abc", "2.3.4": "bcd"}
    registry.get_commits.assert_called_once()
    assert len(registry.get_commits.mock_calls) == 1
    args, kwargs = registry.get_commits.mock_calls[0][1:]
    assert not args
    assert len(kwargs) == 1 and "until" in kwargs
    assert isinstance(kwargs["until"], datetime)
    registry.get_contents.assert_called_with("path/Versions.toml", ref="abcdef")
    debug.assert_not_called()
    registry.get_commits.return_value = []
    assert r._versions(min_age=delta) == {}
    debug.assert_called_with("No registry commits were found")
    registry.get_contents.side_effect = UnknownObjectException(0, 0)
    assert r._versions() == {}
    debug.assert_called_with("Versions.toml was not found")


@patch("tagbot.repo.git_check", side_effect=[True, False])
def test_can_fast_forward(git_check):
    r = Repo("", "", "")
    r._dir = lambda: "dir"
    assert r._can_fast_forward("master1", "branch1")
    git_check.assert_called_with(
        "merge-base", "--is-ancestor", "master1", "branch1", repo="dir"
    )
    assert not r._can_fast_forward("master2", "branch2")
    git_check.assert_called_with(
        "merge-base", "--is-ancestor", "master2", "branch2", repo="dir",
    )


@patch("tagbot.repo.git")
def test_merge_and_delete_branch(git):
    r = Repo("", "", "")
    r._dir = lambda: "dir"
    r._merge_and_delete_branch("master", "branch")
    git.assert_has_calls(
        [
            call("checkout", "master", repo="dir"),
            call("merge", "branch", repo="dir"),
            call("push", "origin", "master", repo="dir"),
            call("push", "-d", "origin", "branch", repo="dir"),
        ]
    )


@patch("tagbot.repo.Github")
def test_create_release_branch_pr(Github):
    r = Repo("", "", "")
    r._create_release_branch_pr("v1.2.3", "master", "branch")
    r._Repo__repo.create_pull.assert_called_once_with(
        title="Merge release branch for v1.2.3", head="branch", base="master"
    )


def test_new_versions():
    r = Repo("", "", "")
    r._versions = (
        lambda min_age=None: {"1.2.3": "abc"}
        if min_age
        else {"1.2.3": "abc", "2.3.4": "bcd"}
    )
    r._filter_map_versions = lambda vs: vs
    assert r.new_versions() == {"2.3.4": "bcd"}


@patch("tagbot.repo.Github")
def test_handle_release_branch(Github):
    r = Repo("", "", "")
    r._Repo__repo.default_branch = "master"
    r._fetch_branch = Mock(side_effect=[False, True, True])
    r._can_fast_forward = Mock(side_effect=[True, False])
    r._merge_and_delete_branch = Mock()
    r._create_release_branch_pr = Mock()
    r.handle_release_branch("v1.2.3")
    r._fetch_branch.assert_called_with("master", "release-1.2.3")
    r.handle_release_branch("v2.3.4")
    r._merge_and_delete_branch.assert_called_once_with("master", "release-2.3.4")
    r.handle_release_branch("v3.4.5")
    r._create_release_branch_pr.assert_called_once_with(
        "v3.4.5", "master", "release-3.4.5"
    )


@patch("tagbot.repo.Github")
@patch("requests.post")
def test_create_dispatch_event(post, Github):
    r = Repo("", "", "x")
    r._Repo__repo.full_name = "Foo/Bar"
    r.create_dispatch_event({"a": "b", "c": "d"})
    post.assert_called_once_with(
        "https://api.github.com/repos/Foo/Bar/dispatches",
        headers={
            "Accept": "application/vnd.github.everest-preview+json",
            "Authorization": f"token x",
        },
        json={"event_type": "TagBot", "client_payload": {"a": "b", "c": "d"}},
    )


@patch("tagbot.repo.Github")
@patch("tagbot.repo.get_changelog")
def test_changelog(get_changelog, Github):
    Github.return_value.get_repo.side_effect = Mock
    r = Repo("", "", "x")
    r._Repo__repo.full_name = "Foo/Bar"
    r._Repo__registry.full_name = "Bar/Baz"
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


@patch("tagbot.repo.Github")
@patch("tagbot.repo.git")
def test_create_release(git, Github):
    r = Repo("Foo/Bar", "", "")
    r._dir = lambda: "dir"
    r._Repo__repo.default_branch = "master"
    git.return_value = "abcdef"
    r.create_release("v1.2.3", "abcdef", "hi")
    r._Repo__repo.create_git_release.assert_called_once_with(
        "v1.2.3", "v1.2.3", "hi", target_commitish="master"
    )
    git.return_value = "aaaaaa"
    r.create_release("v3.2.1", "abcdef", None)
    r._Repo__repo.create_git_release.assert_called_with(
        "v3.2.1", "v3.2.1", "", target_commitish="abcdef"
    )
