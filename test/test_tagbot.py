from unittest.mock import call, patch

import tagbot as tb


@patch("__main__.print")
def test_loggers(print):
    tb.debug("a")
    tb.info("b")
    tb.warn("c")
    tb.error("d")
    calls = [call("::debug ::a"), call("b"), call("::warning c"), call("::error d")]
    assert print.has_calls(calls)
