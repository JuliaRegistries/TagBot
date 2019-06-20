import json

from typing import Any, List

from ..enums import stages
from ..context import Context
from ..mixins.aws import AWS
from ..mixins.github_api import GitHubAPI


class Handler(AWS, GitHubAPI):
    """Notifies of failure."""

    def __init__(self, event: dict):
        self.ctxs: List[Context] = []
        self.stages: List[str] = []
        self.errors: List[str] = []
        for r in event["Records"]:
            self.ctxs.append(Context(**json.loads(r["Sns"]["Message"])))
            self.stages.append(
                self.get_item(r["MessageAttributes"]["RequestId"]["Value"])
                or stages.unknown
            )
            self.errors.append(r["MessageAttributes"]["ErrorMessage"]["Value"])

    def do(self) -> None:
        for ctx, stage, error in zip(self.ctxs, self.stages, self.errors):
            if ctx.comment_id is None:
                print("Context has no comment ID")
                continue
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
