from typing import Any, Callable

from github import Github

from . import env


def logger(level: str) -> Callable[[Any], None]:
    return lambda msg: print(f"::{level} ::{msg}")


debug = logger("debug")
info = print
warn = logger("warning")
error = logger("error")


def die(level: Callable[[Any], None], msg: str, status: int) -> None:
    """Log something, then exit."""
    level(msg)
    exit(status)


def client() -> Github:
    """Create a GitHub client."""
    return Github(env.TOKEN, base_url=env.GITHUB_API)
