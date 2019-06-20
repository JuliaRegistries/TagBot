import json

from typing import List, Optional

from .. import stages
from ..context import Context
from ..mixins import AWS, GitHubAPI


class Handler(AWS, GitHubAPI):
    def __init__(self, event: dict):
        self.ctxs: List[Context] = []
        self.stages: List[str] = []
        self.errors: List[str] = []
        for r in event["Records"]:
            self.ctxs.append(Context(**json.loads(r["Sns"]["Message"])))
            # This assumes that the topics are named dead-<stage>.
            self.stages.append(r["Sns"]["TopicArn"].split(":")[-1].split("-")[-1])
            self.errors.append(r["MessageAttributes"]["ErrorMessage"]["Value"])

    def do(self) -> None:
        for ctx, stage, error in zip(self.ctxs, self.stages, self.errors):
            action = stages.action(stage)
            if not action:
                continue
            msg = f"I was trying to {action} but I ran into this:\n```\n{error}\n```"
            if ctx.comment_id is None:
                issue = self.get_issue(ctx.repo, ctx.issue)
                self.create_comment(issue, msg)
            else:
                comment = self.get_issue_comment(ctx.repo, ctx.issue, ctx.comment_id)
                self.append_comment(comment, msg)
            next_stage = stages.next(stage)
            if next_stage:
                # We're pushing the context through unchanged here,
                # which is fine for all the situations that I can think of.
                # - tag: nothing is changed on success anyways
                # - changelog: null changelog is equivalent to empty changelog
                self.invoke(next_stage, ctx)


def handler(event: dict, _ctx=None) -> None:
    Handler(event).do()
