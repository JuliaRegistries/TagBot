from ..context import Context
from ..mixins import AWS, GitHubAPI


class Handler(AWS, GitHubAPI):
    """Comments on GitHub issues."""

    def __init__(self, body: dict):
        self.ctx = Context(**body)

    def do(self):
        if not self.ctx.notification:
            print("Notification field is empty")
            return
        issue = self.get_issue(self.ctx.repo, self.ctx.issue)
        comment = self.get_issue_comment(
            self.ctx.repo, self.ctx.issue, self.ctx.comment_id
        )
        self.append_comment(comment, self.ctx.notification)


def handler(body: dict, _ctx=None) -> None:
    Handler(body).do()
