from .. import stages
from ..context import Context
from ..mixins import AWS, Git, GitHubAPI


class Handler(AWS, Git, GitHubAPI):
    """Creates a Git tag."""

    _this_stage = stages.tag

    def __init__(self, body: dict):
        self.ctx = Context(**body)

    def do(self):
        self.create_tag(self.ctx.repo, self.ctx.version, self.ctx.target)
        next_stage = stages.next(self._this_stage)
        self.invoke(stages.next(self._this_stage), self.ctx)


def handler(body: dict, _ctx=None):
    Handler(body).do()
