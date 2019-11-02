import json
import os
import subprocess
import traceback

import toml

from github import Github

EVENT_NAME = os.environ["GITHUB_EVENT_NAME"]
EVENT_PATH = os.environ["GITHUB_EVENT_PATH"]
REPO = os.environ["GITHUB_REPOSITORY"]
REPO_DIR = os.environ["GITHUB_WORKSPACE"]
TOKEN = os.getenv("INPUT_TOKEN")


def logger(level):
    def write(msg):
        print(f"::{level} ::{msg}")

    return write


debug = logger("debug")
warn = logger("warning")
error = logger("error")


def die(level, msg, status):
    error(msg)
    exit(status)


def read_event(path):
    with open(path) as f:
        return json.load(f)


def git(*argv):
    args = ["git", "-C", REPO_DIR, *argv]
    p = subprocess.run(args, capture_output=True)
    out = p.stdout.decode("utf-8")
    if p.returncode:
        error(f"Git command '{' '.join(args)}' failed")
        if out:
            print(out)
        if p.stderr:
            print(p.stderr.decode("utf-8"))
        exit(1)
    return out


def validate(data):
    if EVENT_NAME != "issue_comment":
        die(debug, "Not an issue comment", 0)
    if data["action"] != "created":
        die(debug, "Not a new issue comment", 0)
        exit(0)
    if not TOKEN:
        die(error, "The 'token' input parameter is required", 1)
    # TODO: Check the author of the comment, and probably some other verification.


def create_tag(version, sha):
    debug("Creating Git tag")
    if not os.listdir(REPO_DIR):
        die(error, "You must use the actions/checkout action prior to this one", 1)
    git("tag", version, sha)
    git("remote", "add", "with-token", f"https://oauth2:{TOKEN}@github.com/{REPO}")
    git("push", "with-token", "--tags")
    debug("Pushed Git tag")


def create_changelog(version):
    debug("Creating changelog")
    changelog = "TODO"
    debug("Created changelog")
    return changelog


def create_release(version, sha, message):
    debug("Creating GitHub release")
    gh = Github(TOKEN)
    r = gh.get_repo(REPO, lazy=True)
    target = sha
    head = git("rev-parse", "HEAD")
    if head == sha:
        target = r.default_branch
    r.create_git_release(version, version, message, target_commitish=target)
    debug("Created GitHub release")


if __name__ == "__main__":
    event = read_event(EVENT_PATH)
    validate(event)
    try:
        data = toml.loads(event["comment"]["body"])
    except:
        error("Invalid comment body")
        traceback.print_exc()
        exit(1)
    debug(data)
    version = "v" + data["version"]
    sha = data["sha"]
    create_tag(version, sha)
    changelog = create_changelog(version)
    create_release(version, sha, changelog)
