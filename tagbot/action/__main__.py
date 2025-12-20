import json
import os
import sys
import time

from typing import Dict, Optional

from datetime import timedelta

from .. import logger
from .changelog import Changelog
from .repo import Repo, _metrics

INPUTS: Optional[Dict[str, str]] = None
CRON_WARNING = """\
Your TagBot workflow should be updated to use issue comment triggers instead of cron.
See this Discourse thread for more information: https://discourse.julialang.org/t/ann-required-updates-to-tagbot-yml/49249
"""  # noqa: E501


def get_input(key: str, default: str = "") -> str:
    """Get an input from the environment, or from a workflow input if it's set."""
    global INPUTS
    default = os.getenv(f"INPUT_{key.upper().replace('-', '_')}", default)
    if INPUTS is None:
        if "GITHUB_EVENT_PATH" not in os.environ:
            return default
        with open(os.environ["GITHUB_EVENT_PATH"]) as f:
            event = json.load(f)
        INPUTS = event.get("inputs") or {}
    return INPUTS.get(key.lower()) or default


try:
    # Reset metrics at start of each run
    _metrics.reset()

    if os.getenv("GITHUB_EVENT_NAME") == "schedule":
        logger.warning(CRON_WARNING)
    token = get_input("token")
    if not token:
        logger.error("No GitHub API token supplied")
        sys.exit(1)
    ssh = get_input("ssh")
    gpg = get_input("gpg")
    changelog_ignore = get_input("changelog_ignore")
    if changelog_ignore:
        ignore = changelog_ignore.split(",")
    else:
        ignore = Changelog.DEFAULT_IGNORE

    repo = Repo(
        repo=os.getenv("GITHUB_REPOSITORY", ""),
        registry=get_input("registry"),
        github=get_input("github"),
        github_api=get_input("github_api"),
        token=token,
        changelog=get_input("changelog"),
        changelog_ignore=ignore,
        ssh=bool(ssh),
        gpg=bool(gpg),
        draft=get_input("draft").lower() in ["true", "yes"],
        registry_ssh=get_input("registry_ssh"),
        user=get_input("user"),
        email=get_input("email"),
        branch=get_input("branch"),
        subdir=get_input("subdir"),
        tag_prefix=get_input("tag_prefix"),
    )

    if not repo.is_registered():
        logger.info("This package is not registered, skipping")
        logger.info(
            "If this repository is not going to be registered, then remove TagBot"
        )
        sys.exit()

    versions = repo.new_versions()
    if not versions:
        logger.info("No new versions to release")
        sys.exit()

    if get_input("dispatch", "false") == "true":
        minutes = int(get_input("dispatch_delay"))
        repo.create_dispatch_event(versions)
        logger.info(f"Waiting {minutes} minutes for any dispatch handlers")
        time.sleep(timedelta(minutes=minutes).total_seconds())

    if ssh:
        repo.configure_ssh(ssh, get_input("ssh_password"))
    if gpg:
        repo.configure_gpg(gpg, get_input("gpg_password"))

    # Determine which version should be marked as "latest" release.
    # Only the version with the most recent commit should be marked as latest.
    # This prevents backfilled old releases from being incorrectly marked as latest.
    latest_version = repo.version_with_latest_commit(versions)
    if latest_version:
        logger.info(
            f"Version {latest_version} has the most recent commit and will be marked as latest"
        )

    errors = []
    successes = []
    for version, sha in versions.items():
        try:
            logger.info(f"Processing version {version} ({sha})")
            if get_input("branches", "false") == "true":
                repo.handle_release_branch(version)
            is_latest = version == latest_version
            if not is_latest:
                logger.info(f"Version {version} will not be marked as latest release")
            repo.create_release(version, sha, is_latest=is_latest)
            successes.append(version)
            logger.info(f"Successfully released {version}")
        except Exception as e:
            logger.error(f"Failed to process version {version}: {e}")
            errors.append((version, sha, str(e)))
            repo.handle_error(e, raise_abort=False)

    if successes:
        logger.info(f"Successfully released versions: {', '.join(successes)}")
    if errors:
        failed = ", ".join(v for v, _, _ in errors)
        logger.error(f"Failed to release versions: {failed}")
        # Create an issue if any failures need manual intervention
        # This includes workflow permission issues and git push failures
        actionable_errors = [
            (v, sha, err)
            for v, sha, err in errors
            if "workflow" in err.lower()
            or "Resource not accessible" in err
            or "Git command" in err
        ]
        if actionable_errors:
            repo.create_issue_for_manual_tag(actionable_errors)
        _metrics.log_summary()
        sys.exit(1)
    _metrics.log_summary()
except Exception as e:
    try:
        repo.handle_error(e)
    except NameError:
        logger.exception("An unexpected, unreportable error occurred")
