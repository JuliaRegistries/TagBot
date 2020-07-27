from argparse import ArgumentParser
from getpass import getpass
from pathlib import Path

import yaml

from ..action.repo import Repo

with open(Path(__file__).parent.parent.parent / "action.yml") as f:
    action = yaml.safe_load(f)
    GITHUB = action["inputs"]["github"]["default"]
    GITHUB_API = action["inputs"]["github_api"]["default"]
    CHANGELOG = action["inputs"]["changelog"]["default"]
    REGISTRY = action["inputs"]["registry"]["default"]
    USER = action["inputs"]["user"]["default"]
    EMAIL = action["inputs"]["email"]["default"]


parser = ArgumentParser()
parser.add_argument("--repo", required=True, metavar="", help="Repo to tag")
parser.add_argument("--version", required=True, metavar="", help="Version to tag")
parser.add_argument("--token", metavar="", help="GitHub API token")
parser.add_argument("--github", default=GITHUB, metavar="", help="GitHub URL")
parser.add_argument(
    "--github-api", default=GITHUB_API, metavar="", help="GitHub API URL"
)
parser.add_argument(
    "--changelog", default=CHANGELOG, metavar="", help="Changelog template"
)
parser.add_argument(
    "--registry", default=REGISTRY, metavar="", help="Registry to search"
)
args = parser.parse_args()
if not args.token:
    args.token = getpass("GitHub API token: ")

repo = Repo(
    repo=args.repo,
    registry=args.registry,
    github=args.github,
    github_api=args.github_api,
    token=args.token,
    changelog=args.changelog,
    changelog_ignore=[],
    ssh=False,
    gpg=False,
    user=USER,
    email=EMAIL,
    lookback=0,
)

version = args.version if args.version.startswith("v") else "v" + args.version
sha = repo.commit_sha_of_version(version)
if sha:
    repo.create_release(version, sha)
else:
    print(f"Commit for {version} was not found")
