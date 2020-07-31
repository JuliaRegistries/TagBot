from datetime import datetime
from unittest.mock import Mock, call, patch

import pytest

from tagbot.action import Abort
from tagbot.action.git import Git


def _git(
    github="", repo="", token="", user="user", email="a@b.c", command=None, check=None,
) -> Git:
    g = Git(github, repo, token, user, email)
    if command:
        m = g.command = Mock()
        if isinstance(command, list):
            m.side_effect = command
        else:
            m.return_value = command
    if check:
        m = g.check = Mock()
        if isinstance(check, list):
            m.side_effect = check
        else:
            m.return_value = check
    return g


@patch("subprocess.run")
def test_command(run):
    g = Git("", "Foo/Bar", "x", "user", "email")
    g._Git__dir = "dir"
    run.return_value.configure_mock(stdout="out\n", returncode=0)
    assert g.command("a") == "out"
    assert g.command("b", repo=None) == "out"
    assert g.command("c", repo="foo") == "out"
    calls = [
        call(["git", "-C", "dir", "a"], text=True, capture_output=True),
        call(["git", "b"], text=True, capture_output=True),
        call(["git", "-C", "foo", "c"], text=True, capture_output=True),
    ]
    run.assert_has_calls(calls)
    run.return_value.configure_mock(stderr="err\n", returncode=1)
    with pytest.raises(Abort):
        g.command("d")


def test_check():
    g = _git(command=["abc", Abort()])
    assert g.check("foo")
    assert not g.check("bar", repo="dir")
    g.command.assert_has_calls([call("foo", repo=""), call("bar", repo="dir")])


@patch("tagbot.action.git.mkdtemp", return_value="dir")
def test_dir(mkdtemp):
    g = _git(github="https://gh.com", repo="Foo/Bar", token="x", command=["", "branch"])
    assert g._dir == "dir"
    assert g._dir == "dir"
    # Second call should not clone.
    mkdtemp.assert_called_once()
    g.command.assert_called_once_with(
        "clone", "https://oauth2:x@gh.com/Foo/Bar", "dir", repo=None
    )


def test_default_branch():
    g = _git(command=["foo\nHEAD branch: default\nbar", "uhhhh"])
    assert g._default_branch == "default"
    assert g._default_branch == "default"
    g.command.assert_called_once_with("remote", "show", "origin")
    g._Git__default_branch = None
    assert g._default_branch == "master"


def test_commit_sha_of_tree():
    g = _git(command="a b\n c d\n d e\n")
    assert g.commit_sha_of_tree("b") == "a"
    g.command.assert_called_with("log", "--all", "--format=%H %T")
    assert g.commit_sha_of_tree("e") == "d"
    assert g.commit_sha_of_tree("c") is None


def test_set_remote_url():
    g = _git(command="hi")
    g.set_remote_url("url")
    g.command.assert_called_with("remote", "set-url", "origin", "url")


def test_config():
    g = _git(command="ok")
    g.config("a", "b")
    g.command.assert_called_with("config", "a", "b")


def test_create_tag():
    g = _git(user="me", email="hi@foo.bar", command="hm")
    g.config = Mock()
    g.create_tag("v1", "abcdef", "log")
    calls = [
        call("user.name", "me"),
        call("user.email", "hi@foo.bar"),
    ]
    g.config.assert_has_calls(calls)
    calls = [
        call("tag", "-m", "log", "v1", "abcdef"),
        call("push", "origin", "v1"),
    ]
    g.command.assert_has_calls(calls)


def test_fetch_branch():
    g = _git(check=[False, True], command="ok")
    g._Git__default_branch = "default"
    assert not g.fetch_branch("a")
    g.check.assert_called_with("checkout", "a")
    assert g.fetch_branch("b")
    g.command.assert_called_with("checkout", "default")


def test_is_merged():
    g = _git(command=["b", "a\nb\nc", "d", "a\nb\nc"])
    g._Git__default_branch = "default"
    assert g.is_merged("foo")
    calls = [call("rev-parse", "foo"), call("log", "default", "--format=%H")]
    g.command.assert_has_calls(calls)
    assert not g.is_merged("bar")


def test_can_fast_forward():
    g = _git(check=[False, True])
    g._Git__default_branch = "default"
    assert not g.can_fast_forward("a")
    g.check.assert_called_with("merge-base", "--is-ancestor", "default", "a")
    assert g.can_fast_forward("b")


def test_merge_and_delete_branch():
    g = _git(command="ok")
    g._Git__default_branch = "default"
    g.merge_and_delete_branch("a")
    calls = [
        call("checkout", "default"),
        call("merge", "a"),
        call("push", "origin", "default"),
        call("push", "-d", "origin", "a"),
    ]
    g.command.assert_has_calls(calls)


def test_time_of_commit():
    g = _git(command="2019-12-22T12:49:26+07:00")
    assert g.time_of_commit("a") == datetime(2019, 12, 22, 5, 49, 26)
    g.command.assert_called_with("show", "-s", "--format=%cI", "a")
