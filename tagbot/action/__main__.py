import json
import os
import sys
import time

from typing import Dict, Optional

from datetime import timedelta

from .. import logger
from .changelog import Changelog
from .repo import Repo

INPUTS: Optional[Dict[str, str]] = None


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
        user=get_input("user"),
        email=get_input("email"),
        lookback=int(get_input("lookback")),
        branch=get_input("branch"),
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

    for version, sha in versions.items():
        logger.info(f"Processing version {version} ({sha})")
        if get_input("branches", "false") == "true":
            repo.handle_release_branch(version)
        repo.create_release(version, sha)
except Exception as e:
    try:
        repo.handle_error(e)
    except NameError:
        logger.exception("An unexpected, unreportable error occurred")
