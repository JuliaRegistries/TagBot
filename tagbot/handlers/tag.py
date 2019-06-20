from typing import Any

from .. import context
from ..context import Context
from ..mixins.aws import AWS
from ..mixins.git import Git
from ..mixins.github_api import GitHubAPI


class Handler(AWS, Git, GitHubAPI):
    """Creates a Git tag."""

    _next_step = "changelog"

    def __init__(self, body: dict):
        self.ctx = Context(**body)

    def do(self):
        self.create_tag(self.ctx.repo, self.ctx.version, self.ctx.target)
        self.invoke(self._next_step, self.ctx)


def handler(body: dict, _ctx: Any = None):
    Handler(body).do()
