import json
import traceback

from . import get_in
from .github_api import GitHubAPI


class UnknownType(Exception):
    pass


class InvalidPayload(Exception):
    def __init__(self, reason):
        self.reason = reason


class Handler(GitHubAPI):
    _command_prefix = "TagBot "
    _command_ignore = _command_prefix + "ignore"
    _command_tag = _command_prefix + "tag"

    def __init__(self, evt):
        self.messages = [json.loads(r["Sns"]["Message"]) for r in evt["Records"]]
        super().__init__()

    def do(self):
        for msg in self.messages:
            print("id:", msg.get("id"))
            try:
                ctx = self._from_github(msg)
            except (UnknownType, InvalidPayload) as e:
                traceback.print_exc()

    def _from_github(msg):
        type = msg["type"]
        body = msg["body"]
        if type == "pull_request":
            ctx = from_pull_request(body)
        elif type == "issue_comment":
            ctx = from_issue_comment(body)
        else:
            raise InvalidPayload(f"Unknown type {type}")
        ctx.id = msg.get("id")
        ctx.target = self._target(ctx)
        return ctx

    def _from_pull_request(body):
        pass

    def _from_issue_comment(body):
        if body.get("action") != "created":
            raise InvalidPayload("Not a new issue comment")
        if "pull_request" not in body:
            raise InvalidPayload("Comment not on a pull request")
        if get_in(body, "sender", "type") == "Bot":
            raise InvalidPayload("Comment by bot")
        comment = get_in(body, "comment", "body", default="")
        if _command_ignore in comment:
            raise InvalidPayload("Comment contains ignore command")
        if _command_tag in comment:
            pass  # TODO
        raise InvalidPayload("Comment contains no command")

    def _target(self, ctx):
        # Issue #10
        branch = self.get_default_branch(ctx.repo)
        return branch.name if branch.commit.sha == self.commit else self.commit


def handler(evt, _ctx=None):
    Handler(evt).do()
