from typing import Any

from ..context import Context
from ..github_api import GitHubAPI


class Handler(GitHubAPI):
    def __init__(self, body: dict):
        self.ctx = Context(**body)
        super().__init__()

    def do(self):
        if not self.ctx.notification:
            print("Notification field is empty")
            return
        issue = self.get_issue(self.ctx.repo, self.ctx.issue)
        if self.ctx.comment_id is None:
            self.create_comment(issue, self.ctx.notification)
        else:
            comment = self.get_issue_comment(self.ctx.repo, self.ctx.issue, self.ctx.comment_id)
            self.append_comment(comment, self.ctx.notification)


def handler(body: dict, _ctx: Any = None) -> None:
    Handler(body).do()
