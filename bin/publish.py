#!/usr/bin/env python3

import os
import re
import subprocess

DEST = "tagbot"
REF = os.environ["GITHUB_REF"]
REPO = os.environ["GITHUB_WORKSPACE"]
IMAGE = os.environ["DOCKER_IMAGE"]
USER = os.environ["DOCKER_USERNAME"]
PASS = os.environ["DOCKER_PASSWORD"]
VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def docker(*args, **kwargs):
    subprocess.run(["docker", *args], check=True, **kwargs)


def build():
    docker("build", "-t", DEST, REPO)


def tag(version):
    docker("tag", DEST, f"{USER}/{DEST}:{version}")


def login():
    docker("login", "-u", USER, "--password-stdin", input=PASS.encode("utf-8"))


def push(version):
    docker("push", f"{USER}/{DEST}:{version}")


def main():
    major, minor, patch = VERSION_RE.search(REF).groups()
    versions = ["latest", f"{major}", f"{major}.{minor}", f"{major}.{minor}.{patch}"]
    build()
    login()
    for version in versions:
        tag(version)
        push(version)


if __name__ == "__main__":
    main()
