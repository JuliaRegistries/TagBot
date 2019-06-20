from typing import Any

from ..enums import stages
from ..context import Context
from ..mixins.aws import AWS
from ..mixins.github_api import GitHubAPI


class Handler(AWS, GitHubAPI):
    """Comments on GitHub issues."""

    _this_stage = stages.notify

    def __init__(self, body: dict, aws_id: str):
        self.ctx = Context(**body)
        self.aws_id = aws_id

    def do(self):
        self.put_item(self.aws_id, self._this_stage)
        if not self.ctx.notification:
            print("Notification field is empty")
            return
        issue = self.get_issue(self.ctx.repo, self.ctx.issue)
        if self.ctx.comment_id is None:
            self.create_comment(issue, self.ctx.notification)
        else:
            comment = self.get_issue_comment(
                self.ctx.repo, self.ctx.issue, self.ctx.comment_id
            )
            self.append_comment(comment, self.ctx.notification)


def handler(body: dict, ctx) -> None:
    Handler(body, ctx.aws_request_id).do()
