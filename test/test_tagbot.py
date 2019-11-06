import tempfile

from unittest.mock import call, patch

import tagbot as tb


@patch("sys.stdout")
def test_loggers(stdout):
    tb.debug("a")
    tb.info("b")
    tb.warn("c")
    tb.error("d")
    calls = [call("::debug ::a"), call("b"), call("::warning c"), call("::error d")]
    stdout.write.assert_any_call("::debug ::a")
    stdout.write.assert_any_call("b")
    stdout.write.assert_any_call("::warning ::c")
    stdout.write.assert_any_call("::error ::d")


@patch("subprocess.run")
def test_git(run):
    run.return_value.stdout = b"hello\n"
    run.return_value.stderr = b""
    run.return_value.returncode = 0
    assert tb.git("a", "b") == "hello"
    assert tb.git("c", "d", root=None) == "hello"
    assert tb.git("e", "f", root=tempfile.gettempdir())
    calls = [
        call(["git", "-C", tb.env.REPO_DIR, "a", "b"], capture_output=True),
        call(["git", "c", "d"], capture_output=True),
        call(["git", "-C", tempfile.gettempdir(), "e", "f"], capture_output=True),
    ]
    run.assert_has_calls(calls)
