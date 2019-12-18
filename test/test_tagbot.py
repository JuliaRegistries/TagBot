from unittest.mock import call, patch

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


@patch("subprocess.run")
def test_git(run):
    run.return_value.stdout = b"hello\n"
    run.return_value.stderr = b""
    run.return_value.returncode = 0
    assert tb.git("a", "b") == "hello"
    assert tb.git("c", "d", repo=None) == "hello"
    assert tb.git("e", "f", repo="foo")
    calls = [
        call(["git", "a", "b"], capture_output=True),
        call(["git", "c", "d"], capture_output=True),
        call(["git", "-C", "foo", "e", "f"], capture_output=True),
    ]
    run.assert_has_calls(calls)
