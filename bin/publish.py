#!/usr/bin/env python3

import json
import os
import re
import subprocess

from subprocess import DEVNULL
from tempfile import mkstemp
from typing import List, Optional

from github import Github, GithubException
from github.PullRequest import PullRequest
from github.Repository import Repository
from semver import VersionInfo

REPO = os.environ["GITHUB_REPOSITORY"]
WORKSPACE = os.environ["GITHUB_WORKSPACE"]
DOCKER_IMAGE = os.environ["DOCKER_IMAGE"]
DOCKER_USERNAME = os.environ["DOCKER_USERNAME"]
DOCKER_PASSWORD = os.environ["DOCKER_PASSWORD"]
GH = Github(os.environ["GITHUB_TOKEN"])


def configure_ssh() -> None:
    _, key = mkstemp()
    with open(key, "w") as f:
        f.write(os.environ["SSH_KEY"].strip() + "\n")
    os.chmod(key, 0o400)
    _, hosts = mkstemp()
    with open(hosts, "w") as f:
        subprocess.run(
            ["ssh-keyscan", "-t", "rsa", "github.com"],
            check=True,
            stdout=f,
            stderr=DEVNULL,
        )
    git("remote", "set-url", "origin", f"git@github.com:{REPO}.git")
    git("config", "core.sshCommand", f"ssh -i {key} -o UserKnownHostsFile={hosts}")


def on_workflow_dispatch(version: str) -> None:
    semver = resolve_version(version)
    if semver.build is not None or semver.prerelease is not None:
        raise ValueError("Only major, minor, and patch components should be set")
    update_pyproject_toml(semver)
    digest = build_and_push_versioned_image(semver)
    update_action_yml(semver, digest)
    branch = git_push(semver)
    repo = GH.get_repo(REPO)
    msg = f"Release {semver}"
    repo.create_pull(title=msg, body=msg, head=branch, base="master")


def on_pull_request(number: int) -> None:
    repo = GH.get_repo(REPO)
    pr = repo.get_pull(number)
    if not pr.merged or not pr.head.ref.startswith("release/"):
        return
    version = current_version()
    tag_sha = pr.merge_commit_sha
    git("fetch", "origin", "master")
    git("checkout", "-B", "master", "origin/master")
    update_action_ref_pins(version, tag_sha)
    git("add", "--all")
    has_changes = (
        subprocess.run(
            ["git", "-C", WORKSPACE, "diff", "--cached", "--quiet"], check=False
        ).returncode
        != 0
    )
    if has_changes:
        git("commit", "--message", f"Pin action refs to v{version}")
        git("push", "origin", "master")
    update_tags(tag_sha)
    create_release(repo, pr, tag_sha)
    push_floating_tags()


def git(*args: str) -> None:
    subprocess.run(["git", "-C", WORKSPACE, *args], check=True)


def resolve_version(bump: str) -> VersionInfo:
    if bump not in ["major", "minor", "patch"]:
        raise ValueError(f"Invalid bump: {bump}")
    current = current_version()
    return current.next_version(bump)


def current_version() -> VersionInfo:
    with open(repo_file("pyproject.toml")) as f:
        pyproject = f.read()
    m = re.search(r'version = "(.*)"', pyproject)
    if not m:
        raise ValueError("Invalid pyproject.toml")
    return VersionInfo.parse(m[1])


def repo_file(*paths: str) -> str:
    return os.path.join(os.path.dirname(__file__), "..", *paths)


def update_pyproject_toml(version: VersionInfo) -> None:
    path = repo_file("pyproject.toml")
    with open(path) as f:
        pyproject = f.read()
    updated = re.sub(r"version = .*", f'version = "{version}"', pyproject, count=1)
    with open(path, "w") as f:
        f.write(updated)


def update_action_yml(version: VersionInfo, digest: str) -> None:
    path = repo_file("action.yml")
    with open(path) as f:
        action = f.read()
    updated = re.sub(
        r"image: docker://\S+",
        f"image: docker://{DOCKER_IMAGE}:{version}@sha256:{digest}",
        action,
        count=1,
    )
    with open(path, "w") as f:
        f.write(updated)


