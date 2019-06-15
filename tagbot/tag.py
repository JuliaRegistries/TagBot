from . import context
from .github_api import GitHubAPI


class Handler(Git, GitHubAPI):
    def __init__(self, evt):
        self.ctxs = context.from_records(evt)
        super().__init__()

    def do(self):
        for ctx in self.ctxs:
            self.create_tag(ctx.repo, ctx.version, ctx.target)


def handler(evt, _ctx=None):
    Handler(evt).do()
