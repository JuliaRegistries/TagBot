from typing import Dict, Optional, Union

import github
import requests

from github.Branch import Branch
from github.GitRelease import GitRelease
from github.Issue import Issue
from github.IssueComment import IssueComment
from github.PullRequest import PullRequest
from github.Repository import Repository

from .. import env
from .. import resources
from ..exceptions import NotInstalledForOrg, NotInstalledForRepo


class GitHubAPI:
    """Provides access to the GitHub API."""

    with open(resources.resource("tagbot.pem")) as f:
        _app = github.GithubIntegration(env.github_app_id, f.read().strip())

    def _client(self) -> github.Github:
        """Get a GitHub API client, authenticated as the app."""
        return github.Github(jwt=self._app.create_jwt())

    def __headers(self) -> Dict[str, str]:
        """Get headers required to make manual requests to the GitHub API."""
        return {
            "Accept": "application/vnd.github.machine-man-preview+json",
            "Authorization": "Bearer " + self._app.create_jwt(),
        }

    def __org_installation_id(self, org: str) -> int:
        """Get the ID of an installation by organization."""
        url = f"https://api.github.com/orgs/{org}/installation"
        r = requests.get(url, headers=self.__headers())
        if r.status_code == 404:
            raise NotInstalledForOrg()
        return r.json()["id"]

    def __repo_installation_id(self, repo: str) -> int:
        """Get the ID of an installation by repository."""
        url = f"https://api.github.com/repos/{repo}/installation"
        r = requests.get(url, headers=self.__headers())
        if r.status_code == 404:
            try:
                self.__org_installation_id(repo.split("/")[0])
                raise NotInstalledForRepo()
            except NotInstalledForOrg:
                raise
        return r.json()["id"]

    def _installation(self, repo: str) -> github.Github:
        """Get a GitHub client with an installation's permissions."""
        # TODO: Use the github package when these endpoints are supported.
        return github.Github(
            self._app.get_access_token(self.__repo_installation_id(repo)).token
        )

    def get_repo(self, repo: str, lazy: bool = False) -> Repository:
        """Get a repository."""
        return self._client().get_repo(repo, lazy=lazy)

    def get_pull_request(
        self, repo: str, number: int, lazy: bool = False
    ) -> PullRequest:
        """Get a pull request."""
        return self._client().get_repo(repo, lazy=True).get_pull(number, lazy=lazy)

    def get_issue(self, repo: str, number: int) -> Issue:
        """Get an issue."""
        return self._client().get_repo(repo, lazy=True).get_issue(number)

    def get_issue_comment(self, repo: str, issue: int, id: int) -> IssueComment:
        """Get an issue comment."""
        return self.get_issue(repo, issue).get_comment(id)

    def get_default_branch(self, repo: str) -> Branch:
        """Get a repository's default branch."""
        r = self._client().get_repo(repo)
        return r.get_branch(r.default_branch)

    def create_comment(
        self, issue_or_pr: Union[Issue, PullRequest], body: str
    ) -> IssueComment:
        """Comment on an issue or pull request."""
        if isinstance(issue_or_pr, PullRequest):
            issue_or_pr = issue_or_pr.as_issue()
        return issue_or_pr.create_comment(body)

    def append_comment(
        self, comment: IssueComment, body: str
    ) -> Optional[IssueComment]:
        """Add a message to an existing comment."""
        if body in comment.body:
            print("Body is already in the comment")
            return None
        return comment.edit(body=comment.body + "\n---\n" + body)

    def create_release(
        self, repo: str, tag: str, ref: str, body: Optional[str]
    ) -> GitRelease:
        """Create a GitHub release."""
        return (
            self._installation(repo).get_repo(repo, lazy=True)
            # TODO: Is None body okay?
            .create_git_release(tag, tag, body, target_commitish=ref)
        )
