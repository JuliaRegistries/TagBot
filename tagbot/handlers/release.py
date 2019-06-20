from typing import Any

from ..enums import stages
from ..context import Context
from ..mixins.aws import AWS
from ..mixins.github_api import GitHubAPI


class Handler(AWS, GitHubAPI):
    """Creates a GitHub release."""

    _this_stage = stages.release

    def __init__(self, body: dict, aws_id: str):
        self.ctx = Context(**body)
        self.aws_id = aws_id

    def do(self) -> None:
        self.put_item(self.aws_id, self._this_stage)
        self.create_release(
            self.ctx.repo, self.ctx.version, self.ctx.commit, self.ctx.release_notes
        )
        # TODO: notify


def handler(body: dict, _ctx: Any = None) -> None:
    Handler(body).do()
