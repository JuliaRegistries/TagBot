import os
import sys
import time

from . import Abort, info, error
from .repo import Repo

repo_name = os.getenv("GITHUB_REPOSITORY", "")
branches = os.getenv("INPUT_BRANCHES", "false") == "true"
changelog = os.getenv("INPUT_CHANGELOG", "")
dispatch = os.getenv("INPUT_DISPATCH", "false") == "true"
registry_name = os.getenv("INPUT_REGISTRY", "")
ssh = os.getenv("INPUT_SSH", "")
token = os.getenv("INPUT_TOKEN", "")

if not token:
    error("No GitHub API token supplied")
    sys.exit(1)

repo = Repo(
    repo=repo_name,
    registry=registry_name,
    token=token,
    changelog=changelog,
    ssh=bool(ssh),
)
versions = repo.new_versions()

if not versions:
    info("No new versions to release")
    sys.exit(0)

if dispatch:
    repo.create_dispatch_event(versions)
    info("Waiting 5 minutes for any dispatch handlers")
    time.sleep(60 * 5)

if ssh:
    repo.configure_ssh(ssh)

for version, sha in versions.items():
    info(f"Processing version {version} ({sha})")
    try:
        if branches:
            repo.handle_release_branch(version)
        repo.create_release(version, sha)
    except Abort as e:
        error(e.args[0])

from . import STATUS  # noqa: E402

info(f"Exiting with status {STATUS}")
sys.exit(STATUS)
