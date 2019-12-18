from datetime import datetime
from typing import List, Optional, Union

from github import UnknownObjectException
from github.Issue import Issue
from github.PullRequest import PullRequest

from . import debug, info, repo


class Changelog:
    """A Changelog produces release notes for a single release."""

    def __init__(self, repo: "repo.Repo", template: str):
        self.__repo = repo
        self.__template = template
        self.__issues_and_prs: Optional[List[Union[Issue, PullRequest]]] = None

    def _get_version_start(self, version: str) -> datetime:
        rs = []
        found = False
        for r in self.__repo._repo.get_releases():
            if r.tag_name == version:
                found = True
            if found:
                rs.append(r)
        # TODO: Use semver to find the real previous release.
        return rs[1].created_at if len(rs) > 1 else datetime(1, 1, 1)

    def _get_version_end(self, version: str) -> datetime:
        try:
            r = self.__repo._repo.get_release(version)
            return r.created_at
        except UnknownObjectException:
            return datetime.now()

    def _issues_and_prs(self, start: datetime, end: datetime) -> List[Issue]:
        if self.__issues_and_prs is not None:
            return self.__issues_and_prs
        xs = []
        for x in self.__repo._repo.get_issues(state="closed", since=start):
            if x.closed_at < start or x.closed_at > end:
                continue
            if x.pull_request:
                xs.append(x.as_pull_request())
            else:
                xs.append(x)
        xs.reverse()
        self.__issues_and_prs = xs
        return self.__issues_and_prs

    def _issues(self, start: datetime, end: datetime) -> List[Issue]:
        return [i for i in self._issues_and_prs(start, end) if isinstance(i, Issue)]

    def _pulls(self, start: datetime, end: datetime) -> List[PullRequest]:
        return [
            i for i in self._issues_and_prs(start, end) if isinstance(i, PullRequest)
        ]

    def get(self, version: str) -> str:
        """Get the changelog for a specific version."""
        info(f"Generating changelog for version {version}")
        start = self._get_version_start(version)
        debug(f"Start date: {start}")
        end = self._get_version_end(version)
        debug(f"End date: {start}")
        issues = self._issues(start, end)
        prs = self._pulls(start, end)
        return "TODO"
