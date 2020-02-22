from unittest.mock import call, patch

import tagbot


@patch("builtins.print")
def test_loggers(print):
    tagbot.debug("a")
    tagbot.info("b")
    tagbot.warn("c")
    tagbot.error("d")
    calls = [call("::debug ::a"), call("b"), call("::warning ::c"), call("::error ::d")]
    print.assert_has_calls(calls)
    tagbot.debug("foo\nbar")
    print.assert_called_with("::debug ::foo\n::debug ::bar")
