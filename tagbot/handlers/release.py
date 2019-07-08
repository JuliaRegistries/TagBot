from .. import Context
from ..mixins import AWS, GitHubAPI


class Handler(AWS, GitHubAPI):
    """Creates a GitHub release."""

    def __init__(self, body: dict):
        self.ctx = Context(**body)

    def do(self) -> None:
        self.ctx.dump()
        release = self.create_release(
            self.ctx.repo, self.ctx.version, self.ctx.commit, self.ctx.changelog
        )
        msg = f"All done! [Here]({release.html_url}) is your new release."
        self.invoke_notify(self.ctx, msg)


def handler(body: dict, _ctx=None) -> None:
    Handler(body).do()