def git_push(version: VersionInfo) -> str:
    branch = f"release/{version}"
    msg = f"Release {version}"
    git("checkout", "-B", branch)
    git("commit", "--all", "--message", msg)
    git("push", "origin", "--force", branch)
    return branch


def update_tags(commit: str) -> None:
    for version in expand_versions(v=True):
        git("tag", "--force", version, commit)
    git("push", "origin", "--tags", "--force")


def expand_versions(*, v: bool) -> List[str]:
    prefix = "v" if v else ""
    version = current_version()
    return [
        "latest",
        f"{prefix}{version.major}",
        f"{prefix}{version.major}.{version.minor}",
        f"{prefix}{version.major}.{version.minor}.{version.patch}",
    ]


def update_action_ref_pins(version: VersionInfo, sha: str) -> None:
    files = [
        repo_file("example.yml"),
        repo_file(".github", "workflows", "tagbot.yml"),
        repo_file("README.md"),
        repo_file("IMPROVEMENTS.md"),
    ]
    for path in files:
        with open(path) as f:
            content = f.read()
        updated = re.sub(
            r"uses: JuliaRegistries/TagBot@[^\s#]+(?:\s*#[^\n]*)?",
            f"uses: JuliaRegistries/TagBot@{sha} # v{version}",
            content,
        )
        with open(path, "w") as f:
            f.write(updated)


def create_release(repo: Repository, pr: PullRequest, commit: str) -> None:
    notes = get_release_notes(pr)
    release = "v" + str(current_version())
    try:
        repo.create_git_release(
            tag=release,
            name=release,
            message=notes,
            target_commitish=commit,
            generate_release_notes=True,
        )
    except GithubException as e:
        if e.status == 422:
            print("This release already exists, ignoring")
        else:
            raise


def get_release_notes(pr: PullRequest) -> str:
    for comment in pr.get_issue_comments():
        m = re.search("(?si)Release notes:(.*)", comment.body)
        if m:
            return m[1].strip()
    return ""


def build_and_push_versioned_image(version: VersionInfo) -> str:
    tag = f"{DOCKER_IMAGE}:{version}"
    server = [DOCKER_IMAGE.split("/")[0]] if DOCKER_IMAGE.count("/") > 1 else []
    docker(
        "login",
        "--username",
        DOCKER_USERNAME,
        "--password-stdin",
        *server,
        stdin=DOCKER_PASSWORD,
    )
    docker("build", "--tag", tag, WORKSPACE)
    docker("push", tag)
    result = subprocess.run(
        ["docker", "inspect", "--format={{index .RepoDigests 0}}", tag],
        check=True,
        capture_output=True,
        text=True,
    )
    ref = result.stdout.strip()
    if "@sha256:" not in ref:
        raise RuntimeError(
            f"Could not determine digest for {tag}: docker inspect returned {ref!r}"
        )
    return ref.split("@sha256:")[1]


def push_floating_tags() -> None:
    version = current_version()
    versioned_tag = f"{DOCKER_IMAGE}:{version}"
    server = [DOCKER_IMAGE.split("/")[0]] if DOCKER_IMAGE.count("/") > 1 else []
    docker(
        "login",
        "--username",
        DOCKER_USERNAME,
        "--password-stdin",
        *server,
        stdin=DOCKER_PASSWORD,
    )
    docker("pull", versioned_tag)
    for float_version in [
        str(version.major),
        f"{version.major}.{version.minor}",
        "latest",
    ]:
        tag = f"{DOCKER_IMAGE}:{float_version}"
        docker("tag", versioned_tag, tag)
        docker("push", tag)


def docker(*args: str, stdin: Optional[str] = None) -> None:
    subprocess.run(["docker", *args], check=True, text=True, input=stdin)


if __name__ == "__main__":
    configure_ssh()
    name = os.environ["GITHUB_EVENT_NAME"]
    with open(os.environ["GITHUB_EVENT_PATH"]) as f:
        event = json.load(f)
    if name == "workflow_dispatch":
        on_workflow_dispatch(event["inputs"]["bump"])
    elif name == "pull_request":
        on_pull_request(event["pull_request"]["number"])
