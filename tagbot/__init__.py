import os
import subprocess
import tempfile

from typing import Any, Dict, Callable, List, Optional

import toml

from github import Github, UnknownObjectException

from . import env
from .changelog import get_changelog


def logger(level: str) -> Callable[[Any], None]:
    return lambda msg: print(f"::{level} ::{msg}")


debug = logger("debug")
info = print
warn = logger("warning")
error = logger("error")


def die(level: Callable[[Any], None], msg: str, status: int) -> None:
    level(msg)
    exit(status)


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
            print(out)
        if p.stderr:
            print(p.stderr.decode("utf-8"))
        die(error, f"Git command '{cmd}' failed", 1)
    return out.strip()


def clone_registry() -> str:
    """Clone the registry."""
    info("Cloning registry")
    path = tempfile.mkdtemp()
    git("clone", env.REGISTRY, path, root=None)
    info("Cloned registry")
    return path


def get_versions(registry: str) -> Dict[str, str]:
    """Get a mapping of version -> sha for each version in the registry."""
    with open(os.path.join(env.REPO_DIR, "Project.toml")) as f:
        project = toml.load(f)
    uuid = project["uuid"]
    with open(os.path.join(registry, "Registry.toml")) as f:
        reg = toml.load(f)
    path = reg["packages"][uuid]["path"]
    with open(os.path.join(registry, path, "Versions.toml")) as f:
        versions = toml.load(f)
    return {v: versions[v]["git-tree-sha1"] for v in versions}


def rollback(repo: str, days: int = 3) -> None:
    """Roll back a repo to a commit some time ago."""
    # https://stackoverflow.com/a/20801396
    spec = f"{days} days ago"
    sha = git("rev-list", "-n", "1", "--before", spec, "master", root=repo)
    git("checkout", sha, root=repo)


def get_new_versions() -> Dict[str, str]:
    """Collect all new versions of the package."""
    path = clone_registry()
    current = get_versions(path)
    rollback(path)
    old = get_versions(path)
    return {v: sha for v, sha in current.items() if v not in old}


def release_exists(version: str) -> bool:
    """Check if a GitHub release already exists."""
    gh = Github(env.TOKEN)
    r = gh.get_repo(env.REPO, lazy=True)
    # TODO: This should use a different endpoint:
    # https://developer.github.com/v3/repos/releases/#get-a-release-by-tag-name
    for rel in r.get_releases():
        if rel.tag_name == version:
            return True
    return False


def commit_from_tree(tree: str) -> Optional[str]:
    """Get the commit SHA that corresponds to a tree SHA."""
    lines = git("log", "--format=raw").splitlines()
    for i, line in enumerate(lines):
        if line == f"tree {tree}" and lines[i - 1].startswith("commit "):
            return lines[i - 1].split()[1]
    return None


def tag_exists(version: str) -> bool:
    """Check if a Git tag already exists."""
    gh = Github(env.TOKEN)
    r = gh.get_repo(env.REPO, lazy=True)
    try:
        r.get_git_ref(f"tags/{version}")
    except UnknownObjectException:
        return False
    return True


def setup_gpg() -> None:
    """Import a GPG key, and set it as the default key for Git."""
    if not env.GPG_KEY:
        info("No GPG key found")
        return
    _, path = tempfile.mkstemp()
    with open(path, "w") as f:
        f.write(env.GPG_KEY)
    subprocess.run(["gpg", "--import", path], check=True)
    key = (
        subprocess.run(["gpg", "--list-keys"], capture_output=True)
        .stdout.decode("utf-8")
        .splitlines()[3]
        .strip()
    )
    git("config", "user.signingKey", key)
    os.unlink(path)


def create_tag(version: str, sha: str) -> None:
    """Create and push a Git tag."""
    if tag_exists(version):
        info("Git tag already exists")
        return
    info("Creating Git tag")
    if not os.path.isdir(env.REPO_DIR) or not os.listdir(env.REPO_DIR):
        die(error, "You must use the actions/checkout action prior to this one", 1)
    setup_gpg()
    args = ["tag", version, sha]
    if env.GPG_KEY:
        args.append("-s")
    git(*args)
    remote = f"https://oauth2:{env.TOKEN}@github.com/{env.REPO}"
    git("remote", "add", "with-token", remote)
    git("push", "with-token", "--tags")
    info("Pushed Git tag")


def create_release(version: str, sha: str, message: Optional[str]) -> None:
    """Create a GitHub release for the new version."""
    info("Creating GitHub release")
    gh = Github(env.TOKEN)
    r = gh.get_repo(env.REPO, lazy=True)
    target = r.default_branch if git("rev-parse", "HEAD") == sha else sha
    info(f"Target: {target}")
    r.create_git_release(version, version, message or "", target_commitish=target)
    info("Created GitHub release")
