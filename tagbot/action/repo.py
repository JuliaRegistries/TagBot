import json
import os
import re
import subprocess
import traceback

import docker
import pexpect
import requests
import toml

from base64 import b64decode
from datetime import datetime, timedelta
from stat import S_IREAD, S_IWRITE, S_IEXEC
from subprocess import DEVNULL
from tempfile import mkdtemp, mkstemp
from typing import Dict, List, Mapping, MutableMapping, Optional, TypeVar, Union, cast
from urllib.parse import urlparse

from github import Github, GithubException, InputGitAuthor, UnknownObjectException
from github.PullRequest import PullRequest
from gnupg import GPG
from semver import VersionInfo

from .. import logger
from . import TAGBOT_WEB, Abort, InvalidProject
from .changelog import Changelog
from .git import Git

RequestException = requests.RequestException
T = TypeVar("T")


class Repo:
    """A Repo has access to its Git repository and registry metadata."""

    def __init__(
        self,
        *,
        repo: str,
        registry: str,
        github: str,
        github_api: str,
        token: str,
        changelog: str,
        changelog_ignore: List[str],
        ssh: bool,
        gpg: bool,
        user: str,
        email: str,
        lookback: int,
        branch: Optional[str],
        github_kwargs: Optional[Dict[str, object]] = None,
    ) -> None:
        if github_kwargs is None:
            github_kwargs = {}
        if not urlparse(github).scheme:
            github = f"https://{github}"
        if not urlparse(github_api).scheme:
            github_api = f"https://{github_api}"
        self._gh_url = github
        self._gh_api = github_api
        self._gh = Github(
            token, base_url=self._gh_api, per_page=100, **github_kwargs  # type: ignore
        )
        self._repo = self._gh.get_repo(repo, lazy=True)
        self._registry = self._gh.get_repo(registry, lazy=True)
        self._token = token
        self._changelog = Changelog(self, changelog, changelog_ignore)
        self._ssh = ssh
        self._gpg = gpg
        self._user = user
        self._email = email
        self._git = Git(self._gh_url, repo, token, user, email)
        self._lookback = timedelta(days=lookback, hours=1)
        self.__release_branch = branch
        self.__project: Optional[MutableMapping[str, object]] = None
        self.__registry_path: Optional[str] = None

    def _project(self, k: str) -> str:
        """Get a value from the Project.toml."""
        if self.__project is not None:
            return str(self.__project[k])
        for name in ["Project.toml", "JuliaProject.toml"]:
            try:
                contents = self._only(self._repo.get_contents(name))
                break
            except UnknownObjectException:
                pass
        else:
            raise InvalidProject("Project file was not found")
        self.__project = toml.loads(contents.decoded_content.decode())
        return str(self.__project[k])

    @property
    def _registry_path(self) -> Optional[str]:
        """Get the package's path in the registry repo."""
        if self.__registry_path is not None:
            return self.__registry_path
        contents = self._only(self._registry.get_contents("Registry.toml"))
        registry = toml.loads(contents.decoded_content.decode())
        try:
            uuid = self._project("uuid")
        except KeyError:
            raise InvalidProject("Project file has no UUID")
        if uuid in registry["packages"]:
            self.__registry_path = registry["packages"][uuid]["path"]
            return self.__registry_path
        return None

    @property
    def _release_branch(self) -> str:
        """Get the name of the release branch."""
        return self.__release_branch or self._repo.default_branch

    def _only(self, val: Union[T, List[T]]) -> T:
        """Get the first element of a list or the thing itself if it's not a list."""
        return val[0] if isinstance(val, list) else val

    def _maybe_decode_private_key(self, key: str) -> str:
        """Return a decoded value if it is Base64-encoded, or the original value."""
        return key if "PRIVATE KEY" in key else b64decode(key).decode()

    def _create_release_branch_pr(self, version: str, branch: str) -> None:
        """Create a pull request for the release branch."""
        self._repo.create_pull(
            title=f"Merge release branch for {version}",
            body="",
            head=branch,
            base=self._repo.default_branch,
        )

    def _registry_pr(self, version: str) -> Optional[PullRequest]:
        """Look up a merged registry pull request for this version."""
        name = self._project("name")
        uuid = self._project("uuid")
        # This is the format used by Registrator/PkgDev.
        head = f"registrator/{name.lower()}/{uuid[:8]}/{version}"
        logger.debug(f"Looking for PR from branch {head}")
        now = datetime.now()
        # Check for an owner's PR first, since this is way faster (only one request).
        registry = self._registry
        owner = registry.owner.login
        logger.debug(f"Trying to find PR by registry owner first ({owner})")
        prs = registry.get_pulls(head=f"{owner}:{head}", state="closed")
        for pr in prs:
            if pr.merged and now - pr.merged_at < self._lookback:
                return pr
        logger.debug("Did not find registry PR by registry owner")
        prs = registry.get_pulls(state="closed")
        for pr in prs:
            if now - cast(datetime, pr.closed_at) > self._lookback:
                break
            if pr.merged and pr.head.ref == head:
                return pr
        return None

    def _commit_sha_from_registry_pr(self, version: str, tree: str) -> Optional[str]:
        """Look up the commit SHA of version from its registry PR."""
        pr = self._registry_pr(version)
        if not pr:
            logger.info("Did not find registry PR")
            return None
        m = re.search("- Commit: ([a-f0-9]{32})", pr.body)
        if not m:
            logger.info("Registry PR body did not match")
            return None
        commit = self._repo.get_commit(m[1])
        if commit.commit.tree.sha == tree:
            return commit.sha
        else:
            logger.warning("Tree SHA of commit from registry PR does not match")
            return None

    def _commit_sha_of_tree_from_branch(
        self, branch: str, tree: str, since: datetime
    ) -> Optional[str]:
        """Look up the commit SHA of a tree with the given SHA on one branch."""
        for commit in self._repo.get_commits(sha=branch, since=since):
            if commit.commit.tree.sha == tree:
                return commit.sha
        return None

    def _commit_sha_of_tree(self, tree: str) -> Optional[str]:
        """Look up the commit SHA of a tree with the given SHA."""
        since = datetime.now() - self._lookback
        sha = self._commit_sha_of_tree_from_branch(self._release_branch, tree, since)
        if sha:
            return sha
        for branch in self._repo.get_branches():
            if branch.name == self._release_branch:
                continue
            sha = self._commit_sha_of_tree_from_branch(branch.name, tree, since)
            if sha:
                return sha
        # For a valid tree SHA, the only time that we reach here is when a release
        # has been made long after the commit was made, which is reasonably rare.
        # Fall back to cloning the repo in that case.
        return self._git.commit_sha_of_tree(tree)

    def _commit_sha_of_tag(self, version: str) -> Optional[str]:
        """Look up the commit SHA of a given tag."""
        try:
            ref = self._repo.get_git_ref(f"tags/{version}")
        except UnknownObjectException:
            return None
        ref_type = getattr(ref.object, "type", None)
        if ref_type == "commit":
            return ref.object.sha
        elif ref_type == "tag":
            tag = self._repo.get_git_tag(ref.object.sha)
            return tag.object.sha
        else:
            return None

    def _commit_sha_of_release_branch(self) -> str:
        """Get the latest commit SHA of the release branch."""
        branch = self._repo.get_branch(self._release_branch)
        return branch.commit.sha

    def _filter_map_versions(self, versions: Dict[str, str]) -> Dict[str, str]:
        """Filter out versions and convert tree SHA to commit SHA."""
        valid = {}
        for version, tree in versions.items():
            version = f"v{version}"
            expected = self._commit_sha_from_registry_pr(version, tree)
            if not expected:
                expected = self._commit_sha_of_tree(tree)
            if not expected:
                logger.warning(
                    f"No matching commit was found for version {version} ({tree})"
                )
                continue
            sha = self._commit_sha_of_tag(version)
            if sha:
                if sha != expected:
                    msg = f"Existing tag {version} points at the wrong commit (expected {expected})"  # noqa: E501
                    logger.error(msg)
                else:
                    logger.info(f"Tag {version} already exists")
                continue
            valid[version] = expected
        return valid

    def _versions(self, min_age: Optional[timedelta] = None) -> Dict[str, str]:
        """Get all package versions from the registry."""
        root = self._registry_path
        if not root:
            logger.debug("Package is not registered")
            return {}
        kwargs = {}
        if min_age:
            # Get the most recent commit from before min_age.
            until = datetime.now() - min_age
            commits = self._registry.get_commits(until=until)
            # Get the first value like this because the iterator has no `next` method.
            for commit in commits:
                kwargs["ref"] = commit.commit.sha
                break
            else:
                logger.debug("No registry commits were found")
                return {}
        try:
            contents = self._only(
                self._registry.get_contents(f"{root}/Versions.toml", **kwargs)
            )
        except UnknownObjectException:
            logger.debug(f"Versions.toml was not found ({kwargs})")
            return {}
        versions = toml.loads(contents.decoded_content.decode())
        return {v: versions[v]["git-tree-sha1"] for v in versions}

    def _pr_exists(self, branch: str) -> bool:
        """Check whether a PR exists for a given branch."""
        owner = self._repo.owner.login
        for pr in self._repo.get_pulls(head=f"{owner}:{branch}"):
            return True
        return False

    def _run_url(self) -> str:
        """Get the URL of this Actions run."""
        url = f"{self._repo.html_url}/actions"
        run = os.getenv("GITHUB_RUN_ID")
        if run:
            url += f"/runs/{run}"
        return url

    def _image_id(self) -> str:
        """Get the Docker image ID."""
        host = os.getenv("HOSTNAME", "")
        if not host:
            logger.warning("HOSTNAME is not set")
            return "Unknown"
        client = docker.from_env()
        container = client.containers.get(host)
        return container.image.id

    def _report_error(self, trace: str) -> None:
        """Report an error."""
        if self._repo.private or os.getenv("GITHUB_ACTIONS") != "true":
            logger.debug("Not reporting")
            return
        logger.debug("Reporting error")
        data = {
            "image": self._image_id(),
            "repo": self._repo.full_name,
            "run": self._run_url(),
            "stacktrace": trace,
        }
        resp = requests.post(f"{TAGBOT_WEB}/report", json=data)
        output = json.dumps(resp.json(), indent=2)
        logger.info(f"Response ({resp.status_code}): {output}")

    def is_registered(self) -> bool:
        """Check whether or not the repository belongs to a registered package."""
        try:
            root = self._registry_path
        except InvalidProject as e:
            logger.debug(e.message)
            return False
        if not root:
            return False
        contents = self._only(self._registry.get_contents(f"{root}/Package.toml"))
        package = toml.loads(contents.decoded_content.decode())
        gh = cast(str, urlparse(self._gh_url).hostname).replace(".", r"\.")
        if "@" in package["repo"]:
            pattern = rf"{gh}:(.*?)(?:\.git)?$"
        else:
            pattern = rf"{gh}/(.*?)(?:\.git)?$"
        m = re.search(pattern, package["repo"])
        if not m:
            return False
        # I'm not really sure why mypy doesn't like this line without the cast.
        return cast(bool, m[1].casefold() == self._repo.full_name.casefold())

    def new_versions(self) -> Dict[str, str]:
        """Get all new versions of the package."""
        current = self._versions()
        logger.debug(f"There are {len(current)} total versions")
        old = self._versions(min_age=self._lookback)
        logger.debug(f"There are {len(current) - len(old)} new versions")
        # Make sure to insert items in SemVer order.
        versions = {}
        for v in sorted(current.keys(), key=VersionInfo.parse):
            if v not in old:
                versions[v] = current[v]
        return self._filter_map_versions(versions)

    def create_dispatch_event(self, payload: Mapping[str, object]) -> None:
        """Create a repository dispatch event."""
        # TODO: Remove the comment when PyGithub#1502 is published.
        self._repo.create_repository_dispatch("TagBot", payload)  # type: ignore

    def configure_ssh(self, key: str, password: Optional[str]) -> None:
        """Configure the repo to use an SSH key for authentication."""
        self._git.set_remote_url(self._repo.ssh_url)
        _, priv = mkstemp(prefix="tagbot_key_")
        with open(priv, "w") as f:
            # SSH keys must end with a single newline.
            f.write(self._maybe_decode_private_key(key).strip() + "\n")
        os.chmod(priv, S_IREAD)
        # Add the host key to a known hosts file
        # so that we don't have to confirm anything when we try to push.
        _, hosts = mkstemp(prefix="tagbot_hosts_")
        host = cast(str, urlparse(self._gh_url).hostname)
        with open(hosts, "w") as f:
            subprocess.run(
                ["ssh-keyscan", "-t", "rsa", host],
                check=True,
                stdout=f,
                stderr=DEVNULL,
            )
        cmd = f"ssh -i {priv} -o UserKnownHostsFile={hosts}"
        logger.debug(f"SSH command: {cmd}")
        self._git.config("core.sshCommand", cmd)
        if password:
            # Start the SSH agent, apply the environment changes,
            # then add our identity so that we don't need to supply a password anymore.
            proc = subprocess.run(
                ["ssh-agent"], check=True, text=True, capture_output=True
            )
            for (k, v) in re.findall(r"\s*(.+)=(.+?);", proc.stdout):
                logger.debug(f"Setting environment variable {k}={v}")
                os.environ[k] = v
            child = pexpect.spawn(f"ssh-add {priv}")
            child.expect("Enter passphrase")
            child.sendline(password)
            child.expect("Identity added")

    def configure_gpg(self, key: str, password: Optional[str]) -> None:
        """Configure the repo to sign tags with GPG."""
        home = os.environ["GNUPGHOME"] = mkdtemp(prefix="tagbot_gpg_")
        os.chmod(home, S_IREAD | S_IWRITE | S_IEXEC)
        logger.debug(f"Set GNUPGHOME to {home}")
        gpg = GPG(gnupghome=home, use_agent=True)
        # For some reason, this doesn't require the password even though the CLI does.
        import_result = gpg.import_keys(self._maybe_decode_private_key(key))
        if import_result.sec_imported != 1:
            logger.warning(import_result.stderr)
            raise Abort("Importing key failed")
        key_id = import_result.fingerprints[0]
        logger.debug(f"GPG key ID: {key_id}")
        if password:
            # Sign some dummy data to put our password into the GPG agent,
            # so that we don't need to supply the password when we create a tag.
            sign_result = gpg.sign("test", passphrase=password)
            if sign_result.status != "signature created":
                logger.warning(sign_result.stderr)
                raise Abort("Testing GPG key failed")
        self._git.config("user.signingKey", key_id)
        self._git.config("tag.gpgSign", "true")

    def handle_release_branch(self, version: str) -> None:
        """Merge an existing release branch or create a PR to merge it."""
        branch = f"release-{version[1:]}"
        if not self._git.fetch_branch(branch):
            logger.info(f"Release branch {branch} does not exist")
        elif self._git.is_merged(branch):
            logger.info(f"Release branch {branch} is already merged")
        elif self._git.can_fast_forward(branch):
            logger.info("Release branch can be fast-forwarded")
            self._git.merge_and_delete_branch(branch)
        elif self._pr_exists(branch):
            logger.info("Release branch already has a PR")
        else:
            logger.info(
                "Release branch cannot be fast-forwarded, creating pull request"
            )
            self._create_release_branch_pr(version, branch)

    def create_release(self, version: str, sha: str) -> None:
        """Create a GitHub release."""
        target = sha
        if self._commit_sha_of_release_branch() == sha:
            # If we use <branch> as the target, GitHub will show
            # "<n> commits to <branch> since this release" on the release page.
            target = self._release_branch
        logger.debug(f"Release {version} target: {target}")
        log = self._changelog.get(version, sha)
        if self._ssh or self._gpg:
            logger.debug("Creating tag via Git CLI")
            self._git.create_tag(version, sha, log)
        else:
            logger.debug("Creating tag via GitHub API")
            tag = self._repo.create_git_tag(
                version,
                log,
                sha,
                "commit",
                tagger=InputGitAuthor(self._user, self._email),
            )
            self._repo.create_git_ref(f"refs/tags/{version}", tag.sha)
        logger.info(f"Creating release {version} at {sha}")
        self._repo.create_git_release(version, version, log, target_commitish=target)

    def handle_error(self, e: Exception) -> None:
        """Handle an unexpected error."""
        allowed = False
        trace = traceback.format_exc()
        if isinstance(e, RequestException):
            logger.warning("TagBot encountered a likely transient HTTP exception")
            logger.info(trace)
            allowed = True
        elif isinstance(e, GithubException):
            if 500 <= e.status < 600:
                logger.warning("GitHub returned a 5xx error code")
                logger.info(trace)
                allowed = True
        if not allowed:
            logger.error("TagBot experienced an unexpected internal failure")
            logger.info(trace)
            try:
                self._report_error(trace)
            except Exception:
                logger.error("Issue reporting failed")
                logger.info(traceback.format_exc())

    def commit_sha_of_version(self, version: str) -> Optional[str]:
        """Get the commit SHA from a registered version."""
        if version.startswith("v"):
            version = version[1:]
        root = self._registry_path
        if not root:
            logger.error("Package is not registered")
            return None
        contents = self._only(self._registry.get_contents(f"{root}/Versions.toml"))
        versions = toml.loads(contents.decoded_content.decode())
        if version not in versions:
            logger.error(f"Version {version} is not registered")
            return None
        tree = versions[version]["git-tree-sha1"]
        return self._commit_sha_of_tree(tree)
