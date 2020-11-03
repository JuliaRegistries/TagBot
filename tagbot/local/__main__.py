from pathlib import Path

import click
import yaml

from ..action.repo import Repo

with (Path(__file__).parent.parent.parent / "action.yml").open() as f:
    action = yaml.safe_load(f)
    GITHUB = action["inputs"]["github"]["default"]
    GITHUB_API = action["inputs"]["github_api"]["default"]
    CHANGELOG = action["inputs"]["changelog"]["default"]
    REGISTRY = action["inputs"]["registry"]["default"]
    USER = action["inputs"]["user"]["default"]
    EMAIL = action["inputs"]["email"]["default"]


@click.command()
@click.option("--repo", help="Repo to tag", prompt=True)
@click.option("--version", help="Version to tag", prompt=True)
@click.option("--token", help="GitHub API token", prompt=True, hide_input=True)
@click.option("--github", default=GITHUB, help="GitHub URL")
@click.option("--github-api", default=GITHUB_API, help="GitHub API URL")
@click.option("--changelog", default=CHANGELOG, help="Changelog template")
@click.option("--registry", default=REGISTRY, help="Registry to search")
def main(
    repo: str,
    version: str,
    token: str,
    github: str,
    github_api: str,
    changelog: str,
    registry: str,
) -> None:
    r = Repo(
        repo=repo,
        registry=registry,
        github=github,
        github_api=github_api,
        token=token,
        changelog=changelog,
        changelog_ignore=[],
        ssh=False,
        gpg=False,
        user=USER,
        email=EMAIL,
        lookback=0,
        branch=None,
    )
    version = version if version.startswith("v") else f"v{version}"
    sha = r.commit_sha_of_version(version)
    if sha:
        r.create_release(version, sha)
    else:
        print(f"Commit for {version} was not found")


if __name__ == "__main__":
    main()
