import json
import os
import re

from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import boto3

from github import Github, GithubException
from github.Issue import Issue
from github.IssueComment import IssueComment
from github.Repository import Repository
from pylev import levenshtein

from .. import logger
from . import TAGBOT_ISSUES_REPO_NAME

_ssm = boto3.client("ssm", region_name=os.getenv("AWS_REGION", "us-east-1"))
_gh: Optional[Github] = None


def _get_gh() -> Github:
    """Get a lazily-initialized GitHub client, reading the token from SSM."""
    global _gh
    if _gh is None:
        param_name = os.getenv("GITHUB_TOKEN_PARAM", "/tagbot/github-token")
        resp = _ssm.get_parameter(Name=param_name, WithDecryption=True)
        token = resp["Parameter"]["Value"]
        _gh = Github(token, per_page=100)
    return _gh


def _get_issues_repo() -> Repository:
    """Get the issues repo, lazily initialized."""
    return _get_gh().get_repo(TAGBOT_ISSUES_REPO_NAME, lazy=True)


_RUN_URL_RE = re.compile(
    r"^https://github\.com/(?P<repo>[^/]+/[^/]+)/actions/runs/(?P<run_id>\d+)"
)

# Workflow run statuses that indicate the run is still active. Reports are sent
# while TagBot is mid-run, so a legitimate report's run is never yet completed.
_ACTIVE_RUN_STATUSES = {"queued", "in_progress", "requested", "waiting", "pending"}


def _verify_run(repo: str, run: str) -> bool:
    """Verify that a report corresponds to a real, active TagBot run.

    The client only reports public repositories running in GitHub Actions, so the
    web service can independently confirm each report using its own GitHub token:
    it looks up the workflow run named in the report and checks that the run
    belongs to the claimed repository and is still active.

    Fails closed: if the run cannot be positively confirmed (private repo,
    nonexistent repo, mismatched or completed run, API error), the report is
    rejected. Private-repo runs are invisible to the token and never reported by
    the client, so they correctly never reach this point.
    """
    m = _RUN_URL_RE.match(run or "")
    if not m:
        logger.warning("Run URL did not match the expected format; rejecting")
        return False
    if m["repo"].casefold() != repo.casefold():
        logger.warning("Run URL repo does not match the reported repo; rejecting")
        return False
    run_id = int(m["run_id"])
    try:
        wf_run = _get_gh().get_repo(repo, lazy=True).get_workflow_run(run_id)
        full_name = wf_run.repository.full_name
        status = wf_run.status
    except GithubException as e:
        logger.warning(f"Could not verify workflow run (status {e.status}); rejecting")
        return False
    except Exception:
        logger.warning("Unexpected error verifying workflow run; rejecting")
        return False
    if not full_name or full_name.casefold() != repo.casefold():
        logger.warning("Workflow run repository mismatch; rejecting")
        return False
    if status not in _ACTIVE_RUN_STATUSES:
        logger.warning(f"Workflow run is not active (status {status}); rejecting")
        return False
    return True


def handler(event: Dict[str, str], ctx: object = None) -> None:
    """Lambda event handler."""
    logger.info(f"Event: {json.dumps(event, indent=2)}")
    _handle_report(
        image=event["image"],
        repo=event["repo"],
        run=event["run"],
        stacktrace=event["stacktrace"],
        version=event.get("version"),
        manual_intervention_url=event.get("manual_intervention_url"),
    )


def _handle_report(
    *,
    image: str,
    repo: str,
    run: str,
    stacktrace: str,
    version: Optional[str] = None,
    manual_intervention_url: Optional[str] = None,
) -> None:
    """Report an error."""
    if not _verify_run(repo, run):
        logger.warning(f"Rejecting unverifiable report for {repo}")
        return
    duplicate = _find_duplicate(stacktrace)
    if duplicate and duplicate.state == "open":
        logger.info(f"Found a duplicate (#{duplicate.number})")
        if _already_commented(duplicate, repo=repo):
            logger.info("Already reported")
        else:
            logger.info("Adding a comment")
            comment = _add_duplicate_comment(
                duplicate,
                image=image,
                repo=repo,
                run=run,
                stacktrace=stacktrace,
                version=version,
                manual_intervention_url=manual_intervention_url,
            )
            logger.info(f"Created comment: {comment.html_url}")
    else:
        closed_duplicate_url = None
        if duplicate:
            closed_duplicate_url = duplicate.html_url
            logger.info(
                f"Duplicate (#{duplicate.number}) is closed, creating new issue"
            )
        logger.info("Creating a new issue")
        issue = _create_issue(
            image=image,
            repo=repo,
            run=run,
            stacktrace=stacktrace,
            version=version,
            manual_intervention_url=manual_intervention_url,
            closed_duplicate_url=closed_duplicate_url,
        )
        logger.info(f"Created issue: {issue.html_url}")


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


_DUPLICATE_SEARCH_WINDOW = timedelta(days=60)


def _find_duplicate(stacktrace: str) -> Optional[Issue]:
    """Look for a duplicate error report updated within the search window."""
    since = datetime.now(timezone.utc) - _DUPLICATE_SEARCH_WINDOW
    for issue in _get_issues_repo().get_issues(state="all", since=since):
        m = re.search("(?s)```py\n(.*)\n```", issue.body)
        if not m:
            continue
        if _is_duplicate(stacktrace, m[1]):
            return issue
    return None


def _report_body(
    *,
    image: str,
    repo: str,
    run: str,
    stacktrace: str,
    version: Optional[str] = None,
    manual_intervention_url: Optional[str] = None,
    closed_duplicate_url: Optional[str] = None,
) -> str:
    """Format the error report."""
    lines = [
        f"Repo: {repo}",
        f"Run URL: {run}",
        f"Image ID: {image}",
    ]
    if version:
        lines.append(f"TagBot version: {version}")
    if manual_intervention_url:
        lines.append(f"Manual intervention issue: {manual_intervention_url}")
    if closed_duplicate_url:
        lines.append(f"Found a closed duplicate: {closed_duplicate_url}")
    lines.append(f"Stacktrace:\n```py\n{stacktrace}\n```\n")
    return "\n".join(lines)


def _add_duplicate_comment(
    issue: Issue,
    *,
    image: str,
    repo: str,
    run: str,
    stacktrace: str,
    version: Optional[str] = None,
    manual_intervention_url: Optional[str] = None,
) -> IssueComment:
    """Comment on an existing error report."""
    body = _report_body(
        image=image,
        repo=repo,
        run=run,
        stacktrace=stacktrace,
        version=version,
        manual_intervention_url=manual_intervention_url,
    )
    return issue.create_comment(f"Probably duplicate error:\n{body}")


def _create_issue(
    *,
    image: str,
    repo: str,
    run: str,
    stacktrace: str,
    version: Optional[str] = None,
    manual_intervention_url: Optional[str] = None,
    closed_duplicate_url: Optional[str] = None,
) -> Issue:
    """Create a new error report."""
    title = f"Automatic error report from {repo}"
    body = _report_body(
        image=image,
        repo=repo,
        run=run,
        stacktrace=stacktrace,
        version=version,
        manual_intervention_url=manual_intervention_url,
        closed_duplicate_url=closed_duplicate_url,
    )
    return _get_issues_repo().create_issue(title, body)
