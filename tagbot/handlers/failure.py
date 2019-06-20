import json

from typing import Any

from ..enums import stages
from ..context import Context
from ..mixins.github_api import GitHubAPI


class Handler(GitHubAPI):
    """Notifies of failure."""

    def __init__(self, event: dict):
        self.ctxs = []
        self.stages = []
        self.errors = []
        for r in event["Records"]:
            self.ctxs.push(Context(**json.loads(r["Sns"]["Message"])))
            self.stages.push(
                self.get_item(r["MessageAttributes"]["RequestId"]["Value"])
            )
            self.errors.push(r["MessageAttributes"]["ErrorMessage"]["Value"])

    def do(self) -> None:
        for ctx, stage, error in zip(self.ctxs, self.stages, self.errors):
            if stage == stages.prepare:
                action = "prepare a job context"
            elif stage == stages.tag:
                action = "create a Git tag"
            elif stage == stages.changelog:
                action = "generate a changelog"
            elif stage == stages.release:
                action = "create a GitHub release"
            elif stage == stages.notify:
                action = "send a notification"
            comment = self.get_issue_comment(ctx.repo, ctx.issue, ctx.comment_id)
            msg = f"I was trying to {action} but I ran into this:\n```\n{error}\n```"
            self.append_comment(comment, msg)


def handler(event: dict, _ctx: Any = None) -> None:
    Handler(event).do()
