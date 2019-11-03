#!/usr/bin/env python3

import os
import re
import subprocess

DEST = "tagbot"
REF = os.environ["GITHUB_REF"]
REPO = os.environ["GITHUB_WORKSPACE"]
IMAGE = os.environ["INPUT_IMAGE"]
USER = os.environ["INPUT_USERNAME"]
PASS = os.environ["INPUT_PASSWORD"]
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
    ref = REF[1:] if REF.startswith("v") else REF
    major, minor, patch = VERSION_RE.match(ref).groups()
    versions = [f"{major}", f"{major}.{minor}", f"{major}.{minor}.{patch}"]
    build()
    login()
    for version in versions:
        tag(version)
        push(version)


if __name__ == "__main__":
    main()
