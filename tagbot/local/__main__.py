from argparse import ArgumentParser
from getpass import getpass
from pathlib import Path

import yaml

from ..action.repo import Repo

with open(Path(__file__).parent.parent.parent / "action.yml") as f:
    action = yaml.safe_load(f)
    CHANGELOG = action["inputs"]["changelog"]["default"]
    REGISTRY = action["inputs"]["registry"]["default"]


parser = ArgumentParser()
parser.add_argument("--repo", metavar="", required=True, help="Repo to tag")
parser.add_argument("--version", metavar="", required=True, help="Version to tag")
parser.add_argument("--token", metavar="", help="GitHub API token")
parser.add_argument(
    "--changelog", metavar="", default=CHANGELOG, help="Changelog template"
)
parser.add_argument(
    "--registry", metavar="", default=REGISTRY, help="Registry to search"
)
args = parser.parse_args()
if not args.token:
    args.token = getpass("GitHub API token: ")

repo = Repo(
    repo=args.repo,
    registry=args.registry,
    token=args.token,
    changelog=args.changelog,
    changelog_ignore=[],
    ssh=False,
    gpg=False,
    lookback=0,
)

version = args.version if args.version.startswith("v") else "v" + args.version
sha = repo.commit_sha_of_version(version)
if sha:
    repo.create_release(version, sha)
else:
    print(f"Commit for {version} was not found")
