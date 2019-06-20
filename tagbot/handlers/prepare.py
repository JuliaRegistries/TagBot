import json
import traceback

from typing import Any

from github import ObjectNotFoundException

from .. import env, stages
from ..context import Context
from ..exceptions import (
    InvalidPayload,
    NotInstalled,
    NotInstalledForRepo,
    StopPipeline,
    UnknownType,
)
from ..mixins import AWS, GitHubAPI


class Handler(AWS, GitHubAPI):
    """Builds a Context from a GitHub event."""

    _command_prefix = "TagBot "
    _command_ignore = _command_prefix + "ignore"
    _command_tag = _command_prefix + "tag"
    _github_app_name = env.github_app_name
    _this_stage = stages.prepare
    _next_stage = stages.next(_this_stage)

    def __init__(self, body: dict):
        self.body = body

    def do(self) -> None:
        try:
            ctx = self._from_github()
        except (NotInstalled, StopPipeline):
            traceback.print_exc()
            return
        msg = f"""
        I'm creating release `{ctx.version}` for `{ctx.repo}` at commit `{ctx.commit}`, I'll keep this comment updated with my progress.
        If something goes wrong and you want me to try again, make a reply to this comment containing `{self._command_tag}`.
        <!--
        {self._command_ignore}
        ID: {ctx.id}
        -->
        """
        self.invoke_notify(ctx, msg)
        self.invoke(self._next_stage, ctx)  # type: ignore

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
        try:
            ctx.auth = self.auth_token(ctx.repo)
        except NotInstalledForRepo:
            msg = f"""
            The GitHub App is installed for the repository owner's account, but the repository itself is not enabled.
            Go [here](https://github.com/apps/{self._github_app_name}/installations/new) to update your settings.
            Once that's done, you might want to retry by making a reply to this comment containing `{self._command_tag}`.
            """
            self.invoke_notify(ctx, msg)
            raise StopPipeline()
        try:
            tag = self.get_tag(ctx.repo, ctx.version)
        except ObjectNotFoundException:
            pass
        else:
            if tag.sha != ctx.commit:
                msg = f"""
                A tag `{ctx.version}` already exists, but it points at the wrong commit.
                Expected: `{ctx.commit}`
                Observed: `{tag.sha}`
                You might want to delete the existing tag and retry by making a reply to this comment containing `{self._command_tag}`.
                """
                self.invoke_notify(ctx, msg)
                raise StopPipeline()
        ctx.id = payload.get("id")
        ctx.target = self._target(ctx)
        return ctx

    def _from_pull_request(self, payload: dict) -> Context:
        """Build a Context from a pull request event."""
        # TODO
        pass

    def _from_issue_comment(self, payload: dict) -> Context:
        """Build a Context from an issue comment event."""
        if payload.get("action") != "created":
            raise InvalidPayload("Not a new issue comment")
        if "pull_request" not in payload:
            raise InvalidPayload("Comment not on a pull request")
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
