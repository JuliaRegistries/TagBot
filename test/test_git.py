import os.path

from datetime import datetime
from typing import List, Union
from unittest.mock import Mock, call, patch

import pytest

from tagbot import Abort
from tagbot.git import Git


def _git(
    repo: str = "",
    token: str = "",
    command: Union[str, List[str], None] = None,
    check: Union[str, List[str], None] = None,
) -> Git:
    g = Git(repo, token)
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
    g = Git("Foo/Bar", "x")
    g._Git__dir = "dir"
    run.return_value.configure_mock(stdout=b"out\n", returncode=0)
    assert g.command("a") == "out"
    assert g.command("b", repo=None) == "out"
    assert g.command("c", repo="foo") == "out"
    calls = [
        call(["git", "-C", "dir", "a"], capture_output=True),
        call(["git", "b"], capture_output=True),
        call(["git", "-C", "foo", "c"], capture_output=True),
    ]
    run.assert_has_calls(calls)
    run.return_value.configure_mock(stderr=b"err\n", returncode=1)
    with pytest.raises(Abort):
        g.command("d")


def test_check():
    g = _git(command=["abc", Abort()])
    assert g.check("foo")
    assert not g.check("bar", repo="dir")
    g.command.assert_has_calls([call("foo", repo=""), call("bar", repo="dir")])


@patch("tagbot.git.mkdtemp", return_value="dir")
def test_dir(mkdtemp):
    g = _git(repo="Foo/Bar", token="x", command=["", "branch"])
    assert g._dir == "dir"
    assert g._default_branch == "branch"
    assert g._dir == "dir"
    # Second call should not clone.
    mkdtemp.assert_called_once()
    assert g.command.call_count == 2
    calls = [
        call("clone", "https://oauth2:x@github.com/Foo/Bar", "dir", repo=None),
        call("rev-parse", "--abbrev-ref", "HEAD"),
    ]
    g.command.assert_has_calls(calls)


def test_path():
    g = _git()
    g._Git__dir = "dir"
    assert g.path("foo", "bar") == os.path.join("dir", "foo", "bar")


def test_commit_sha_of_default():
    g = _git(command="abcdef")
    g._default_branch = "branch"
    assert g.commit_sha_of_default() == "abcdef"
    g.command.assert_called_once_with("rev-parse", "branch")


def test_commit_sha_of_tree():
    g = _git(command="a b\n c d\n d e\n")
    assert g.commit_sha_of_tree("b") == "a"
    g.command.assert_called_with("log", "--all", "--format=%H %T")
    assert g.commit_sha_of_tree("e") == "d"
    assert g.commit_sha_of_tree("c") is None


def test_commit_sha_of_tag():
    g = _git(command=["a refs/tags/v1", "b refs/tags/v2\nc refs/tags/v2^{}"])
    assert g.commit_sha_of_tag("v1") == "a"
    g.command.assert_called_with("show-ref", "-d", "v1")
    assert g.commit_sha_of_tag("v2") == "c"
    g.command.assert_called_with("show-ref", "-d", "v2")


def test_invalid_tag_exists():
    g = _git(command=["", "v2", "v3"])
    g.commit_sha_of_tag = Mock(side_effect=["b", "c"])
    assert not g.invalid_tag_exists("v1", "a")
    g.command.assert_called_with("tag", "--list", "v1")
    g.commit_sha_of_tag.assert_not_called()
    assert not g.invalid_tag_exists("v2", "b")
    g.commit_sha_of_tag.assert_called_with("v2")
    assert g.invalid_tag_exists("v2", "d")


def test_set_remote_url():
    g = _git(command="hi")
    g.set_remote_url("url")
    g.command.assert_called_with("remote", "set-url", "origin", "url")


def test_config():
    g = _git(command="ok")
    g.config("a", "b")
    g.command.assert_called_with("config", "a", "b")


def test_create_tag():
    g = _git(command=["", ""])
    g.create_tag("v1.2.3", "abcdef")
    calls = [call("tag", "v1.2.3", "abcdef"), call("push", "origin", "v1.2.3")]
    g.command.assert_has_calls(calls)


def test_fetch_branch():
    g = _git(check=[False, True], command="ok")
    g._default_branch = "default"
    assert not g.fetch_branch("a")
    g.check.assert_called_with("checkout", "a")
    assert g.fetch_branch("b")
    g.command.assert_called_with("checkout", "default")


def test_can_fast_forward():
    g = _git(check=[False, True])
    g._default_branch = "default"
    assert not g.can_fast_forward("a")
    g.check.assert_called_with("merge-base", "--is-ancestor", "default", "a")
    assert g.can_fast_forward("b")


def test_merge_and_delete_branch():
    g = _git(command="ok")
    g._default_branch = "default"
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
