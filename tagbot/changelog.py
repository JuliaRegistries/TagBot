import json
import re

import semver

from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

from github.Issue import Issue
from github.NamedUser import NamedUser
from github.PullRequest import PullRequest
from github.GitRelease import GitRelease
from jinja2 import Template

from . import DELTA, debug, info, warn

if TYPE_CHECKING:
    from .repo import Repo


class Changelog:
    """A Changelog produces release notes for a single release."""

    _CUSTOM = re.compile(
        "(?s)<!-- BEGIN RELEASE NOTES -->(.*)<!-- END RELEASE NOTES -->"
    )

    def __init__(self, repo: "Repo", template: str):
        self._repo = repo
        self._template = Template(template, trim_blocks=True)
        self._range: Optional[Tuple[datetime, datetime]] = None
        self.__issues_and_pulls: Optional[List[Union[Issue, PullRequest]]] = None

    def _previous_release(self, version: str) -> Optional[GitRelease]:
        """Get the release before the current one."""
        cur_ver = semver.parse_version_info(version[1:])
        prev_ver = semver.parse_version_info("0.0.0")
        prev_rel = None
        for r in self._repo._repo.get_releases():
            if not r.tag_name.startswith("v"):
                continue
            try:
                ver = semver.parse_version_info(r.tag_name[1:])
            except ValueError:
                continue
            if ver.prerelease or ver.build:
                continue
            if ver < cur_ver and ver > prev_ver:
                prev_ver = ver
                prev_rel = r
        return prev_rel

    def _version_end(self, sha: str) -> datetime:
        """Get the end of the interval for collecting issues and pull requests."""
        ts = self._repo._git("show", "-s", "--format=%cI", sha)
        dt = datetime.fromisoformat(ts)
        # Convert to UTC and then remove TZ info altogether.
        offset = dt.utcoffset()
        if offset:
            dt -= offset
        return dt.replace(tzinfo=None)

    def _issues_and_pulls(self, start: datetime, end: datetime) -> List[Issue]:
        """Collect issues and pull requests that were closed in the interval."""
        if self.__issues_and_pulls is not None and self._range == (start, end):
            return self.__issues_and_pulls
        xs = []
        for x in self._repo._repo.get_issues(state="closed", since=start):
            if x.closed_at < start or x.closed_at > end:
                continue
            if x.pull_request:
                pr = x.as_pull_request()
                if pr.merged:
                    xs.append(pr)
            else:
                xs.append(x)
        xs.reverse()
        self._range = (start, end)
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

    def _registry_pr(self, version: str) -> Optional[PullRequest]:
        """Look up a merged registry pull request for this version."""
        name = self._repo._project("name")
        uuid = self._repo._project("uuid")
        head = f"registrator/{name.lower()}/{uuid[:8]}/{version}"
        debug(f"Looking for PR from branch {head}")
        now = datetime.now()
        # Check for an owner's PR first, since this is way faster.
        registry = self._repo._registry
        owner = registry.owner.login
        debug(f"Trying to find PR by registry owner first ({owner})")
        prs = registry.get_pulls(head=f"{owner}:{head}", state="closed")
        print("owner:", prs)
        for pr in prs:
            if pr.merged and now - pr.merged_at < DELTA:
                return pr
        else:
            debug("Did not find registry PR by registry owner")
            prs = registry.get_pulls(state="closed")
            print(prs)
            for pr in prs:
                if now - pr.closed_at > DELTA:
                    break
                if pr.merged and pr.head.ref == head:
                    return pr
        return None

    def _custom_release_notes(self, version: str) -> Optional[str]:
        """Look up a version's custom release notes."""
        debug("Looking up custom release notes")
        pr = self._registry_pr(version)
        if pr is None:
            warn("No registry pull request was found for this version")
            return None
        m = self._CUSTOM.search(pr.body)
        if m:
            # Remove the '> ' at the beginning of each line.
            return "\n".join(l[2:] for l in m[1].splitlines()).strip()
        debug("No custom release notes were found")
        return None

    def _format_user(self, user: NamedUser) -> Dict[str, Any]:
        """Format a user for the template."""
        return {
            "name": user.name,
            "url": user.html_url,
            "username": user.login,
        }

    def _format_issue(self, issue: Issue) -> Dict[str, Any]:
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

    def _format_pull(self, pull: PullRequest) -> Dict[str, Any]:
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

    def _collect_data(self, version: str, sha: str) -> Dict[str, Any]:
        """Collect data needed to create the changelog."""
        previous = self._previous_release(version)
        debug(f"Previous version: {previous.tag_name if previous else None}")
        start = previous.created_at if previous else datetime(1, 1, 1)
        debug(f"Start date: {start}")
        end = self._version_end(sha)
        debug(f"End date: {end}")
        issues = self._issues(start, end)
        pulls = self._pulls(start, end)
        compare = None
        old = None
        if previous:
            old = previous.tag_name
            compare = f"{self._repo._repo.html_url}/compare/{old}...{version}"
        return {
            "compare_url": compare,
            "custom": self._custom_release_notes(version),
            "issues": [self._format_issue(i) for i in issues],
            "package": self._repo._project("name"),
            "previous_release": old,
            "pulls": [self._format_pull(p) for p in pulls],
            "sha": sha,
            "version": version,
            "version_url": f"{self._repo._repo.html_url}/tree/{version}",
        }

    def _render(self, data: Dict[str, Any]) -> str:
        """Render the template."""
        return self._template.render(data).strip()

    def get(self, version: str, sha: str) -> str:
        """Get the changelog for a specific version."""
        info(f"Generating changelog for version {version} ({sha})")
        data = self._collect_data(version, sha)
        debug(f"Changelog data: {json.dumps(data, indent=2)}")
        return self._render(data)
