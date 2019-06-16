from typing import Any

from . import context
from .aws_lambda import Lambda
from .context import Context
from .git import Git
from .github_api import GitHubAPI


class Handler(Git, GitHubAPI):
    """Creates a Git tag."""

    _next_step = "changelog"

    def __init__(self, body: dict):
        self.ctx = Context(**body)
        super().__init__()

    def do(self):
        self.create_tag(self.ctx.repo, self.ctx.version, self.ctx.target)
        self.invoke(self._next_step, self.ctx)


def handler(body: dict, _ctx: Any = None):
    Handler(body).do()
