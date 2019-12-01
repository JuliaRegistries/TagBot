import os
import subprocess
import tempfile

from datetime import datetime, timedelta
from typing import Dict, Optional
from urllib.parse import urlparse

import toml

from github import Github, UnknownObjectException

from . import env
from .changelog import get_changelog
from .util import *


class Abort(Exception):
    pass


def git(*argv: str, root=env.REPO_DIR) -> str:
    """Run a Git command."""
    args = ["git"]
    if root:
        args.extend(["-C", root])
    args.extend(argv)
    cmd = " ".join(args)
    debug(f"Running {cmd}")
    p = subprocess.run(args, capture_output=True)
    out = p.stdout.decode("utf-8")
    if p.returncode:
        if out:
            info(out)
        if p.stderr:
            info(p.stderr.decode("utf-8"))
        raise Abort(f"Git command '{cmd}' failed")
    return out.strip()


def get_versions(days_ago: int = 0) -> Dict[str, str]:
    """Get a mapping of version -> tree sha for each version in the registry."""
    with open(os.path.join(env.REPO_DIR, "Project.toml")) as f:
        project = toml.load(f)
    uuid = project["uuid"]
    gh = client()
    r = gh.get_repo(env.REGISTRY)
    registry_toml = r.get_contents("Registry.toml")
    registry = toml.loads(registry_toml.decoded_content.decode("utf-8"))
    if uuid in registry["packages"]:
        path = registry["packages"][uuid]["path"]
    else:
        return {}
    try:
        if days_ago:
            until = datetime.now() - timedelta(days=days_ago)
            commits = r.get_commits(until=until)
            for commit in commits:
                ref = commit.commit.sha
                break
            else:
                return {}
            versions_toml = r.get_contents(f"{path}/Versions.toml", ref=ref)
        else:
            versions_toml = r.get_contents(f"{path}/Versions.toml")
    except UnknownObjectException:
        return {}
    versions = toml.loads(versions_toml.decoded_content.decode("utf-8"))
    return {v: versions[v]["git-tree-sha1"] for v in versions}


def get_new_versions(max_age: int = 3) -> Dict[str, str]:
    """Collect all new versions of the package."""
    current = get_versions()
    old = get_versions(days_ago=max_age)
    return {v: sha for v, sha in current.items() if v not in old}


def release_exists(version: str) -> bool:
    """Check if a GitHub release already exists."""
    gh = Github(env.TOKEN)
    r = gh.get_repo(env.REPO, lazy=True)
    try:
        r.get_release(version)
    except UnknownObjectException:
        return False
    return True


def commit_from_tree(tree: str) -> Optional[str]:
    """Get the commit SHA that corresponds to a tree SHA."""
    for line in git("log", "--all", "--format=%H %T").splitlines():
        c, t = line.split()
        if t == tree:
            return c
    return None


def release_is_valid(version: str, sha: str) -> bool:
    """Check if a tag points at the commit that we expect it to."""
    # TODO check release via API
    return f"{sha} refs/tags/{version}^{{}}" in git("show-ref", "-d", version)


def create_release(version: str, sha: str, message: Optional[str]) -> None:
    """Create a GitHub release for the new version."""
    info("Creating GitHub release")
    gh = client()
    r = gh.get_repo(env.REPO, lazy=True)
    target = r.default_branch if git("rev-parse", "HEAD") == sha else sha
    debug(f"Target: {target}")
    r.create_git_release(version, version, message or "", target_commitish=target)
    info("Created GitHub release")
