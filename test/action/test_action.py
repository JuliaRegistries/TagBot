from unittest.mock import call, patch

from tagbot import action


@patch("builtins.print")
def test_loggers(print):
    action.debug("a")
    action.info("b")
    action.warn("c")
    action.error("d")
    calls = [call("::debug ::a"), call("b"), call("::warning ::c"), call("::error ::d")]
    print.assert_has_calls(calls)
    action.debug("foo\nbar")
    print.assert_called_with("::debug ::foo\n::debug ::bar")
