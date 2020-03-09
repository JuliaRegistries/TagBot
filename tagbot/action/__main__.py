import os
import sys
import time
import traceback

from datetime import timedelta

from github import GithubException
from github.Requester import requests

from . import info, error, warn
from .changelog import Changelog
from .repo import Repo

RequestException = requests.RequestException

repo_name = os.getenv("GITHUB_REPOSITORY", "")
branches = os.getenv("INPUT_BRANCHES", "false") == "true"
changelog = os.getenv("INPUT_CHANGELOG", "")
changelog_ignore = os.getenv("INPUT_CHANGELOG_IGNORE", "")
dispatch = os.getenv("INPUT_DISPATCH", "false") == "true"
dispatch_delay = os.getenv("INPUT_DISPATCH_DELAY", "")
lookback = os.getenv("INPUT_LOOKBACK", "3")
registry_name = os.getenv("INPUT_REGISTRY", "")
ssh = os.getenv("INPUT_SSH")
ssh_password = os.getenv("INPUT_SSH_PASSWORD")
gpg = os.getenv("INPUT_GPG")
gpg_password = os.getenv("INPUT_GPG_PASSWORD")
token = os.getenv("INPUT_TOKEN")

if not token:
    error("No GitHub API token supplied")
    sys.exit(1)

try:
    if changelog_ignore:
        ignore = changelog_ignore.split(",")
    else:
        ignore = Changelog.DEFAULT_IGNORE

    repo = Repo(
        repo=repo_name,
        registry=registry_name,
        token=token,
        changelog=changelog,
        changelog_ignore=ignore,
        ssh=bool(ssh),
        gpg=bool(gpg),
        lookback=int(lookback),
    )

    if not repo.is_registered():
        info("This package is not registered, skipping")
        info("If this repository is not going to be registered, then remove TagBot")
        sys.exit()

    versions = repo.new_versions()
    if not versions:
        info("No new versions to release")
        sys.exit()

    if dispatch:
        minutes = int(dispatch_delay)
        repo.create_dispatch_event(versions)
        info(f"Waiting {minutes} minutes for any dispatch handlers")
        time.sleep(timedelta(minutes=minutes).total_seconds())
    if ssh:
        repo.configure_ssh(ssh, ssh_password)
    if gpg:
        repo.configure_gpg(gpg, gpg_password)

    for version, sha in versions.items():
        info(f"Processing version {version} ({sha})")
        if branches:
            repo.handle_release_branch(version)
        repo.create_release(version, sha)
except Exception as e:
    report = True
    if isinstance(e, GithubException):
        if 500 <= e.status < 600:
            warn("GitHub returned a 5xx error code")
            traceback.print_exc()
            report = False
    elif isinstance(e, RequestException):
        warn("TagBot encountered a likely transient HTTP exception")
        traceback.print_exc()
        report = False
    if report:
        try:
            repo.report_error(traceback.format_exc())
        except Exception:
            error("Issue reporting failed")
            traceback.print_exc()
