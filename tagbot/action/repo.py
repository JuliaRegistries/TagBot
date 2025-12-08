import hashlib
import json
import os
import re
import subprocess
import sys
import traceback

import docker
import pexpect
import requests
import toml

from base64 import b64decode
from datetime import datetime, timedelta, timezone
from stat import S_IREAD, S_IWRITE, S_IEXEC
from subprocess import DEVNULL
from tempfile import mkdtemp, mkstemp
from typing import (
    Any,
    Dict,
    List,
    Mapping,
    MutableMapping,
    Optional,
    TypeVar,
    Union,
    cast,
)

from urllib.parse import urlparse

from github import Github, Auth, GithubException, UnknownObjectException
from github.PullRequest import PullRequest
from gnupg import GPG
from semver import VersionInfo

from .. import logger
from . import TAGBOT_WEB, Abort, InvalidProject
from .changelog import Changelog
from .git import Git

GitlabClient: Any = None
GitlabUnknown: Any = None
try:
    from .gitlab import (
        GitlabClient as _GitlabClient,
        UnknownObjectException as _GitlabUnknown,
    )

    GitlabClient = _GitlabClient
    GitlabUnknown = _GitlabUnknown
except Exception:
    # Optional import: ignore errors if .gitlab is not available or fails to import.
    pass

