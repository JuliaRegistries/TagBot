import json
import re

from datetime import datetime, timedelta, timezone
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
        "skip changelog",
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

    def _previous_release(self, version_tag: str) -> Optional[GitRelease]:
        """Get the release previous to the current one (according to SemVer)."""
        tag_prefix = self._repo._tag_prefix()
        i_start = len(tag_prefix)
        cur_ver = VersionInfo.parse(version_tag[i_start:])
        prev_ver = VersionInfo(0)
        prev_rel = None
        tag_prefix = self._repo._tag_prefix()
        for r in self._repo._repo.get_releases():
            if not r.tag_name.startswith(tag_prefix):
                continue
            try:
                ver = VersionInfo.parse(r.tag_name[i_start:])
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

    def _is_backport(self, version: str, tags: Optional[List[str]] = None) -> bool:
        """Determine whether or not the version is a backport."""
        try:
            version_pattern = re.compile(
                r"^(.*?)[-v]?(\d+\.\d+\.\d+(?:\.\d+)*)(?:[-+].+)?$"
            )

            if tags is None:
                # Populate the tags list with tag names from the releases
                tags = [r.tag_name for r in self._repo._repo.get_releases()]

            # Extract any package name prefix and version number from the input
            match = version_pattern.match(version)
            if not match:
                raise ValueError(f"Invalid version format: {version}")
            package_name = match.group(1)
            cur_ver = VersionInfo.parse(match.group(2))

            for tag in tags:
                tag_match = version_pattern.match(tag)
                if not tag_match:
                    continue

                tag_package_name = tag_match.group(1)

                if tag_package_name != package_name:
                    continue

                try:
                    tag_ver = VersionInfo.parse(tag_match.group(2))
                except ValueError:
                    continue

                # Disregard prerelease and build versions
                if tag_ver.prerelease or tag_ver.build:
                    continue

                # Check if the version is a backport
                if tag_ver > cur_ver:
                    return True

            return False
        except Exception as e:
            # This is a best-effort function so we don't fail the entire process
            logger.error(f"Checking if backport failed. Assuming False: {e}")
            return False

    def _issues_and_pulls(
        self, start: datetime, end: datetime
    ) -> List[Union[Issue, PullRequest]]:
        """Collect issues and pull requests that were closed in the interval."""
        # Even if we've previously cached some data,
        # only return it if the interval is the same.
        if self.__issues_and_pulls is not None and self.__range == (start, end):
            return self.__issues_and_pulls
        xs: List[Union[Issue, PullRequest]] = []

        # Use search API to filter by date range on the server side.
        # This is much more efficient than fetching all closed issues and filtering.
        repo_name = self._repo._repo.full_name
        # Format dates for GitHub search (ISO 8601 without timezone)
        start_str = start.strftime("%Y-%m-%dT%H:%M:%S")
        end_str = end.strftime("%Y-%m-%dT%H:%M:%S")
        query = f"repo:{repo_name} is:closed closed:{start_str}..{end_str}"
        logger.debug(f"Searching issues/PRs with query: {query}")

        try:
            # Use the GitHub instance from the repo to search
            gh = self._repo._gh
            for x in gh.search_issues(query, sort="created", order="asc"):
                # Search returns issues, need to filter by closed_at within range
                # (search date range is approximate, so we still need to verify)
                if x.closed_at is None or x.closed_at <= start or x.closed_at > end:
                    continue
                if self._ignore.intersection(
                    self._slug(label.name) for label in x.labels
                ):
                    continue
                if x.pull_request:
                    pr = x.as_pull_request()
                    if pr.merged:
                        xs.append(pr)
                else:
                    xs.append(x)
        except Exception as e:
            # Fall back to the old method if search fails
            logger.warning(f"Search API failed, falling back to issues API: {e}")
            return self._issues_and_pulls_fallback(start, end)

        self.__range = (start, end)
        self.__issues_and_pulls = xs
        return self.__issues_and_pulls

    def _issues_and_pulls_fallback(
        self, start: datetime, end: datetime
    ) -> List[Union[Issue, PullRequest]]:
        """Fallback method using the issues API (slower but more reliable)."""
        xs: List[Union[Issue, PullRequest]] = []
        for x in self._repo._repo.get_issues(state="closed", since=start):
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

    def _custom_release_notes(self, version_tag: str) -> Optional[str]:
        """Look up a version's custom release notes."""
        logger.debug("Looking up custom release notes")
        tag_prefix = self._repo._tag_prefix()
        i_start = len(tag_prefix) - 1
        package_version = version_tag[i_start:]
        pr = self._repo._registry_pr(package_version)
        if not pr:
            logger.warning("No registry pull request was found for this version")
            return None
        m = re.search(
            "(?s)<!-- BEGIN RELEASE NOTES -->\n`````"
            + "(.*)`````\n<!-- END RELEASE NOTES -->",
            pr.body,
        )
        if m:
            return m[1].strip()
        # check for the old way, if it's an older PR
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
            # Fetching `user.name` for the Copilot bot fails, so it needs to be
            # special-cased.
            name = (
                "Copilot"
                if (user.login == "Copilot" and user.type == "Bot")
                else (user.name or user.login)
            )
            return {
                "name": name,
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

    def _collect_data(self, version_tag: str, sha: str) -> Dict[str, object]:
        """Collect data needed to create the changelog."""
        previous = self._previous_release(version_tag)
        start = datetime.fromtimestamp(0, timezone.utc)
        prev_tag = None
        compare = None
        if previous:
            start = previous.created_at
            prev_tag = previous.tag_name
            compare = f"{self._repo._repo.html_url}/compare/{prev_tag}...{version_tag}"
        # When the last commit is a PR merge, the commit happens a second or two before
        # the PR and associated issues are closed.
        commit = self._repo._repo.get_commit(sha)
        end = commit.commit.author.date + timedelta(minutes=1)
        logger.debug(f"Previous version: {prev_tag}")
        logger.debug(f"Start date: {start}")
        logger.debug(f"End date: {end}")
        issues = self._issues(start, end)
        pulls = self._pulls(start, end)
        return {
            "compare_url": compare,
            "custom": self._custom_release_notes(version_tag),
            "backport": self._is_backport(version_tag),
            "issues": [self._format_issue(i) for i in issues],
            "package": self._repo._project("name"),
            "previous_release": prev_tag,
            "pulls": [self._format_pull(p) for p in pulls],
            "sha": sha,
            "version": version_tag,
            "version_url": f"{self._repo._repo.html_url}/tree/{version_tag}",
        }

    def _render(self, data: Dict[str, object]) -> str:
        """Render the template."""
        return self._template.render(data).strip()

    def get(self, version_tag: str, sha: str) -> str:
        """Get the changelog for a specific version."""
        logger.info(f"Generating changelog for version {version_tag} ({sha})")
        data = self._collect_data(version_tag, sha)
        logger.debug(f"Changelog data: {json.dumps(data, indent=2)}")
        return self._render(data)
