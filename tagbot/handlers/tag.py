from .. import Context, stages
from ..mixins import AWS, Git, GitHubAPI


class Handler(AWS, Git, GitHubAPI):
    """Creates a Git tag."""

    _this_stage = stages.tag
    _next_stage = stages.next(_this_stage)

    def __init__(self, body: dict):
        self.ctx = Context(**body)

    def do(self):
        self.ctx.dump()
        if self.tag_exists(self.ctx.repo, self.ctx.version):
            print("Tag exists")
        else:
            msg = f"See github.com/{self.ctx.repo}/releases/tag/{self.ctx.version}"
            auth = self.auth_token(self.ctx.repo)
            self.create_tag(self.ctx.repo, self.ctx.version, self.ctx.target, msg, auth)
        self.invoke(self._next_stage, self.ctx)


def handler(body: dict, _ctx=None):
    Handler(body).do()
