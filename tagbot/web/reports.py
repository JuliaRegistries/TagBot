import json
import os
import re

from typing import Dict, List, Optional, cast

from github import Github
from github.Issue import Issue
from github.IssueComment import IssueComment
from pylev import levenshtein

from . import TAGBOT_REPO_NAME

_gh = Github(os.getenv("GITHUB_TOKEN"), per_page=100)
TAGBOT_REPO = _gh.get_repo(TAGBOT_REPO_NAME, lazy=True)
ERROR_LABEL = "error-report"


def handler(event: Dict[str, object], ctx: object = None) -> None:
    """Lambda event handler."""
    records = cast(List[Dict[str, object]], event["Records"])
    print(f"Processing {len(records)} records")
    for record in records:
        body = json.loads(cast(str, record["body"]))
        print(f"Record: {json.dumps(body, indent=2)}")
        _handle_report(
            image=body["image"],
            repo=body["repo"],
            run=body["run"],
            stacktrace=body["stacktrace"],
        )


def _handle_report(*, image: str, repo: str, run: str, stacktrace: str) -> None:
    """Report an error."""
    duplicate = _find_duplicate(stacktrace)
    if duplicate:
        print(f"Found a duplicate (#{duplicate.number})")
        if _already_commented(duplicate, repo=repo):
            print("Already reported")
        else:
            print("Adding a comment")
            comment = _add_duplicate_comment(
                duplicate, image=image, repo=repo, run=run, stacktrace=stacktrace
            )
            print(f"Created comment: {comment.html_url}")
    else:
        print("Creating a new issue")
        issue = _create_issue(image=image, repo=repo, run=run, stacktrace=stacktrace)
        print(f"Created issue: {issue.html_url}")


def _already_commented(issue: Issue, *, repo: str) -> bool:
    """Check whether this repository has already commented on the issue."""
    target = f"Repo: {repo}"
    if target in issue.body:
        return True
    for comment in issue.get_comments():
        if target in comment.body:
            return True
    return False


def _is_duplicate(a: str, b: str) -> bool:
    """Determine whether two stacktraces are for the same error."""
    la = len(a)
    lb = len(b)
    diff = abs(la - lb)
    if diff > 50:
        return False
    denom = min(la, lb) + diff / 2
    ratio = levenshtein(a.casefold(), b.casefold()) / denom
    return ratio < 0.1


def _find_duplicate(stacktrace: str) -> Optional[Issue]:
    """Look for a duplicate error report."""
    for issue in TAGBOT_REPO.get_issues(state="all", labels=[ERROR_LABEL]):
        m = re.search("(?s)```py\n(.*)\n```", issue.body)
        if not m:
            continue
        if _is_duplicate(stacktrace, m[1]):
            return issue
    return None


def _report_body(*, image: str, repo: str, run: str, stacktrace: str) -> str:
    """Format the error report."""
    return (
        f"Repo: {repo}\n"
        f"Run URL: {run}\n"
        f"Image ID: {image}\n"
        f"Stacktrace:\n```py\n{stacktrace}\n```\n"
    )


def _add_duplicate_comment(
    issue: Issue, *, image: str, repo: str, run: str, stacktrace: str
) -> IssueComment:
    """Comment on an existing error report."""
    body = (
        f"Probably duplicate error:\n"
        f"{_report_body(image=image, repo=repo, run=run, stacktrace=stacktrace)}"
    )
    return issue.create_comment(body)


def _create_issue(*, image: str, repo: str, run: str, stacktrace: str) -> Issue:
    """Create a new error report."""
    title = f"Automatic error report from {repo}"
    body = (
        f"{_report_body(image=image, repo=repo, run=run, stacktrace=stacktrace)}"
        f"[{ERROR_LABEL[:3]}]\n"  # Required for the automatic issue labeler.
    )
    return TAGBOT_REPO.create_issue(title, body)
