import os
import time

from . import Abort, info, error
from .repo import Repo

repo_name = os.getenv("GITHUB_REPOSITORY", "")
dispatch = os.getenv("INPUT_DISPATCH", "false") == "true"
registry_name = os.getenv("INPUT_REGISTRY", "")
token = os.getenv("INPUT_TOKEN", "")

repo = Repo(repo_name, registry_name, token)
versions = repo.new_versions()

if not versions:
    info("No new versions to release")
    exit(0)

if dispatch:
    repo.create_dispatch_event(versions)
    info("Waiting 5 minutes for any dispatch handlers")
    time.sleep(60 * 5)

for version, sha in versions.items():
    info(f"Processing version {version} ({sha})")
    try:
        log = repo.changelog(version)
        repo.create_release(version, sha, log)
    except Abort as e:
        error(e.args[0])

from . import STATUS

exit(STATUS)
