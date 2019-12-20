import os

import toml

from datetime import datetime, timedelta
from tempfile import mkdtemp
from typing import Any, Dict, MutableMapping, Optional

from github import Github, UnknownObjectException
from github.Requester import requests

from . import DELTA, Abort, git, git_check, debug, info, warn, error
from .changelog import get_changelog


class Repo:
    """A Repo has access to its Git repository and registry metadata."""

    def __init__(self, name: str, registry: str, token: str):
        self.__token = token
        self.__gh = Github(self.__token)
        self.__repo = self.__gh.get_repo(name, lazy=True)
        self.__registry = self.__gh.get_repo(registry, lazy=True)
        self.__dir: Optional[str] = None
        self.__project: Optional[MutableMapping[str, Any]] = None
        self.__registry_path: Optional[str] = None

    def _project(self, k) -> str:
        """Get a value from the Project.toml."""
        if self.__project is not None:
            return self.__project[k]
        for name in ["Project.toml", "JuliaProject.toml"]:
            path = os.path.join(self._dir(), name)
            if os.path.isfile(path):
                with open(path) as f:
                    self.__project = toml.load(f)
                return self.__project[k]
        raise Abort("Project file was not found")

    def _registry_path(self) -> Optional[str]:
        """Get the package's path in the registry repo."""
        if self.__registry_path is not None:
            return self.__registry_path
        contents = self.__registry.get_contents("Registry.toml")
        registry = toml.loads(contents.decoded_content.decode())
        uuid = self._project("uuid")
        if uuid in registry["packages"]:
            self.__registry_path = registry["packages"][uuid]["path"]
            return self.__registry_path
        return None

    def _dir(self) -> str:
        """Get the repository clone location (cloning if necessary)."""
        if self.__dir is not None:
            return self.__dir
        url = f"https://oauth2:{self.__token}@github.com/{self.__repo.full_name}"
        dest = mkdtemp(prefix="tagbot_repo_")
        git("clone", url, dest)
        self.__dir = dest
        return self.__dir

    def _commit_from_tree(self, tree: str) -> Optional[str]:
        """Get the commit SHA that corresponds to a tree SHA."""
        lines = git("log", "--all", "--format=%H %T", repo=self._dir()).splitlines()
        for line in lines:
            c, t = line.split()
            if t == tree:
                return c
        return None

    def _fetch_branch(self, master: str, branch: str) -> bool:
        """Try to checkout a remote branch, and return whether or not it succeeded."""
        if not git_check("checkout", branch, repo=self._dir()):
            return False
        git("checkout", master, repo=self._dir())
        return True

    def _tag_exists(self, version: str) -> bool:
        """Check whether or not a tag exists locally."""
        return bool(git("tag", "--list", version, repo=self._dir()))

    def _release_exists(self, version) -> bool:
        """Check whether or not a GitHub release exists."""
        try:
            self.__repo.get_release(version)
            return True
        except UnknownObjectException:
            return False

    def _invalid_tag_exists(self, version: str, sha: str) -> bool:
        """Check whether or not an existing tag points at the wrong commit."""
        if not self._tag_exists(version):
            return False
        lines = git("show-ref", "-d", version, repo=self._dir()).splitlines()
        # For annotated tags, there are two entries.
        # The one with the ^{} suffix uses the commit hash.
        expected = f"{sha} refs/tags/{version}"
        return expected not in lines and f"{expected}^{{}}" not in lines

    def _filter_map_versions(self, versions: Dict[str, str]) -> Dict[str, str]:
        """Filter out versions and convert tree SHA to commit SHA."""
        valid = {}
        for version, tree in versions.items():
            version = f"v{version}"
            sha = self._commit_from_tree(tree)
            if not sha:
                warn(f"No matching commit was found for version {version} ({tree})")
                continue
            if self._invalid_tag_exists(version, sha):
                error(
                    f"Existing tag {version} points at the wrong commit (expected {sha})"
                )
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
            commits = self.__registry.get_commits(until=until)
            for commit in commits:
                kwargs["ref"] = commit.commit.sha
                break
            else:
                debug("No registry commits were found")
                return {}
        root = self._registry_path()
        try:
            contents = self.__registry.get_contents(f"{root}/Versions.toml", **kwargs)
        except UnknownObjectException:
            debug("Versions.toml was not found")
            return {}
        versions = toml.loads(contents.decoded_content.decode())
        return {v: versions[v]["git-tree-sha1"] for v in versions}

    def _can_fast_forward(self, master: str, branch: str) -> bool:
        """Check whether master can be fast-forwarded to branch."""
        return git_check(
            "merge-base", "--is-ancestor", master, branch, repo=self._dir()
        )

    def _merge_and_delete_branch(self, master: str, branch: str) -> None:
        """Merge a branch into master and delete the branch."""
        git("checkout", master, repo=self._dir())
        git("merge", branch, repo=self._dir())
        git("push", "origin", master, repo=self._dir())
        git("push", "-d", "origin", branch, repo=self._dir())

    def _create_release_branch_pr(self, version: str, master: str, branch: str) -> None:
        """Create a pull request for the release branch."""
        self.__repo.create_pull(
            title=f"Merge release branch for {version}",
            body="",
            head=branch,
            base=master,
        )

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
            f"https://api.github.com/repos/{self.__repo.full_name}/dispatches",
            headers={
                "Accept": "application/vnd.github.everest-preview+json",
                "Authorization": f"token {self.__token}",
            },
            json={"event_type": "TagBot", "client_payload": payload},
        )
        debug(f"Dispatch response code: {resp.status_code}")

    def handle_release_branch(self, version: str) -> None:
        """Merge an existing release branch or create a PR to merge it."""
        master = self.__repo.default_branch
        branch = f"release-{version[1:]}"
        if not self._fetch_branch(master, branch):
            info(f"Release branch {branch} does not exist")
            return
        if self._can_fast_forward(master, branch):
            info("Release branch can be fast-forwarded")
            self._merge_and_delete_branch(master, branch)
        else:
            info("Release branch cannot be fast-forwarded, creating pull request")
            self._create_release_branch_pr(version, master, branch)

    def changelog(self, version: str) -> Optional[str]:
        """Get the changelog for a new version."""
        return get_changelog(
            name=self._project("name"),
            registry=self.__registry.full_name,
            repo=self.__repo.full_name,
            token=self.__token,
            uuid=self._project("uuid"),
            version=version,
        )

    def create_release(self, version: str, sha: str, changelog: Optional[str]) -> None:
        """Create a GitHub release."""
        if git("rev-parse", "HEAD", repo=self._dir()) == sha:
            target = self.__repo.default_branch
        else:
            target = sha
        info(f"Creating release {version} at {sha} (target {target})")
        self.__repo.create_git_release(
            version, version, changelog or "", target_commitish=target
        )
