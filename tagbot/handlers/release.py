from .. import stages
from ..context import Context
from ..mixins import AWS, GitHubAPI


class Handler(AWS, GitHubAPI):
    """Creates a GitHub release."""

    _this_stage = stages.release

    def __init__(self, body: dict):
        self.ctx = Context(**body)

    def do(self) -> None:
        self.create_release(
            self.ctx.repo, self.ctx.version, self.ctx.commit, self.ctx.changelog
        )
        # TODO: notify


def handler(body: dict, _ctx=None) -> None:
    Handler(body).do()
