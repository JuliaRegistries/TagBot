from unittest.mock import Mock, call, patch

import tagbot as tb


@patch("builtins.print")
def test_loggers(print):
    tb.debug("a")
    tb.info("b")
    tb.warn("c")
    assert tb.STATUS == 0
    tb.error("d")
    assert tb.STATUS == 1
    calls = [call("::debug ::a"), call("b"), call("::warning ::c"), call("::error ::d")]
    print.assert_has_calls(calls)


@patch("subprocess.run", return_value=Mock(stdout=b"hello\n", stderr=b"", returncode=0))
def test_git(run):
    assert tb.git("a", "b") == "hello"
    assert tb.git("c", "d", repo=None) == "hello"
    assert tb.git("e", "f", repo="foo")
    calls = [
        call(["git", "a", "b"], capture_output=True),
        call(["git", "c", "d"], capture_output=True),
        call(["git", "-C", "foo", "e", "f"], capture_output=True),
    ]
    run.assert_has_calls(calls)


@patch("tagbot.git", side_effect=["", tb.Abort()])
def test_git_check(git):
    assert tb.git_check("a") is True
    git.assert_called_with("a", repo=None)
    assert tb.git_check("b", repo="dir") is False
    git.assert_called_with("b", repo="dir")
