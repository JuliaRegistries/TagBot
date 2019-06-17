from typing import Any

from ..aws_lambda import Lambda
from ..context import Context
from ..github_api import GitHubAPI


class Handler(GitHubAPI, Lambda):
    """Creates a GitHub release."""

    def __init__(self, body: dict):
        self.ctx = Context(**body)
        super().__init__()

    def do(self) -> None:
        self.create_release(
            self.ctx.repo, self.ctx.version, self.ctx.commit, self.ctx.release_notes
        )
        # TODO: notify


def handler(body: dict, _ctx: Any = None) -> None:
    Handler(body).do()
