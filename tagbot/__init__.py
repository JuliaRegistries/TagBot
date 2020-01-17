from datetime import timedelta

DELTA = timedelta(days=3)  # Maximum age of new versions/merged registry PRs.
STATUS = 0  # Exit status for the main script.


class Abort(Exception):
    pass


def _log(message: str, prefix: str) -> None:
    """Print out a log message."""
    print("\n".join(f"::{prefix} ::{line}" for line in message.splitlines()))


def debug(msg: str) -> None:
    """Write a debug message, which only shows up if the user opts into them."""
    _log(msg, "debug")


def info(msg: str) -> None:
    """Write an info message."""
    print(msg)


def warn(msg: str) -> None:
    """Write a warning message."""
    _log(msg, "warning")


def error(msg: str) -> None:
    """Write an error message, and set the exit code to be non-zero."""
    global STATUS
    STATUS += 1
    _log(msg, "error")
