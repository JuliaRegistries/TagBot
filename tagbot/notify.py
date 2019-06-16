from typing import Any

from .context import Context
from .github_api import GitHubAPI


class Handler(GitHubAPI):
    def __init__(self, body: dict):
        self.ctx = Context(**body)
        super().__init__()

    def do(self):
        pass


def handler(body: dict, _ctx: Any = None) -> None:
    Handler(body).do()
