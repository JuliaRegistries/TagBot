import os

import toml

from datetime import datetime, timedelta
from stat import S_IREAD
from tempfile import mkstemp
from typing import Any, Dict, MutableMapping, Optional

from github import Github, UnknownObjectException
from github.Requester import requests

from . import DELTA, Abort, debug, info, warn, error
from .changelog import Changelog
from .git import Git


class Repo:
    """A Repo has access to its Git repository and registry metadata."""

    def __init__(
        self, *, repo: str, registry: str, token: str, changelog: str, ssh: bool,
    ):
        gh = Github(token, per_page=100)
        self._repo = gh.get_repo(repo, lazy=True)
        self._registry = gh.get_repo(registry, lazy=True)
        self._token = token
        self._changelog = Changelog(self, changelog)
        self._ssh = ssh
        self._git = Git(repo, token)
        self.__project: Optional[MutableMapping[str, Any]] = None
        self.__registry_path: Optional[str] = None

    def _project(self, k: str) -> str:
        """Get a value from the Project.toml."""
        if self.__project is not None:
            return str(self.__project[k])
        for name in ["Project.toml", "JuliaProject.toml"]:
            path = self._git.path(name)
            if os.path.isfile(path):
                with open(path) as f:
                    self.__project = toml.load(f)
                return str(self.__project[k])
        raise Abort("Project file was not found")

    @property
    def _registry_path(self) -> Optional[str]:
        """Get the package's path in the registry repo."""
        if self.__registry_path is not None:
            return self.__registry_path
        contents = self._registry.get_contents("Registry.toml")
        registry = toml.loads(contents.decoded_content.decode())
        uuid = self._project("uuid")
        if uuid in registry["packages"]:
            self.__registry_path = registry["packages"][uuid]["path"]
            return self.__registry_path
        return None

    def _release_exists(self, version: str) -> bool:
        """Check whether or not a GitHub release exists."""
        try:
            self._repo.get_release(version)
            return True
        except UnknownObjectException:
            return False

    def _create_release_branch_pr(self, version: str, branch: str) -> None:
        """Create a pull request for the release branch."""
        self._repo.create_pull(
            title=f"Merge release branch for {version}",
            body="",
            head=branch,
            base=self._repo.default_branch,
        )

    def _filter_map_versions(self, versions: Dict[str, str]) -> Dict[str, str]:
        """Filter out versions and convert tree SHA to commit SHA."""
        valid = {}
        for version, tree in versions.items():
            version = f"v{version}"
            sha = self._git.commit_sha_of_tree(tree)
            if not sha:
                warn(f"No matching commit was found for version {version} ({tree})")
                continue
            if self._git.invalid_tag_exists(version, sha):
                msg = f"Existing tag {version} points at the wrong commit (expected {sha})"  # noqa: E501
                error(msg)
                continue
            if self._release_exists(version):
                info(f"Release {version} already exists")
                continue
            valid[version] = sha
        return valid

    def _versions(self, min_age: Optional[timedelta] = None) -> Dict[str, str]:
        """Get all package versions from the registry."""
        kwargs = {}
        if min_age:
            # Get the most recent commit from before min_age.
            until = datetime.now() - min_age
            commits = self._registry.get_commits(until=until)
            for commit in commits:
                kwargs["ref"] = commit.commit.sha
                break
            else:
                debug("No registry commits were found")
                return {}
        root = self._registry_path
        try:
            contents = self._registry.get_contents(f"{root}/Versions.toml", **kwargs)
        except UnknownObjectException:
            debug("Versions.toml was not found")
            return {}
        versions = toml.loads(contents.decoded_content.decode())
        return {v: versions[v]["git-tree-sha1"] for v in versions}

    def new_versions(self) -> Dict[str, str]:
        """Get all new versions of the package."""
        current = self._versions()
        debug(f"There are {len(current)} total versions")
        old = self._versions(min_age=DELTA)
        debug(f"There are {len(old)} new versions")
        versions = {k: v for k, v in current.items() if k not in old}
        return self._filter_map_versions(versions)

    def create_dispatch_event(self, payload: Dict[str, Any]) -> None:
        """Create a repository dispatch event."""
        resp = requests.post(
            f"https://api.github.com/repos/{self._repo.full_name}/dispatches",
            headers={
                "Accept": "application/vnd.github.everest-preview+json",
                "Authorization": f"token {self._token}",
            },
            json={"event_type": "TagBot", "client_payload": payload},
        )
        debug(f"Dispatch response code: {resp.status_code}")

    def configure_ssh(self, key: str) -> None:
        """Configure the repo to use an SSH key for authentication."""
        self._git.set_remote_url(self._repo.ssh_url)
        _, path = mkstemp(prefix="tagbot_key_")
        debug(f"Writing SSH key to {path}")
        with open(path, "w") as f:
            f.write(key)
        os.chmod(path, S_IREAD)
        self._git.config("core.sshCommand", f"ssh -i {path}")

    def handle_release_branch(self, version: str) -> None:
        """Merge an existing release branch or create a PR to merge it."""
        branch = f"release-{version[1:]}"
        if not self._git.fetch_branch(branch):
            info(f"Release branch {branch} does not exist")
            return
        if self._git.can_fast_forward(branch):
            info("Release branch can be fast-forwarded")
            self._git.merge_and_delete_branch(branch)
        else:
            info("Release branch cannot be fast-forwarded, creating pull request")
            self._create_release_branch_pr(version, branch)

    def create_release(self, version: str, sha: str) -> None:
        """Create a GitHub release."""
        target = sha
        if self._git.commit_sha_of_default() == sha:
            target = self._repo.default_branch
        log = self._changelog.get(version, sha)
        info(f"Creating release {version} at {sha} (target {target})")
        if self._ssh:
            info("Using SSH key to create a tag")
            self._git.create_tag(version, sha)
        self._repo.create_git_release(version, version, log, target_commitish=target)
