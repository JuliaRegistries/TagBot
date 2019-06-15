import github
import requests

from . import env
from . import resources


class NotInstalled(Exception):
    pass


class NotInstalledForOrg(NotInstalled):
    pass


class NotInstalledForRepo(NotInstalled):
    pass


class GitHubAPI:
    with open(resources.resource("tagbot.pem")) as f:
        _app = github.GithubIntegration(env.github_app_id, f.read().strip())

    def _client(self):
        """Get a GitHub API client, authenticated as the app."""
        return github.Github(jwt=self._app.create_jwt())

    def __headers(self):
        return {
            "Accept": "application/vnd.github.machine-man-preview+json",
            "Authorization": "Bearer " + self._app.create_jwt(),
        }

    def __org_installation_id(self, org):
        url = f"https://api.github.com/orgs/{org}/installation"
        r = requests.get(url, headers=self.__headers())
        if r.status_code == 404:
            raise NotInstalledForOrg()
        return r.json()["id"]

    def __repo_installation_id(self, repo):
        url = f"https://api.github.com/repos/{repo}/installation"
        r = requests.get(url, headers=self.__headers())
        if r.status_code == 404:
            try:
                self._org_installation(repo.split("/")[0])
                raise NotInstalledForRepo()
            except NotInstalledForOrg:
                raise
        return r.json()

    def _installation(self, repo):
        # TODO: Use the github package when these endpoints are supported.
        return github.Github(
            self._app.get_access_token(self.__repo_installation_id(repo)).token
        )

    def get_repo(repo, lazy=False):
        return self._client().get_repo(repo, lazy=lazy)

    def get_pull_request(repo, number, lazy=False):
        return self._client().get_repo(repo, lazy=True).get_pull(number, lazy=lazy)

    def get_default_branch(repo):
        r = self._client().get_repo(repo)
        return r.get_branch(r.default_branch)

    def create_comment(issue_or_pr, body):
        if isinstance(issue_or_pr, github.PullRequest.PullRequest):
            issue_or_pr = issue_or_pr.as_issue()
        return issue_or_pr.create_comment(body)

    def get_issue(repo, number):
        return self._client().get_repo(repo, lazy=True).get_issue(number)

    def get_issue_comment(repo, issue, id):
        return self.get_issue(repo, issue).get_comment(id)

    def create_release(repo, tag, body, ref):
        return (
            self._installation(repo)
            .get_repo(repo, lazy=True)
            .create_git_release(tag, tag, body, target_commitish=ref)
        )
