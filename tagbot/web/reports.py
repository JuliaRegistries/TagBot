import os
import re

from typing import Optional

from github import BadCredentialsException, Github
from github.Issue import Issue
from pylev import levenshtein

from . import TAGBOT_REPO_NAME, JSONResponse

_gh = Github(os.getenv("GITHUB_TOKEN"), per_page=100)
TAGBOT_REPO = _gh.get_repo(TAGBOT_REPO_NAME, lazy=True)
ERROR_LABEL = "error-report"


def handle(
    *, image: str, repo: str, run: str, stacktrace: str, token: str,
) -> JSONResponse:
    """Report an error."""
    if not _validate_token(token):
        return {"error": "Invalid token"}, 400
    duplicate = _find_duplicate(stacktrace)
    if duplicate:
        print(f"Found a duplicate (#{duplicate.number})")
        _add_duplicate_comment(
            duplicate, image=image, repo=repo, run=run, stacktrace=stacktrace
        )
        status = f"Duplicate: {duplicate.html_url}"
    else:
        print("Creating a new issue")
        issue = _create_issue(image=image, repo=repo, run=run, stacktrace=stacktrace)
        status = f"Created new issue: {issue.html_url}"
    return {"status": status}, 200


def _validate_token(token: str) -> bool:
    """Ensure that the provided token is valid."""
    if not token:
        return False
    gh = Github(token)
    user = gh.get_user()
    try:
        print("Token belongs to:", user.login)
        return True
    except BadCredentialsException:
        return False


def _is_duplicate(a: str, b: str) -> bool:
    """Determine whether two stacktraces are for the same error."""
    la = len(a)
    lb = len(b)
    denom = min(la, lb) + (la - lb) / 2
    ratio = levenshtein(a.casefold(), b.casefold()) / denom
    return ratio < 0.1


def _find_duplicate(stacktrace: str) -> Optional[Issue]:
    """Look for a duplicate error report."""
    for issue in TAGBOT_REPO.get_issues(labels=[ERROR_LABEL]):
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
) -> None:
    """Comment on an existing error report."""
    body = (
        f"Probably duplicate error:\n"
        f"{_report_body(image=image, repo=repo, run=run, stacktrace=stacktrace)}"
    )
    issue.create_comment(body)


def _create_issue(*, image: str, repo: str, run: str, stacktrace: str) -> Issue:
    """Create a new error report."""
    title = f"Automatic error report from {repo}"
    body = (
        f"{_report_body(image=image, repo=repo, run=run, stacktrace=stacktrace)}\n"
        f"[{ERROR_LABEL[:3]}]\n"  # Required for the automatic issue labeler.
    )
    return TAGBOT_REPO.create_issue(title, body)
