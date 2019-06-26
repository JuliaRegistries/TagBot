import json

from typing import List, Optional

from .. import Context, stages
from ..mixins import AWS, GitHubAPI


class Handler(AWS, GitHubAPI):
    """Notifies of failure."""

    def __init__(self, event: dict):
        self.bodies: List[dict] = []
        self.stages: List[str] = []
        self.errors: List[str] = []
        for r in event["Records"]:
            self.bodies.append(json.loads(r["Sns"]["Message"]))
            # This assumes that the topics are named <irrelevant>-<stage>-<irrelevant>.
            self.stages.append(r["Sns"]["TopicArn"].split(":")[-1].split("-")[-2])
            self.errors.append(r["MessageAttributes"]["ErrorMessage"]["Value"])

    def do(self) -> None:
        for body, stage, error in zip(self.bodies, self.stages, self.errors):
            action = stages.action(stage)
            if not action:
                continue
            msg = f"I was trying to {action} but I ran into this:\n```\n{error}\n```"
            # This is ugly, but the input to prepare is not a context.
            # Really, this should probably be a separate handler entirely.
            if stage == stages.prepare:
                type = body["type"]
                payload = body["payload"]
                try:
                    registry = payload["repository"]["full_name"]
                    if type == "pull_request":
                        number = payload["pull_request"]["number"]
                    elif type == "issue_comment":
                        number = payload["issue"]["number"]
                    else:
                        print(f"Unknown type {type}")
                        continue
                except KeyError:
                    print("Payload is malformed")
                    continue
                issue = self.get_issue(registry, number)
                self.create_comment(issue, msg)
            else:
                ctx = Context(**body)
                comment = self.get_issue_comment(
                    ctx.registry, ctx.issue, ctx.comment_id
                )
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
