import os.path
import textwrap

from functools import lru_cache
from typing import Dict, Optional, Union

import github
import requests

from github import UnknownObjectException
from github.Branch import Branch
from github.GitRelease import GitRelease
from github.Issue import Issue
from github.IssueComment import IssueComment
from github.PullRequest import PullRequest
from github.Repository import Repository

from .. import env, resources
from ..exceptions import NotInstalledForOwner, NotInstalledForRepo


class GitHubAPI:
    """Provides access to the GitHub API."""

    __pem = resources.resource("tagbot.pem")
    if os.path.isfile(__pem):
        with open(__pem) as f:
            __pem = f.read().strip()
    else:
        print("Private key is not available")
        __pem = ""
    _app = github.GithubIntegration(env.github_app_id, __pem)

    def _client(self) -> github.Github:
        """Get a GitHub API client, authenticated as the app."""
        return github.Github(jwt=self._app.create_jwt())

    def __headers(self) -> Dict[str, str]:
        """Get headers required to make manual requests to the GitHub API."""
        return {
            "Accept": "application/vnd.github.machine-man-preview+json",
            "Authorization": "Bearer " + self._app.create_jwt(),
        }

    @lru_cache()
    def __installation_id(self, path: str, key: str) -> Optional[int]:
        """Get the ID of an installation."""
        url = f"https://api.github.com/{path}/{key}/installation"
        r = requests.get(url, headers=self.__headers())
        if r.status_code == 200:
            return r.json().get("id")
        if r.status_code != 404:
            r.raise_for_status()
        return None

    def _installation(self, repo: str) -> github.Github:
        """Get a GitHub client with an installation's permissions."""
        return github.Github(self.auth_token(repo))

    def get_repo(self, repo: str, lazy: bool = False) -> Repository:
        """Get a repository."""
        return self._installation(repo).get_repo(repo, lazy=lazy)

    def get_pull_request(self, repo: str, number: int) -> PullRequest:
        """Get a pull request."""
        return self.get_repo(repo, lazy=True).get_pull(number)

    def get_issue(self, repo: str, number: int) -> Issue:
        """Get an issue."""
        return self.get_repo(repo, lazy=True).get_issue(number)

    def get_issue_comment(self, repo: str, issue: int, id: int) -> IssueComment:
        """Get an issue comment."""
        return self.get_issue(repo, issue).get_comment(id)

    def get_default_branch(self, repo: str) -> Branch:
        """Get a repository's default branch."""
        r = self.get_repo(repo)
        return r.get_branch(r.default_branch)

    def get_tag_commit_sha(self, repo: str, tag: str) -> str:
        """Get a Git tag.."""
        r = self.get_repo(repo, lazy=True)
        ref = r.get_git_ref(f"tags/{tag}")
        if ref.object.type == "commit":
            return ref.object.sha
        return r.get_git_tag(ref.object.sha).object.sha

    def tag_exists(self, repo: str, tag: str) -> bool:
        """Determine whether or not a tag exists."""
        try:
            self.get_tag_commit_sha(repo, tag)
        except UnknownObjectException:
            return False
        else:
            return True

    def create_comment(
        self, issue_or_pr: Union[Issue, PullRequest], body: str
    ) -> IssueComment:
        """Comment on an issue or pull request."""
        if isinstance(issue_or_pr, PullRequest):
            issue_or_pr = issue_or_pr.as_issue()
        return issue_or_pr.create_comment(textwrap.dedent(body).strip())

    def append_comment(self, comment: IssueComment, body: str) -> IssueComment:
        """Add a message to an existing comment."""
        if body in comment.body:
            print("Body is already in the comment")
            return comment
        return comment.edit(
            body=comment.body + "\n\n---\n\n" + textwrap.dedent(body).strip()
        )

    @lru_cache()  # TODO: This might cause tokens to expire, TTL would work better.
    def auth_token(self, repo: str) -> str:
        """Get an OAuth2 token for a repository."""
        id = self.__installation_id("repos", repo)
        if id is not None:
            return self._app.get_access_token(id).token
        owner = repo.split("/")[0]
        if self.__installation_id("users", owner) is not None:
            raise NotInstalledForRepo()
        if self.__installation_id("orgs", owner) is not None:
            raise NotInstalledForRepo()
        raise NotInstalledForOwner()

    def create_release(
        self, repo: str, tag: str, ref: str, body: Optional[str]
    ) -> GitRelease:
        """Create a GitHub release."""
        return self.get_repo(repo, lazy=True).create_git_release(
            tag, tag, body or "", target_commitish=ref
        )