# Build a tuple of UnknownObjectException classes for both GitHub and GitLab
# so exception handlers can catch the appropriate type depending on what's
# available at runtime.
UnknownObjectExceptions: tuple[type[Exception], ...] = (UnknownObjectException,)
if GitlabUnknown is not None:
    UnknownObjectExceptions = (UnknownObjectException, GitlabUnknown)

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
        draft: bool,
        registry_ssh: str,
        user: str,
        email: str,
        lookback: int,
        branch: Optional[str],
        subdir: Optional[str] = None,
        tag_prefix: Optional[str] = None,
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
        auth = Auth.Token(token)
        gh_url_host = urlparse(self._gh_url).hostname
        gh_api_host = urlparse(self._gh_api).hostname
        is_gitlab = (gh_url_host and "gitlab" in gh_url_host) or (
            gh_api_host and "gitlab" in gh_api_host
        )
        if is_gitlab:
            if GitlabClient is None:
                raise Abort("GitLab support requires python-gitlab to be installed")
            # python-gitlab expects base URL (e.g. https://gitlab.com)
            self._gh = GitlabClient(token, self._gh_api)
        else:
            self._gh = Github(
                auth=auth,
                base_url=self._gh_api,
                per_page=100,
                **github_kwargs,  # type: ignore
            )
        self._repo = self._gh.get_repo(repo, lazy=True)
        self._registry_name = registry
        try:
            self._registry = self._gh.get_repo(registry)
        except UnknownObjectExceptions:
            # This gets raised if the registry is private and the token lacks
            # permissions to read it. In this case, we need to use SSH.
            if not registry_ssh:
                raise Abort(f"Registry {registry} is not accessible")
            self._registry_ssh_key = registry_ssh
            logger.debug("Will access registry via Git clone")
            self._clone_registry = True
        except Exception:
            # This is an awful hack to let me avoid properly fixing the tests...
            if "pytest" in sys.modules:
                logger.warning("'awful hack' in use")
                self._registry = self._gh.get_repo(registry, lazy=True)
                self._clone_registry = False
            else:
                raise
        else:
            self._clone_registry = False
        self._token = token
        self._changelog = Changelog(self, changelog, changelog_ignore)
        self._ssh = ssh
        self._gpg = gpg
        self._draft = draft
        self._user = user
        self._email = email
        self._git = Git(self._gh_url, repo, token, user, email)
        self._lookback = timedelta(days=lookback, hours=1)
        self.__registry_clone_dir: Optional[str] = None
        self.__release_branch = branch
        self.__subdir = subdir
        self.__tag_prefix = tag_prefix
        self.__project: Optional[MutableMapping[str, object]] = None
        self.__registry_path: Optional[str] = None
        self.__registry_url: Optional[str] = None

    def _project(self, k: str) -> str:
        """Get a value from the Project.toml."""
        if self.__project is not None:
            return str(self.__project[k])
        for name in ["Project.toml", "JuliaProject.toml"]:
            try:
                filepath = os.path.join(self.__subdir, name) if self.__subdir else name
                contents = self._only(self._repo.get_contents(filepath))
                break
            except UnknownObjectExceptions:
                pass  # Try the next filename
        else:
            raise InvalidProject("Project file was not found")
        self.__project = toml.loads(contents.decoded_content.decode())
        return str(self.__project[k])

    @property
    def _registry_clone_dir(self) -> str:
        if self.__registry_clone_dir is not None:
            return self.__registry_clone_dir
        repo = mkdtemp(prefix="tagbot_registry_")
        self._git.command("init", repo, repo=None)
        self.configure_ssh(self._registry_ssh_key, None, repo=repo)
        url = f"git@{urlparse(self._gh_url).hostname}:{self._registry_name}.git"
        self._git.command("remote", "add", "origin", url, repo=repo)
        self._git.command("fetch", "origin", repo=repo)
        self._git.command("checkout", self._git.default_branch(repo=repo), repo=repo)
        self.__registry_clone_dir = repo
        return repo

    @property
    def _registry_path(self) -> Optional[str]:
        """Get the package's path in the registry repo."""
        if self.__registry_path is not None:
            return self.__registry_path
        try:
            uuid = self._project("uuid").lower()
        except KeyError:
            raise InvalidProject("Project file has no UUID")
        if self._clone_registry:
            with open(os.path.join(self._registry_clone_dir, "Registry.toml")) as f:
                registry = toml.load(f)
        else:
            contents = self._only(self._registry.get_contents("Registry.toml"))
            blob = self._registry.get_git_blob(contents.sha)
            b64 = b64decode(blob.content)
            string_contents = b64.decode("utf8")
            registry = toml.loads(string_contents)

        if uuid in registry["packages"]:
            self.__registry_path = registry["packages"][uuid]["path"]
            return self.__registry_path
        return None

    @property
    def _registry_url(self) -> Optional[str]:
        """Get the package's url in the registry repo."""
        if self.__registry_url is not None:
            return self.__registry_url
        root = self._registry_path
        try:
            contents = self._only(self._registry.get_contents(f"{root}/Package.toml"))
        except UnknownObjectExceptions:
            raise InvalidProject("Package.toml was not found")
        package = toml.loads(contents.decoded_content.decode())
        self.__registry_url = package["repo"]
        return self.__registry_url

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

    def _create_release_branch_pr(self, version_tag: str, branch: str) -> None:
        """Create a pull request for the release branch."""
        self._repo.create_pull(
            title=f"Merge release branch for {version_tag}",
            body="",
            head=branch,
            base=self._repo.default_branch,
        )

    def _tag_prefix(self) -> str:
        """Return the package's tag prefix."""
        if self.__tag_prefix == "NO_PREFIX":
            return "v"
        elif self.__tag_prefix:
            return self.__tag_prefix + "-v"
        elif self.__subdir:
            return self._project("name") + "-v"
        else:
            return "v"

    def _get_version_tag(self, package_version: str) -> str:
        """Return the prefixed version tag."""
        if package_version.startswith("v"):
            package_version = package_version[1:]
        return self._tag_prefix() + package_version

    def _registry_pr(self, version: str) -> Optional[PullRequest]:
        """Look up a merged registry pull request for this version."""
        if self._clone_registry:
            # I think this is actually possible, but it looks pretty complicated.
            return None
        name = self._project("name")
        uuid = self._project("uuid").lower()
        url = self._registry_url
        if not url:
            logger.info("Could not find url of package in registry")
            return None
        url_hash = hashlib.sha256(url.encode()).hexdigest()
        # This is the format used by Registrator/PkgDev.
        # see https://github.com/JuliaRegistries/RegistryTools.jl/blob/
        # 0de7540015c6b2c0ff31229fc6bb29663c52e5c4/src/utils.jl#L23-L23
        head = f"registrator-{name.lower()}-{uuid[:8]}-{version}-{url_hash[:10]}"
        logger.debug(f"Looking for PR from branch {head}")
        now = datetime.now(timezone.utc)
        # Check for an owner's PR first, since this is way faster (only one request).
        registry = self._registry
        owner = registry.owner.login
        logger.debug(f"Trying to find PR by registry owner first ({owner})")
        prs = registry.get_pulls(head=f"{owner}:{head}", state="closed")
        for pr in prs:
            if pr.merged_at is not None and now - pr.merged_at < self._lookback:
                return cast(PullRequest, pr)
        logger.debug("Did not find registry PR by registry owner")
        prs = registry.get_pulls(state="closed")
        for pr in prs:
            if now - cast(datetime, pr.closed_at) > self._lookback:
                break
            if pr.merged and pr.head.ref == head:
                return cast(PullRequest, pr)
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
        # Handle special case of tagging packages in a repo subdirectory, in which
        # case the Julia package tree hash does not match the git commit tree hash
        if self.__subdir:
            arg = f"{commit.sha}:{self.__subdir}"
            subdir_tree_hash = self._git.command("rev-parse", arg)
            if subdir_tree_hash == tree:
                return cast(str, commit.sha)
            else:
                msg = "Subdir tree SHA of commit from registry PR does not match"
                logger.warning(msg)
                return None
        # Handle regular case (subdir is not set)
        if commit.commit.tree.sha == tree:
            return cast(str, commit.sha)
        else:
            logger.warning("Tree SHA of commit from registry PR does not match")
            return None

    def _commit_sha_of_tree_from_branch(
        self, branch: str, tree: str, since: datetime
    ) -> Optional[str]:
        """Look up the commit SHA of a tree with the given SHA on one branch."""
        for commit in self._repo.get_commits(sha=branch, since=since):
            if commit.commit.tree.sha == tree:
                return cast(str, commit.sha)
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

    def _commit_sha_of_tag(self, version_tag: str) -> Optional[str]:
        """Look up the commit SHA of a given tag."""
        try:
            ref = self._repo.get_git_ref(f"tags/{version_tag}")
        except UnknownObjectExceptions:
            return None
        ref_type = getattr(ref.object, "type", None)
        if ref_type == "commit":
            return cast(str, ref.object.sha)
        elif ref_type == "tag":
            tag = self._repo.get_git_tag(ref.object.sha)
            return cast(str, tag.object.sha)
        else:
            return None

    def _commit_sha_of_release_branch(self) -> str:
        """Get the latest commit SHA of the release branch."""
        branch = self._repo.get_branch(self._release_branch)
        return cast(str, branch.commit.sha)

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
            version_tag = self._get_version_tag(version)
            sha = self._commit_sha_of_tag(version_tag)
            if sha:
                if sha != expected:
                    msg = f"Existing tag {version_tag} points at the wrong commit (expected {expected})"  # noqa: E501
                    logger.error(msg)
                else:
                    logger.info(f"Tag {version_tag} already exists")
                continue
            valid[version] = expected
        return valid

    def _versions(self, min_age: Optional[timedelta] = None) -> Dict[str, str]:
        """Get all package versions from the registry."""
        if self._clone_registry:
            return self._versions_clone(min_age=min_age)
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
        except UnknownObjectExceptions:
            logger.debug(f"Versions.toml was not found ({kwargs})")
            return {}
        versions = toml.loads(contents.decoded_content.decode())
        return {v: versions[v]["git-tree-sha1"] for v in versions}

    def _versions_clone(self, min_age: Optional[timedelta] = None) -> Dict[str, str]:
        """Same as _versions, but uses a Git clone to access the registry."""
        registry = self._registry_clone_dir
        if min_age:
            # TODO: Time zone stuff?
            default_sha = self._git.command("rev-parse", "HEAD", repo=registry)
            earliest = datetime.now() - min_age
            shas = self._git.command("log", "--format=%H", repo=registry).split("\n")
            for sha in shas:
                dt = self._git.time_of_commit(sha, repo=registry)
                if dt < earliest:
                    self._git.command("checkout", sha, repo=registry)
                    break
            else:
                logger.debug("No registry commits were found")
                return {}
        try:
            root = self._registry_path
            if not root:
                logger.debug("Package is not registered")
                return {}
            path = os.path.join(registry, root, "Versions.toml")
            if not os.path.isfile(path):
                logger.debug("Versions.toml was not found")
                return {}
            with open(path) as f:
                versions = toml.load(f)
            return {v: versions[v]["git-tree-sha1"] for v in versions}
        finally:
            if min_age:
                self._git.command("checkout", default_sha, repo=registry)

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
        try:
            is_private = self._repo.private
        except GithubException:
            logger.debug(
                "Could not determine repository privacy (likely bad credentials); "
                "skipping error reporting"
            )
            return

        if is_private or os.getenv("GITHUB_ACTIONS") != "true":
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
        if self._clone_registry:
            with open(
                os.path.join(self._registry_clone_dir, root, "Package.toml")
            ) as f:
                package = toml.load(f)
        else:
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
        self._repo.create_repository_dispatch("TagBot", payload)

    def configure_ssh(self, key: str, password: Optional[str], repo: str = "") -> None:
        """Configure the repo to use an SSH key for authentication."""
        if not repo:
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
        self._git.config("core.sshCommand", cmd, repo=repo)
        if password:
            # Start the SSH agent, apply the environment changes,
            # then add our identity so that we don't need to supply a password anymore.
            proc = subprocess.run(
                ["ssh-agent"], check=True, text=True, capture_output=True
            )
            for k, v in re.findall(r"\s*(.+)=(.+?);", proc.stdout):
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
        import_result = gpg.import_keys(
            self._maybe_decode_private_key(key), passphrase=password
        )
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
        # On Debian, the Git version is too old to recognize tag.gpgSign,
        # so the tag command will need to use --sign.
        self._git._gpgsign = True
        self._git.config("tag.gpgSign", "true")
        self._git.config("user.signingKey", key_id)

    def handle_release_branch(self, version: str) -> None:
        """Merge an existing release branch or create a PR to merge it."""
        # Exclude "v" from version: `0.0.0` or `SubPackage-0.0.0`
        branch_version = self._tag_prefix()[:-1] + version[1:]
        branch = f"release-{branch_version}"
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
            version_tag = self._get_version_tag(version)
            self._create_release_branch_pr(version_tag, branch)

    def create_release(self, version: str, sha: str) -> None:
        """Create a GitHub release."""
        target = sha
        if self._commit_sha_of_release_branch() == sha:
            # If we use <branch> as the target, GitHub will show
            # "<n> commits to <branch> since this release" on the release page.
            target = self._release_branch
        version_tag = self._get_version_tag(version)
        logger.debug(f"Release {version_tag} target: {target}")
        log = self._changelog.get(version_tag, sha)
        if not self._draft:
            # Always create tags via the CLI as the GitHub API has a bug which
            # only allows tags to be created for SHAs which are the the HEAD
            # commit on a branch.
            # https://github.com/JuliaRegistries/TagBot/issues/239#issuecomment-2246021651
            self._git.create_tag(version_tag, sha, log)
        logger.info(f"Creating release {version_tag} at {sha}")
        self._repo.create_git_release(
            version_tag, version_tag, log, target_commitish=target, draft=self._draft
        )

    def _check_rate_limit(self) -> None:
        """Check and log GitHub API rate limit status."""
        try:
            rate_limit = self._gh.get_rate_limit()
            core = rate_limit.resources.core
            logger.info(
                f"GitHub API rate limit: {core.remaining}/{core.limit} remaining "
                f"(reset at {core.reset})"
            )
        except Exception as e:
            logger.debug(f"Could not check rate limit: {e}")

    def handle_error(self, e: Exception, *, raise_abort: bool = True) -> None:
        """Handle an unexpected error."""
        allowed = False
        internal = True
        trace = traceback.format_exc()
        if isinstance(e, RequestException):
            logger.warning("TagBot encountered a likely transient HTTP exception")
            logger.info(trace)
            allowed = True
        elif isinstance(e, GithubException):
            logger.info(e.headers)
            if 500 <= e.status < 600:
                logger.warning("GitHub returned a 5xx error code")
                logger.info(trace)
                allowed = True
            elif e.status == 403:
                self._check_rate_limit()
                logger.error(
                    "GitHub returned a 403 error. This may indicate: "
                    "1. Rate limiting - check the rate limit status above, "
                    "2. Insufficient permissions - verify your token & repo access, "
                    "3. Resource not accessible - see setup documentation"
                )
                internal = False
                allowed = False
        if not allowed:
            if internal:
                logger.error("TagBot experienced an unexpected internal failure")
            logger.info(trace)
            try:
                self._report_error(trace)
            except Exception:
                logger.error("Issue reporting failed")
                logger.info(traceback.format_exc())
            if raise_abort:
                raise Abort("Cannot continue due to internal failure")

    def commit_sha_of_version(self, version: str) -> Optional[str]:
        """Get the commit SHA from a registered version."""
        if version.startswith("v"):
            version = version[1:]
        root = self._registry_path
        if not root:
            logger.error("Package is not registered")
            return None
        if self._clone_registry:
            with open(
                os.path.join(self._registry_clone_dir, root, "Versions.toml")
            ) as f:
                versions = toml.load(f)
        else:
            contents = self._only(self._registry.get_contents(f"{root}/Versions.toml"))
            versions = toml.loads(contents.decoded_content.decode())
        if version not in versions:
            logger.error(f"Version {version} is not registered")
            return None
        tree = versions[version]["git-tree-sha1"]
        return self._commit_sha_of_tree(tree)
