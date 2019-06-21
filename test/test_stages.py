from unittest.mock import patch

from tagbot import stages


@patch("builtins.print")
def test_next(print):
    assert stages.next(stages.prepare) == stages.tag
    assert stages.next(stages.tag) == stages.changelog
    assert stages.next(stages.changelog) == stages.release
    assert stages.next(stages.release) is None
    assert stages.next(stages.notify) is None
    print.assert_not_called()
    assert stages.next("unknown") is None
    print.assert_called_once_with("Unknown stage:", "unknown")


@patch("builtins.print")
def test_after_failure(print):
    assert stages.after_failure(stages.prepare) is None
    assert stages.after_failure(stages.tag) == stages.changelog
    assert stages.after_failure(stages.changelog) == stages.release
    assert stages.after_failure(stages.release) is None
    assert stages.after_failure(stages.notify) is None
    print.assert_not_called()
    assert stages.after_failure("unknown") is None
    print.assert_called_once_with("Unknown stage:", "unknown")


@patch("builtins.print")
def test_action(print):
    assert stages.action(stages.prepare) == "prepare a job context"
    assert stages.action(stages.tag) == "create a Git tag"
    assert stages.action(stages.changelog) == "generate a changelog"
    assert stages.action(stages.release) == "create a GitHub release"
    assert stages.action(stages.notify) == "send a notification"
    print.assert_not_called()
    assert stages.action("unknown") is None
    print.assert_called_once_with("Unknown stage:", "unknown")
