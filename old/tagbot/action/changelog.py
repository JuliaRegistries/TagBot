import json
import re

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple, Union

from github.GitRelease import GitRelease
from github.Issue import Issue
from github.NamedUser import NamedUser
from github.PullRequest import PullRequest
from jinja2 import Template
from semver import VersionInfo

from .. import logger

if TYPE_CHECKING:
    from .repo import Repo


class Changelog:
    """A Changelog produces release notes for a single release."""

    DEFAULT_IGNORE = [
        "changelog skip",
        "duplicate",
        "exclude from changelog",
        "invalid",
        "no changelog",
        "question",
        "wont fix",
    ]

    def __init__(self, repo: "Repo", template: str, ignore: List[str]) -> None:
        self._repo = repo
        self._template = Template(template, trim_blocks=True)
        self._ignore = set(self._slug(s) for s in ignore)
        self.__range: Optional[Tuple[datetime, datetime]] = None
        self.__issues_and_pulls: Optional[List[Union[Issue, PullRequest]]] = None

    def _slug(self, s: str) -> str:
        """Return a version of the string that's easy to compare."""
        return re.sub(r"[\s_-]", "", s.casefold())

    def _previous_release(self, version: str) -> Optional[GitRelease]:
        """Get the release previous to the current one (according to SemVer)."""
        cur_ver = VersionInfo.parse(version[1:])
        prev_ver = VersionInfo(0)
        prev_rel = None
        for r in self._repo._repo.get_releases():
            if not r.tag_name.startswith("v"):
                continue
            try:
                ver = VersionInfo.parse(r.tag_name[1:])
            except ValueError:
                continue
            if ver.prerelease or ver.build:
                continue
            # Get the highest version that is not greater than the current one.
            # That means if we're creating a backport v1.1, an already existing v2.0,
            # despite being newer than v1.0, will not be selected.
            if ver < cur_ver and ver > prev_ver:
                prev_rel = r
                prev_ver = ver
        return prev_rel

    def _issues_and_pulls(
        self, start: datetime, end: datetime
    ) -> List[Union[Issue, PullRequest]]:
        """Collect issues and pull requests that were closed in the interval."""
        # Even if we've previously cached some data,
        # only return it if the interval is the same.
        if self.__issues_and_pulls is not None and self.__range == (start, end):
            return self.__issues_and_pulls
        xs: List[Union[Issue, PullRequest]] = []
        # Get all closed issues and merged PRs that were closed/merged in the interval.
        for x in self._repo._repo.get_issues(state="closed", since=start):
            # If a previous release's last commit closed an issue, then that issue
            # should be included in the previous release's changelog and not this one.
            # The interval includes the endpoint for this same reason.
            if x.closed_at <= start or x.closed_at > end:
                continue
            if self._ignore.intersection(self._slug(label.name) for label in x.labels):
                continue
            if x.pull_request:
                pr = x.as_pull_request()
                if pr.merged:
                    xs.append(pr)
            else:
                xs.append(x)
        xs.reverse()  # Sort in chronological order.
        self.__range = (start, end)
        self.__issues_and_pulls = xs
        return self.__issues_and_pulls

    def _issues(self, start: datetime, end: datetime) -> List[Issue]:
        """Collect just issues in the interval."""
        return [i for i in self._issues_and_pulls(start, end) if isinstance(i, Issue)]

    def _pulls(self, start: datetime, end: datetime) -> List[PullRequest]:
        """Collect just pull requests in the interval."""
        return [
            p for p in self._issues_and_pulls(start, end) if isinstance(p, PullRequest)
        ]

    def _custom_release_notes(self, version: str) -> Optional[str]:
        """Look up a version's custom release notes."""
        logger.debug("Looking up custom release notes")
        pr = self._repo._registry_pr(version)
        if not pr:
            logger.warning("No registry pull request was found for this version")
            return None
        m = re.search(
            "(?s)<!-- BEGIN RELEASE NOTES -->(.*)<!-- END RELEASE NOTES -->", pr.body
        )
        if m:
            # Remove the '> ' at the beginning of each line.
            return "\n".join(line[2:] for line in m[1].splitlines()).strip()
        logger.debug("No custom release notes were found")
        return None

    def _format_user(self, user: Optional[NamedUser]) -> Dict[str, object]:
        """Format a user for the template."""
        if user:
            return {
                "name": user.name or user.login,
                "url": user.html_url,
                "username": user.login,
            }
        return {}

    def _format_issue(self, issue: Issue) -> Dict[str, object]:
        """Format an issue for the template."""
        return {
            "author": self._format_user(issue.user),
            "body": issue.body,
            "closer": self._format_user(issue.closed_by),
            "labels": [label.name for label in issue.labels],
            "number": issue.number,
            "title": issue.title,
            "url": issue.html_url,
        }

    def _format_pull(self, pull: PullRequest) -> Dict[str, object]:
        """Format a pull request for the template."""
        return {
            "author": self._format_user(pull.user),
            "body": pull.body,
            "labels": [label.name for label in pull.labels],
            "merger": self._format_user(pull.merged_by),
            "number": pull.number,
            "title": pull.title,
            "url": pull.html_url,
        }

    def _collect_data(self, version: str, sha: str) -> Dict[str, object]:
        """Collect data needed to create the changelog."""
        previous = self._previous_release(version)
        start = datetime.fromtimestamp(0)
        prev_tag = None
        compare = None
        if previous:
            start = previous.created_at
            prev_tag = previous.tag_name
            compare = f"{self._repo._repo.html_url}/compare/{prev_tag}...{version}"
        # When the last commit is a PR merge, the commit happens a second or two before
        # the PR and associated issues are closed.
        end = self._repo._git.time_of_commit(sha) + timedelta(minutes=1)
        logger.debug(f"Previous version: {prev_tag}")
        logger.debug(f"Start date: {start}")
        logger.debug(f"End date: {end}")
        issues = self._issues(start, end)
        pulls = self._pulls(start, end)
        return {
            "compare_url": compare,
            "custom": self._custom_release_notes(version),
            "issues": [self._format_issue(i) for i in issues],
            "package": self._repo._project("name"),
            "previous_release": prev_tag,
            "pulls": [self._format_pull(p) for p in pulls],
            "sha": sha,
            "version": version,
            "version_url": f"{self._repo._repo.html_url}/tree/{version}",
        }

    def _render(self, data: Dict[str, object]) -> str:
        """Render the template."""
        return self._template.render(data).strip()

    def get(self, version: str, sha: str) -> str:
        """Get the changelog for a specific version."""
        logger.info(f"Generating changelog for version {version} ({sha})")
        data = self._collect_data(version, sha)
        logger.debug(f"Changelog data: {json.dumps(data, indent=2)}")
        return self._render(data)
