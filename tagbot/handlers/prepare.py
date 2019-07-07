import json
import re
import traceback

from typing import Any

from github import UnknownObjectException

from .. import Context, env, stages
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
    _registrator_username = env.registrator_username
    _re_repo = re.compile("Repository:.*github.com/(.*/.*)")
    _re_version = re.compile("Version:\\s*(v.*)")
    _re_commit = re.compile("Commit:\\s*(.*)")
    _re_changelog = re.compile(
        "(?s)<!-- BEGIN RELEASE NOTES -->(.*)<!-- END RELEASE NOTES -->"
    )
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
        issue = self.get_issue(ctx.registry, ctx.issue)
        comment = self.create_comment(issue, msg)
        ctx.comment_id = comment.id
        self.invoke(self._next_stage, ctx)  # type: ignore

    def _from_github(self) -> Context:
        """Build a Context from a GitHub event."""
        type = self.body["type"]
        payload = self.body["payload"]
        if type == "pull_request":
            f = self._from_pull_request
        elif type == "issue_comment":
            f = self._from_issue_comment
        else:
            raise InvalidPayload(f"Unknown type {type}")
        try:
            ctx = f(payload)
        except KeyError as e:
            raise InvalidPayload(f"KeyError: {e}")
        try:
            self.auth_token(ctx.repo)
        except NotInstalledForRepo:
            msg = f"""
            The GitHub App is installed for the repository owner's account, but the repository itself is not enabled.
            Go [here](https://github.com/apps/{self._github_app_name}/installations/new) to update your settings.
            Once that's done, you might want to retry by making a reply to this comment containing `{self._command_tag}`.
            """
            self.invoke_notify(ctx, msg)
            raise StopPipeline("Not installed for repository")
        try:
            tag = self.get_tag(ctx.repo, ctx.version)
        except UnknownObjectException:
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
                raise StopPipeline("Invalid existing tag")
        ctx.id = self.body["id"]
        ctx.target = self._target(ctx)
        return ctx

    def _from_pull_request(self, payload: dict) -> Context:
        """Build a Context from a pull request event."""
        if payload["action"] != "closed":
            raise InvalidPayload("Not a merged PR")
        pr = payload["pull_request"]
        if not pr["merged"]:
            raise InvalidPayload("Not a merged PR")
        if pr["user"]["login"] != self._registrator_username:
            raise InvalidPayload("PR not created by Registrator")
        if pr["base"]["ref"] != pr["base"]["repo"]["default_branch"]:
            raise InvalidPayload("Base branch is not the default branch")
        body = pr["body"]
        m = self._re_repo.search(body)
        if not m:
            raise InvalidPayload("No repo match")
        repo = m[1].strip()
        m = self._re_version.search(body)
        if not m:
            raise InvalidPayload("No version match")
        version = m[1].strip()
        m = self._re_commit.search(body)
        if not m:
            raise InvalidPayload("No commit match")
        commit = m[1].strip()
        changelog = None
        m = self._re_changelog.search(body)
        if m:
            changelog = m[1].strip()
        registry = payload["repository"]["full_name"]
        issue = pr["number"]
        return Context(
            repo=repo,
            version=version,
            commit=commit,
            changelog=changelog,
            issue=issue,
            registry=registry,
        )

    def _from_issue_comment(self, payload: dict) -> Context:
        """Build a Context from an issue comment event."""
        if payload["action"] != "created":
            raise InvalidPayload("Not a new issue comment")
        issue = payload["issue"]
        if "pull_request" not in issue:
            raise InvalidPayload("Comment not on a pull request")
        body = payload["comment"]["body"].casefold()
        if self._command_ignore.casefold() in body:
            raise InvalidPayload("Comment contains ignore command")
        if self._command_tag.casefold() in body:
            pr = self.get_pull_request(
                payload["repository"]["full_name"], issue["number"]
            )
            return self._from_pull_request(
                {
                    "action": "closed",
                    "pull_request": {
                        "merged": pr.merged,
                        "number": pr.number,
                        "body": pr.body,
                        "user": {"login": pr.user.login},
                        "base": {
                            "ref": pr.base.ref,
                            "repo": {"default_branch": pr.base.repo.default_branch},
                        },
                    },
                }
            )
        raise InvalidPayload("Comment contains no command")

    def _target(self, ctx: Context) -> str:
        """Get the release target (see issue #10)."""
        branch = self.get_default_branch(ctx.repo)
        return branch.name if branch.commit.sha == ctx.commit else ctx.commit


def handler(evt: dict, _ctx=None) -> None:
    Handler(evt).do()
