import json
import os
import subprocess

from typing import Any, Callable

import toml

from github import Github, UnknownObjectException

from . import env


def logger(level: str) -> Callable[[Any], None]:
    return lambda msg: print(f"::{level} ::{msg}")


debug = logger("debug")
info = print
warn = logger("warning")
error = logger("error")


def die(level: Callable[[Any], None], msg: str, status: int) -> None:
    level(msg)
    exit(status)


def read_event(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def validate(data: dict) -> None:
    if env.EVENT_NAME != "issue_comment":
        die(info, "Not an issue comment", 0)
    if data["action"] != "created":
        die(info, "Not a new issue comment", 0)
    # TODO: Put me back when not testing myself
    # if data["sender"]["login"] != "github-actions[bot]":
    #     die(info, f"Comment not by GitHub Actions", 0)
    if not env.TOKEN:
        die(error, "The 'token' input parameter is required", 1)


parse_body = toml.loads


def git(*argv: str) -> str:
    """Run a Git command in the repository."""
    args = ["git", "-C", env.REPO_DIR, *argv]
    p = subprocess.run(args, capture_output=True)
    out = p.stdout.decode("utf-8")
    if p.returncode:
        if out:
            print(out)
        if p.stderr:
            print(p.stderr.decode("utf-8"))
        cmd = " ".join(args)
        die(error, f"Git command '{cmd}' failed", 1)
    return out


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


def tag_exists(version: str) -> bool:
    """Check if a Git tag already exists."""
    gh = Github(env.TOKEN)
    r = gh.get_repo(env.REPO, lazy=True)
    try:
        r.get_git_ref(f"tags/{version}")
    except UnknownObjectException:
        return False
    return True


def create_tag(version: str, sha: str) -> None:
    """Create and push a Git tag."""
    if tag_exists(version):
        info("Git tag already exists")
        return
    info("Creating Git tag")
    if not os.path.isdir(env.REPO_DIR) or not os.listdir(env.REPO_DIR):
        die(error, "You must use the actions/checkout action prior to this one", 1)
    git("tag", version, sha)
    remote = f"https://oauth2:{env.TOKEN}@github.com/{env.REPO}"
    git("remote", "add", "with-token", remote)
    git("push", "with-token", "--tags")
    info("Pushed Git tag")


def get_changelog(version: str) -> str:
    """Generate a changelog for the new version."""
    info("Creating changelog")
    changelog = "TODO"
    info("Created changelog")
    return changelog


def create_release(version: str, sha: str, message: str) -> None:
    """Create a GitHub release for the new version."""
    info("Creating GitHub release")
    gh = Github(env.TOKEN)
    r = gh.get_repo(env.REPO, lazy=True)
    target = r.default_branch if git("rev-parse", "HEAD") == sha else sha
    info(f"Target: {target}")
    r.create_git_release(version, version, message, target_commitish=target)
    info("Created GitHub release")
