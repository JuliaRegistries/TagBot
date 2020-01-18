#!/usr/bin/env python3

import os
import re
import subprocess
import sys

from typing import Optional

DEST = "tagbot"
REF = os.environ["GITHUB_REF"]
REPO = os.environ["GITHUB_WORKSPACE"]
IMAGE = os.environ["DOCKER_IMAGE"]
USER = os.environ["DOCKER_USERNAME"]
PASS = os.environ["DOCKER_PASSWORD"]
VERSION_RE = re.compile(r"^refs/tags/v(\d+)\.(\d+)\.(\d+)$")


def docker(*args: str, stdin: Optional[str] = None) -> None:
    subprocess.run(["docker", *args], check=True, text=True, input=stdin)


def build() -> None:
    docker("build", "-t", DEST, REPO)


def tag(version: str) -> None:
    docker("tag", DEST, f"{USER}/{DEST}:{version}")


def login() -> None:
    docker("login", "-u", USER, "--password-stdin", stdin=PASS)


def push(version: str) -> None:
    docker("push", f"{USER}/{DEST}:{version}")


def main() -> None:
    m = VERSION_RE.search(REF)
    if not m:
        print(f"Invalid tag {REF}")
        sys.exit(1)
    major, minor, patch = m.groups()
    versions = ["latest", f"{major}", f"{major}.{minor}", f"{major}.{minor}.{patch}"]
    build()
    login()
    for version in versions:
        tag(version)
        push(version)


if __name__ == "__main__":
    main()
