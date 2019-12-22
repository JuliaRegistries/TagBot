from datetime import timedelta

DELTA = timedelta(days=3)  # Maximum age of new versions/merged registry PRs.
STATUS = 0  # Exit status for the main script.


class Abort(Exception):
    pass


def debug(msg: str) -> None:
    """Write a debug message, which only shows up if the user opts into them."""
    print(f"::debug ::{msg}")


def info(msg: str) -> None:
    """Write an info message."""
    print(msg)


def warn(msg: str) -> None:
    """Write a warning message."""
    print(f"::warning ::{msg}")


def error(msg: str) -> None:
    """Write an error message, and set the exit code to be non-zero."""
    global STATUS
    STATUS += 1
    print(f"::error ::{msg}")
