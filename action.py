import json
import os
import subprocess

from typing import Any, Callable

import toml

from github import Github

EVENT_NAME = os.getenv("GITHUB_EVENT_NAME")
EVENT_PATH = os.getenv("GITHUB_EVENT_PATH")
REPO = os.getenv("GITHUB_REPOSITORY")
REPO_DIR = os.getenv("GITHUB_WORKSPACE")
TOKEN = os.getenv("INPUT_TOKEN")


def logger(level: str) -> Callable[[Any], None]:
    return lambda msg: print(f"::{level} ::{msg}")


debug = logger("debug")
warn = logger("warning")
error = logger("error")


def die(level: Callable[[Any], None], msg: str, status: int) -> None:
    level(msg)
    exit(status)


def read_event(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def git(*argv: str) -> str:
    args = ["git", "-C", REPO_DIR, *argv]
    p = subprocess.run(args, capture_output=True)
    out = p.stdout.decode("utf-8")
    if p.returncode:
        if out:
            print(out)
        if p.stderr:
            print(p.stderr.decode("utf-8"))
        cmd = ' '.join(args)
        die(error, f"Git command '{cmd}' failed", 1)
    return out


def validate(data: dict) -> None:
    if EVENT_NAME != "issue_comment":
        die(debug, "Not an issue comment", 0)
    if data["action"] != "created":
        die(debug, "Not a new issue comment", 0)
    if data["sender"]["login"] != "github-actions[bot]":
        die(debug, f"Comment not by GitHub Actions", 0)
    if not TOKEN:
        die(error, "The 'token' input parameter is required", 1)


def create_tag(version: str, sha: str) -> None:
    debug("Creating Git tag")
    if not os.path.isdir(REPO_DIR) or not os.os.listdir(REPO_DIR):
        die(error, "You must use the actions/checkout action prior to this one", 1)
    git("tag", version, sha)
    git("remote", "add", "with-token", f"https://oauth2:{TOKEN}@github.com/{REPO}")
    git("push", "with-token", "--tags")
    debug("Pushed Git tag")


def get_changelog(version: str) -> str:
    debug("Creating changelog")
    changelog = "TODO"
    debug("Created changelog")
    return changelog


def create_release(version: str, sha: str, message: str) -> None:
    debug("Creating GitHub release")
    gh = Github(TOKEN)
    r = gh.get_repo(REPO, lazy=True)
    target = r.default_branch if git("rev-parse", "HEAD") == sha else sha
    debug(f"Target: {target}")
    r.create_git_release(version, version, message, target_commitish=target)
    debug("Created GitHub release")


if __name__ == "__main__":
    event = read_event(EVENT_PATH)
    validate(event)
    try:
        data = toml.loads(event["comment"]["body"])
    except:
        die(error, "Invalid comment body", 1)
    debug(str(data))
    version = data["version"]
    if not version.startswith("v"):
        version = f"v{version}"
    sha = data["sha"]
    create_tag(version, sha)
    changelog = get_changelog(version)
    create_release(version, sha, changelog)
