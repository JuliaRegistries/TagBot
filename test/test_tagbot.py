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
