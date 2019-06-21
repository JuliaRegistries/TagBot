import os

from tagbot import env

from unittest.mock import patch


@patch("builtins.print")
def test_getenv_warn(print):
    assert env._getenv_warn("GITHUB_APP_ID") == os.environ["GITHUB_APP_ID"]
    print.assert_not_called()
    assert env._getenv_warn("FOOBAR") == ""
    print.assert_called_once_with("Variable 'FOOBAR' not in environment (using '')")
    print.reset_mock()
    assert env._getenv_warn("FOOBAR", "default") == "default"
    print.assert_called_once_with(
        "Variable 'FOOBAR' not in environment (using 'default')"
    )
