import json

from typing import Any

from ..context import Context
from ..github_api import GitHubAPI


class Handler(GitHubAPI):
    """Notifies of failure."""

    def __init__(self, event: dict):
        self.ctxs = [
            Context(**json.loads(r["Sns"]["Message"])) for r in event["Records"]
        ]
        super().__init__()

    def do(self) -> None:
        for ctx in self.ctxs:
            pass
            # TODO: notify


def handler(event: dict, _ctx: Any = None) -> None:
    Handler(event).do()
