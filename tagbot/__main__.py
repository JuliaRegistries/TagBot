from . import *

versions = get_new_versions()
if not versions:
    info("No new verions to release")
for version, tree in versions.items():
    version = f"v{version}"
    info(f"Processing version: {version}")
    sha = commit_from_tree(tree)
    if not sha:
        warn(f"Version {version} doesn't seem to have a matching commit")
        continue
    if release_exists(version):
        warn(f"Release {version} already exists")
        continue
    create_tag(version, sha)
    log = get_changelog(version)
    create_release(version, sha, log)
