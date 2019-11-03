from . import *

versions = get_new_versions()
for version, tree in versions:
    sha = commit_from_tree(tree)
    if not sha:
        warn(f"Version {version} doesn't seem to have a matching commit")
        continue
    if release_exists(version):
        die(warn, f"Release {version} already exists", 0)
    create_tag(version, sha)
    log = get_changelog(version)
    create_release(version, sha, log)
