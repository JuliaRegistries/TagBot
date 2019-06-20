import json
import traceback

from typing import Any

from .. import stages
from ..context import Context
from ..exceptions import InvalidPayload, UnknownType
from ..mixins import AWS, GitHubAPI


class Handler(AWS, GitHubAPI):
    """Builds a Context from a GitHub event."""

    _command_prefix = "TagBot "
    _command_ignore = _command_prefix + "ignore"
    _command_tag = _command_prefix + "tag"
    _this_stage = stages.prepare
    _next_stage = stages.tag

    def __init__(self, body: dict):
        self.body = body

    def do(self) -> None:
        try:
            ctx = self._from_github()
        except (UnknownType, InvalidPayload):
            traceback.print_exc()
        self.invoke(self._next_stage, ctx)

    def _from_github(self) -> Context:
        """Build a Context from a GitHub event."""
        type = self.body["type"]
        payload = self.body["payload"]
        if type == "pull_request":
            ctx = self._from_pull_request(payload)
        elif type == "issue_comment":
            ctx = self._from_issue_comment(payload)
        else:
            raise InvalidPayload(f"Unknown type {type}")
        ctx.id = payload.get("id")
        ctx.target = self._target(ctx)
        return ctx

    def _from_pull_request(self, payload: dict) -> Context:
        """Build a Context from a pull request event."""
        pass

    def _from_issue_comment(self, payload: dict) -> Context:
        """Build a Context from an issue comment event."""
        if payload.get("action") != "created":
            raise InvalidPayload("Not a new issue comment")
        if "pull_request" not in payload:
            raise InvalidPayload("Comment not on a pull request")
        if get_in(payload, "sender", "type") == "Bot":
            raise InvalidPayload("Comment by bot")
        comment = get_in(payload, "comment", "body", default="")
        if self._command_ignore in comment:
            raise InvalidPayload("Comment contains ignore command")
        if self._command_tag in comment:
            pass  # TODO
        raise InvalidPayload("Comment contains no command")

    def _target(self, ctx: Context) -> str:
        """Get the release target (see issue #10)."""
        branch = self.get_default_branch(ctx.repo)
        return branch.name if branch.commit.sha == ctx.commit else ctx.commit


def get_in(d: dict, *keys: str, default: Any = None) -> Any:
    """Safely retrieve a nested value from a dict."""
    for k in keys:
        if k not in d:
            return None
        d = d[k]
    return d


def handler(evt: dict, _ctx=None) -> None:
    Handler(evt).do()
