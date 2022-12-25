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
    DRAFT = action["inputs"]["draft"]["default"]
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
@click.option("--draft", default=DRAFT, help="Create a draft release", is_flag=True)
@click.option("--subpackage_name", default=None, help="Name of subpackage in repo")
@click.option("--subpackage_uuid", default=None, help="UUID of subpackage in repo")
def main(
    repo: str,
    version: str,
    token: str,
    github: str,
    github_api: str,
    changelog: str,
    registry: str,
    draft: bool,
    subpackage_name: str,
    subpackage_uuid: str,
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
        draft=draft,
        registry_ssh="",
        user=USER,
        email=EMAIL,
        lookback=0,
        branch=None,
        subpackage_name=subpackage_name,
        subpackage_uuid=subpackage_uuid,
    )
    ## TODO: parse version into these correctly here
    package_version = ""
    tag_version = ""

    package_version = package_version 
    if not package_version.startswith("v"):
        package_version = f"v{package_version}"
    sha = r.commit_sha_of_version(package_version)
    if sha:
        r.create_release(tag_version, sha)
    else:
        print(f"Commit for {version} was not found")


if __name__ == "__main__":
    main()
