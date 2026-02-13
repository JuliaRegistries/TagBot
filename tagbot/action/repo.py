import hashlib
import json
import os
import re
import subprocess
import sys
import time
import traceback

from importlib.metadata import version as pkg_version, PackageNotFoundError

import docker
import pexpect
import requests
import toml

from base64 import b64decode
from datetime import datetime, timedelta
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
    Tuple,
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
from .git import Git, parse_git_datetime

GitlabClient: Any = None
GitlabUnknown: Any = None
try:
    from .gitlab import (
        GitlabClient as _GitlabClient,
        UnknownObjectException as _GitlabUnknown,
    )

    GitlabClient = _GitlabClient
    GitlabUnknown = _GitlabUnknown
except ImportError:
    # Optional import: ignore import errors if .gitlab is not available.
    pass

# Build a tuple of UnknownObjectException classes for both GitHub and GitLab
# so exception handlers can catch the appropriate type depending on what's
# available at runtime.
UnknownObjectExceptions: tuple[type[Exception], ...] = (UnknownObjectException,)
if GitlabUnknown is not None:
    UnknownObjectExceptions = (UnknownObjectException, GitlabUnknown)

RequestException = requests.RequestException

# Maximum number of PRs to check when looking for registry PR
# This prevents excessive API calls on large registries
MAX_PRS_TO_CHECK = int(os.getenv("TAGBOT_MAX_PRS_TO_CHECK", "300"))


class _PerformanceMetrics:
    """Track performance metrics for API calls and processing."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Reset all metrics to initial state."""
        self.api_calls = 0
        self.start_time = time.time()
        self.prs_checked = 0
        self.versions_checked = 0

    def log_summary(self) -> None:
        """Log performance summary."""
        elapsed = time.time() - self.start_time
        logger.info(
            f"Performance: {self.api_calls} API calls, "
            f"{self.prs_checked} PRs checked, "
            f"{self.versions_checked} versions processed, "
            f"{elapsed:.2f}s elapsed"
        )


_metrics = _PerformanceMetrics()


def _get_tagbot_version() -> str:
    """Get the TagBot version."""
    try:
        return pkg_version("tagbot")
    except PackageNotFoundError:
        return "Unknown"


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
        changelog_format: str,
        ssh: bool,
        gpg: bool,
        draft: bool,
        registry_ssh: str,
        user: str,
        email: str,
        branch: Optional[str],
        subdir: Optional[str] = None,
        lookback: Optional[int] = None,
        tag_prefix: Optional[str] = None,
        github_kwargs: Optional[Dict[str, object]] = None,
    ) -> None:
        if github_kwargs is None:
            github_kwargs = {}
        if lookback is not None:
            logger.warning(
                "The 'lookback' parameter is deprecated and no longer has any effect. "
                "TagBot now checks all releases every time to support backfilling. "
                "You can safely remove this parameter from your configuration."
            )
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
        except (GithubException, RequestException) as exc:
            # This is an awful hack to let me avoid properly fixing the tests...
            if "pytest" in sys.modules:
                logger.warning("'awful hack' in use", exc_info=exc)
                self._registry = self._gh.get_repo(registry, lazy=True)
                self._clone_registry = False
            else:
                raise
        else:
            self._clone_registry = False
        self._token = token
        self.__versions_toml_cache: Optional[Dict[str, Any]] = None
        self._changelog_format = changelog_format
        # Only initialize Changelog if using custom format
        self._changelog = (
            None
            if changelog_format in ["github", "conventional"]
            else Changelog(self, changelog, changelog_ignore)
        )
        self._ssh = ssh
        self._gpg = gpg
        self._draft = draft
        self._user = user
        self._email = email
        self._git = Git(self._gh_url, repo, token, user, email)
        self.__registry_clone_dir: Optional[str] = None
        self.__release_branch = branch
        self.__subdir = subdir
        self.__tag_prefix = tag_prefix
        self.__project: Optional[MutableMapping[str, object]] = None
        self.__registry_path: Optional[str] = None
        self.__registry_url: Optional[str] = None
        # Cache for registry PRs to avoid re-fetching for each version
        self.__registry_prs_cache: Optional[Dict[str, PullRequest]] = None
        # Cache for commit datetimes to avoid redundant API calls
        self.__commit_datetimes: Dict[str, datetime] = {}
        # Cache for existing tags to avoid per-version API calls
        self.__existing_tags_cache: Optional[Dict[str, str]] = None
        # Cache for tree SHA → commit SHA mapping (for non-PR registries)
        self.__tree_to_commit_cache: Optional[Dict[str, str]] = None
        # Track manual intervention issue URL for error reporting
        self._manual_intervention_issue_url: Optional[str] = None

    def _sanitize(self, text: str) -> str:
        """Remove sensitive tokens from text."""
        if self._token:
            text = text.replace(self._token, "***")
        return text

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
        try:
            self.__project = toml.loads(contents.decoded_content.decode())
        except toml.TomlDecodeError as e:
            raise InvalidProject(f"Failed to parse Project.toml: {e}")
        except UnicodeDecodeError as e:
            raise InvalidProject(f"Failed to parse Project.toml (encoding error): {e}")
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
        try:
            if self._clone_registry:
                with open(os.path.join(self._registry_clone_dir, "Registry.toml")) as f:
                    registry = toml.load(f)
            else:
                contents = self._only(self._registry.get_contents("Registry.toml"))
                blob = self._registry.get_git_blob(contents.sha)
                b64 = b64decode(blob.content)
                string_contents = b64.decode("utf8")
                registry = toml.loads(string_contents)
        except toml.TomlDecodeError as e:
            logger.warning(
                f"Failed to parse Registry.toml (malformed TOML): {e}. "
                "This may indicate a structural issue with the registry file."
            )
            return None
        except (UnicodeDecodeError, OSError) as e:
            logger.warning(
                f"Failed to parse Registry.toml ({type(e).__name__}): {e}. "
                "This may indicate a temporary issue with the registry file."
            )
            return None

        if "packages" not in registry:
            logger.warning(
                "Registry.toml is missing the 'packages' key. "
                "This may indicate a structural issue with the registry file."
            )
            return None
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
        try:
            package = toml.loads(contents.decoded_content.decode())
        except toml.TomlDecodeError as e:
            raise InvalidProject(f"Failed to parse Package.toml: {e}")
        except UnicodeDecodeError as e:
            raise InvalidProject(f"Failed to parse Package.toml (encoding error): {e}")
        try:
            self.__registry_url = package["repo"]
        except KeyError:
            raise InvalidProject("Package.toml is missing the 'repo' key")
        return self.__registry_url

    def _release_branch(self, version: str) -> str:
        """Get the name of the release branch for a specific version.

        Priority:
        1. Branch specified by Registrator invocation (from PR body)
        2. Release branch specified in TagBot config
        3. Default branch
        """
        # First check if Registrator specified a branch for this version
        try:
            pr_branch = self._branch_from_registry_pr(version)
        except Exception as e:
            logger.debug(f"Skipping registry PR branch lookup: {e}")
            pr_branch = None
        if pr_branch:
            return pr_branch
        # Fall back to config branch or default
        return self.__release_branch or self._repo.default_branch

    def _only(self, val: Union[T, List[T]]) -> T:
        """Get the first element of a list or the thing itself if it's not a list."""
        return val[0] if isinstance(val, list) else val

    def _maybe_decode_private_key(self, key: str) -> str:
        """Return a decoded value if it is Base64-encoded, or the original value."""
        key = key.strip()
        if "PRIVATE KEY" in key:
            return key
        try:
            return b64decode(key).decode()
        except Exception as e:
            raise ValueError(
                "SSH key does not appear to be a valid private key. "
                "Expected either a PEM-formatted key (starting with "
                "'-----BEGIN ... PRIVATE KEY-----') or a valid Base64-encoded key. "
                f"Decoding error: {e}"
            ) from e

    def _validate_ssh_key(self, key: str) -> None:
        """Warn if the SSH key appears to be invalid."""
        key = key.strip()
        if not key:
            logger.warning("SSH key is empty")
            return
        # Check for common SSH private key markers
        valid_markers = [
            "-----BEGIN OPENSSH PRIVATE KEY-----",
            "-----BEGIN RSA PRIVATE KEY-----",
            "-----BEGIN DSA PRIVATE KEY-----",
            "-----BEGIN EC PRIVATE KEY-----",
            "-----BEGIN PRIVATE KEY-----",
        ]
        if not any(marker in key for marker in valid_markers):
            logger.warning(
                "SSH key does not appear to be a valid private key. "
                "Expected a key starting with '-----BEGIN ... PRIVATE KEY-----'. "
                "Make sure you're using the private key, not the public key."
            )

    def _test_ssh_connection(self, ssh_cmd: str, host: str) -> None:
        """Test SSH authentication and warn if it fails."""
        try:
            # ssh -T returns exit code 1 even on success (no shell access),
            # but outputs "successfully authenticated" on success
            proc = subprocess.run(
                ssh_cmd.split() + ["-T", f"git@{host}"],
                text=True,
                capture_output=True,
                timeout=30,
            )
            output = proc.stdout + proc.stderr
            if "successfully authenticated" in output.lower():
                logger.info("SSH key authentication successful")
            elif "permission denied" in output.lower():
                logger.warning(
                    "SSH key authentication failed: Permission denied. "
                    "Verify the deploy key is added to the repository "
                    "and has write access."
                )
            else:
                logger.debug(f"SSH test output: {output}")
        except subprocess.TimeoutExpired:
            logger.warning("SSH connection test timed out")
        except Exception as e:
            logger.debug(f"SSH connection test failed: {e}")

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

    def _build_registry_prs_cache(self) -> Dict[str, PullRequest]:
        """Build a cache of registry PRs indexed by head branch name.

        This fetches closed PRs once and caches them, avoiding repeated API calls
        when checking multiple versions. Uses pagination to fetch PRs in batches.
        """
        if self.__registry_prs_cache is not None:
            return self.__registry_prs_cache

        logger.debug(
            f"Building registry PR cache (fetching up to {MAX_PRS_TO_CHECK} PRs)"
        )
        cache: Dict[str, PullRequest] = {}
        registry = self._registry

        # Fetch PRs with explicit pagination using per_page parameter
        # PyGithub handles pagination automatically, but we limit total PRs checked
        _metrics.api_calls += 1
        prs = registry.get_pulls(state="closed", sort="updated", direction="desc")

        prs_fetched = 0
        for pr in prs:
            _metrics.prs_checked += 1
            prs_fetched += 1
            if prs_fetched >= MAX_PRS_TO_CHECK:
                logger.info(
                    f"PR cache built with {len(cache)} merged PRs "
                    f"(stopped at {MAX_PRS_TO_CHECK} PR limit)"
                )
                break
            # Only cache merged PRs (not closed without merging)
            if pr.merged:
                cache[pr.head.ref] = cast(PullRequest, pr)

        if prs_fetched < MAX_PRS_TO_CHECK:
            logger.debug(
                f"PR cache built with {len(cache)} merged PRs (all PRs checked)"
            )

        self.__registry_prs_cache = cache
        return cache

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

        # Use the cached PR lookup - fetches once and reuses for all versions.
        # This is much faster than per-version owner lookups.
        pr_cache = self._build_registry_prs_cache()
        if head in pr_cache:
            pr = pr_cache[head]
            logger.debug(f"Found registry PR #{pr.number} in cache")
            return pr

        logger.debug(f"Did not find registry PR for branch {head}")
        return None

    def _branch_from_registry_pr(self, version: str) -> Optional[str]:
        """Extract release branch name from registry PR body.

        Registrator includes branch info in PR body like:
        - Branch: my-branch
        """
        pr = self._registry_pr(version)
        if not pr:
            return None
        if not pr.body:
            return None
        # Look for "- Branch: <branch_name>" in PR body (Registrator format)
        m = re.search(r"^-\s*Branch:\s*(.+)$", pr.body, re.MULTILINE)
        if m:
            branch = m[1].strip()
            logger.debug(f"Found branch '{branch}' in registry PR for {version}")
            return branch
        return None

    def _commit_sha_from_registry_pr(self, version: str, tree: str) -> Optional[str]:
        """Look up the commit SHA of version from its registry PR."""
        pr = self._registry_pr(version)
        if not pr:
            logger.info("Did not find registry PR")
            return None
        if pr.body is None:
            logger.info("Registry PR body is empty")
            return None
        m = re.search("- Commit: ([a-f0-9]{32})", pr.body)
        if not m:
            logger.info("Registry PR body did not match")
            return None
        commit = self._repo.get_commit(m[1])
        # Handle special case of tagging packages in a repo subdirectory, in which
        # case the Julia package tree hash does not match the git commit tree hash
        if self.__subdir:
            subdir_tree_hash = self._subdir_tree_hash(commit.sha, suppress_abort=False)
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

    def _build_tree_to_commit_cache(self) -> Dict[str, str]:
        """Build a cache mapping tree SHAs to commit SHAs.

        Uses git log to get all commit:tree pairs in one command,
        enabling O(1) lookups instead of iterating through commits.
        """
        if self.__tree_to_commit_cache is not None:
            return self.__tree_to_commit_cache

        logger.debug("Building tree→commit cache")
        cache: Dict[str, str] = {}
        try:
            # Get all commit:tree pairs in one git command
            output = self._git.command("log", "--all", "--format=%H %T")
            for line in output.splitlines():
                parts = line.split()
                if len(parts) == 2:
                    commit_sha, tree_sha = parts
                    # Only keep first occurrence (most recent commit for that tree)
                    if tree_sha not in cache:
                        cache[tree_sha] = commit_sha
            logger.debug(f"Tree→commit cache built with {len(cache)} entries")
        except Exception as e:
            logger.warning(f"Failed to build tree→commit cache: {e}")

        self.__tree_to_commit_cache = cache
        return cache

    def _commit_sha_of_tree(self, tree: str) -> Optional[str]:
        """Look up the commit SHA of a tree with the given SHA."""
        # Fast path: use pre-built tree→commit cache (built from git log)
        # This is O(1) vs O(branches * commits) for the API-based approach
        if not self.__subdir:
            tree_cache = self._build_tree_to_commit_cache()
            if tree in tree_cache:
                return tree_cache[tree]
            # Tree not found in any commit
            return None

        # For subdirectories, we need to check the subdirectory tree hash.
        # Build a cache of subdir tree hashes from commits.
        if self.__tree_to_commit_cache is None:
            logger.debug("Building subdir tree→commit cache")
            subdir_cache: Dict[str, str] = {}
            for line in self._git.command("log", "--all", "--format=%H").splitlines():
                subdir_tree_hash = self._subdir_tree_hash(line, suppress_abort=True)
                if subdir_tree_hash and subdir_tree_hash not in subdir_cache:
                    subdir_cache[subdir_tree_hash] = line
            logger.debug(
                f"Subdir tree→commit cache built with {len(subdir_cache)} entries"
            )
            self.__tree_to_commit_cache = subdir_cache

        return self.__tree_to_commit_cache.get(tree)

    def _subdir_tree_hash(
        self, commit_sha: str, *, suppress_abort: bool
    ) -> Optional[str]:
        """Return subdir tree hash for a commit; optionally suppress Abort."""
        if not self.__subdir:
            return None
        arg = f"{commit_sha}:{self.__subdir}"
        try:
            return self._git.command("rev-parse", arg)
        except Abort:
            if suppress_abort:
                logger.debug("rev-parse failed while inspecting %s", arg)
                return None
            raise

    def _build_tags_cache(self, retries: int = 3) -> Dict[str, str]:
        """Build a cache of all existing tags mapped to their commit SHAs.

        This fetches all tags once and caches them, avoiding per-version API calls.
        Returns a dict mapping tag names (without 'refs/tags/' prefix) to commit SHAs.

        Args:
            retries: Number of retry attempts on failure (default 3).
        """
        if self.__existing_tags_cache is not None:
            return self.__existing_tags_cache

        logger.debug("Building tags cache (fetching all tags)")
        cache: Dict[str, str] = {}
        last_error: Optional[Exception] = None

        for attempt in range(retries):
            try:
                _metrics.api_calls += 1
                # Fetch only tag refs using server-side filtering (much faster)
                refs = self._repo.get_git_matching_refs("tags/")
                for ref in refs:
                    tags_prefix_len = len("refs/tags/")
                    tag_name = ref.ref[tags_prefix_len:]
                    ref_type = getattr(ref.object, "type", None)
                    if ref_type == "commit":
                        cache[tag_name] = ref.object.sha
                    elif ref_type == "tag":
                        # Annotated tag - need to resolve to commit
                        # We'll resolve these lazily if needed
                        cache[tag_name] = f"annotated:{ref.object.sha}"
                # Success - break out of retry loop
                last_error = None
                break
            except Exception as e:
                last_error = e
                if attempt < retries - 1:
                    wait_time = 2**attempt  # Exponential backoff: 1s, 2s, 4s
                    logger.warning(
                        f"Failed to fetch tags (attempt {attempt + 1}/{retries}): {e}. "
                        f"Retrying in {wait_time}s..."
                    )
                    time.sleep(wait_time)

        if last_error is not None:
            logger.error(
                f"Could not build tags cache after {retries} attempts: {last_error}. "
                "All versions will be treated as new."
            )

        logger.debug(f"Tags cache built with {len(cache)} tags")
        self.__existing_tags_cache = cache
        return cache

    def _commit_sha_of_tag(self, version_tag: str) -> Optional[str]:
        """Look up the commit SHA of a given tag."""
        # Use cached tags to avoid per-version API calls
        tags_cache = self._build_tags_cache()
        if version_tag not in tags_cache:
            return None

        sha = tags_cache[version_tag]
        if sha.startswith("annotated:"):
            # Resolve annotated tag to commit SHA
            _metrics.api_calls += 1
            annotated_prefix_len = len("annotated:")
            tag = self._repo.get_git_tag(sha[annotated_prefix_len:])
            resolved_sha = cast(str, tag.object.sha)
            # Update cache with resolved value
            tags_cache[version_tag] = resolved_sha
            return resolved_sha
        return sha

    def _commit_sha_of_release_branch(self, version: str) -> str:
        """Get the latest commit SHA of the release branch for a specific version."""
        branch = self._repo.get_branch(self._release_branch(version))
        return cast(str, branch.commit.sha)

    def _highest_existing_version(self) -> Optional[VersionInfo]:
        """Get the highest existing version tag by semver.

        Uses the tags cache to find existing version tags and returns the
        highest version number among them.
        """
        tags_cache = self._build_tags_cache()
        prefix = self._tag_prefix()

        highest: Optional[VersionInfo] = None
        for tag_name in tags_cache:
            # Only consider version tags with our prefix
            if not tag_name.startswith(prefix):
                continue
            prefix_len = len(prefix)
            version_str = tag_name[prefix_len:]
            try:
                version = VersionInfo.parse(version_str)
                if highest is None or version > highest:
                    highest = version
            except ValueError:
                # Not a valid semver tag, skip
                continue

        return highest

    def get_all_tags(self) -> List[str]:
        """Get all Git tag names in the repository.

        Returns a list of tag names (without 'refs/tags/' prefix).
        Uses the tags cache to avoid repeated API calls.
        """
        tags_cache = self._build_tags_cache()
        return list(tags_cache.keys())

    def version_with_latest_commit(self, versions: Dict[str, str]) -> Optional[str]:
        """Find the version with the most recent commit datetime.

        This is used to determine which release should be marked as "latest"
        when creating multiple releases. Only the version with the most recent
        commit should be marked as latest, preventing backfilled old releases
        from being incorrectly marked as the latest release.

        Also considers existing tags - if any existing tag has a higher semver
        than all new versions, no new version will be marked as latest.

        Uses cached commit datetimes when available to avoid redundant API calls.

        Args:
            versions: Dict mapping version strings to commit SHAs

        Returns:
            The version string with the most recent commit, or None if empty
            or if an existing tag has a higher version.
        """
        if not versions:
            return None

        # Check if any existing tag has a higher version than all new versions
        highest_existing = self._highest_existing_version()
        if highest_existing:
            # Find highest new version (versions dict has "v1.2.3" format)
            highest_new: Optional[VersionInfo] = None
            for version in versions:
                v_str = version[1:] if version.startswith("v") else version
                try:
                    v = VersionInfo.parse(v_str)
                    if highest_new is None or v > highest_new:
                        highest_new = v
                except ValueError:
                    continue

            if highest_new and highest_existing > highest_new:
                logger.info(
                    f"Existing tag v{highest_existing} is newer than all new versions; "
                    "no new release will be marked as latest"
                )
                return None

        # Pre-populate commit datetime cache using git log (single command)
        # This avoids N API calls when checking N versions
        self._build_commit_datetime_cache(list(versions.values()))

        latest_version: Optional[str] = None
        latest_datetime: Optional[datetime] = None
        for version, sha in versions.items():
            # Check cache first (should be populated by _build_commit_datetime_cache)
            if sha in self.__commit_datetimes:
                commit_dt = self.__commit_datetimes[sha]
            else:
                # Fallback to API if not in cache (shouldn't happen normally)
                try:
                    _metrics.api_calls += 1
                    commit = self._repo.get_commit(sha)
                    commit_dt = commit.commit.author.date
                    self.__commit_datetimes[sha] = commit_dt
                except Exception as e:
                    logger.debug(
                        f"Could not get commit datetime for {version} ({sha}): {e}"
                    )
                    continue
            if latest_datetime is None or commit_dt > latest_datetime:
                latest_datetime = commit_dt
                latest_version = version
        return latest_version

    def _build_commit_datetime_cache(self, shas: List[str]) -> None:
        """Pre-populate commit datetime cache using git log.

        This fetches commit datetimes in a single git command instead of
        making individual API calls for each commit.

        Args:
            shas: List of commit SHAs to fetch datetimes for
        """
        if not shas:
            return

        # Check which SHAs are not already cached
        uncached = [sha for sha in shas if sha not in self.__commit_datetimes]
        if not uncached:
            return

        logger.debug(f"Building commit datetime cache for {len(uncached)} commits")
        try:
            # Get all commit datetimes in one git command
            # Format: %H = commit hash, %aI = author date (ISO 8601 strict)
            output = self._git.command("log", "--all", "--format=%H %aI")
            sha_set = set(uncached)
            found = 0
            for line in output.splitlines():
                parts = line.split(maxsplit=1)
                if len(parts) == 2:
                    commit_sha, iso_date = parts
                    if commit_sha in sha_set:
                        dt = parse_git_datetime(iso_date)
                        if not dt:
                            logger.debug("Could not parse git log date '%s'", iso_date)
                            continue
                        self.__commit_datetimes[commit_sha] = dt
                        found += 1
                        if found >= len(uncached):
                            break  # Found all we need
            logger.debug(f"Cached {found} commit datetimes from git log")
        except Exception as e:
            logger.warning(f"Failed to build commit datetime cache: {e}")

    def _filter_map_versions(self, versions: Dict[str, str]) -> Dict[str, str]:
        """Filter out versions and convert tree SHA to commit SHA."""
        # Pre-build tags cache to check existing tags quickly
        self._build_tags_cache()
        # Note: PR cache is built lazily only when needed (first registry PR lookup)

        valid = {}
        skipped_existing = 0
        for version, tree in versions.items():
            version = f"v{version}"
            version_tag = self._get_version_tag(version)

            # Fast path: check if tag already exists using cached tags
            # Just check existence, don't resolve annotated tags (saves API calls)
            tags_cache = self._build_tags_cache()
            if version_tag in tags_cache:
                # Tag exists - we skip without full validation for performance.
                skipped_existing += 1
                continue

            # Tag doesn't exist - need to find expected commit SHA
            # Try git log first (fast - O(1) cache lookup)
            expected = self._commit_sha_of_tree(tree)
            if not expected:
                # Fall back to registry PR lookup (slower - requires API calls)
                logger.debug(
                    f"No matching tree for {version}, falling back to registry PR"
                )
                expected = self._commit_sha_from_registry_pr(version, tree)
            if not expected:
                logger.debug(
                    f"Skipping {version}: no matching tree or registry PR found"
                )
                continue
            valid[version] = expected

        if skipped_existing > 0:
            logger.debug(f"Skipped {skipped_existing} versions with existing tags")
        return valid

    def _get_versions_toml(self) -> Dict[str, Any]:
        """Get and cache the raw Versions.toml data from the registry."""
        if self.__versions_toml_cache is not None:
            return self.__versions_toml_cache
        root = self._registry_path
        if not root:
            logger.debug("Package is not registered")
            return {}
        try:
            if self._clone_registry:
                path = os.path.join(self._registry_clone_dir, root, "Versions.toml")
                if not os.path.isfile(path):
                    logger.debug("Versions.toml was not found")
                    return {}
                with open(path) as f:
                    versions = toml.load(f)
            else:
                contents = self._only(
                    self._registry.get_contents(f"{root}/Versions.toml")
                )
                versions = toml.loads(contents.decoded_content.decode())
            self.__versions_toml_cache = versions
            return versions
        except UnknownObjectExceptions:
            logger.debug("Versions.toml was not found")
            return {}

    def is_version_yanked(self, version: str) -> bool:
        """Check if a version is yanked in the registry."""
        if version.startswith("v"):
            version = version[1:]
        versions = self._get_versions_toml()
        if not versions:
            return False
        if version not in versions:
            logger.debug(f"Version {version} not found in Versions.toml")
            return False
        return bool(versions[version].get("yanked", False))

    def _versions(self, min_age: Optional[timedelta] = None) -> Dict[str, str]:
        """Get all package versions from the registry."""
        if self._clone_registry:
            return self._versions_clone(min_age=min_age)
        root = self._registry_path
        if not root:
            logger.debug("Package is not registered")
            return {}
        # Get the most recent commit from before min_age.
        kwargs: Dict[str, str] = {}
        if min_age is not None:
            until = datetime.now() - min_age
            commits = self._registry.get_commits(until=until)
            # Get the first value like this because the iterator has no `next` method.
            for commit in commits:
                kwargs = {"ref": commit.commit.sha}
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

    def _tag_exists(self, version: str) -> bool:
        """Check if a tag already exists."""
        try:
            self._repo.get_git_ref(f"tags/{version}")
            return True
        except UnknownObjectException:
            return False
        except GithubException:
            # If we can't check, assume it doesn't exist
            return False

    def _generate_conventional_changelog(
        self, version_tag: str, sha: str, previous_tag: Optional[str] = None
    ) -> str:
        """Generate changelog from conventional commits.

        Args:
            version_tag: The version tag being released
            sha: Commit SHA for the release
            previous_tag: Previous release tag to generate changelog from

        Returns:
            Formatted changelog based on conventional commits
        """
        # Determine commit range
        if previous_tag:
            commit_range = f"{previous_tag}..{sha}"
        else:
            # For first release, get all commits up to this one
            commit_range = sha

        # Get commit messages
        try:
            log_output = self._git.command(
                "log",
                commit_range,
                "--format=%s|%h|%an",
                "--no-merges",
            )
        except Exception as e:
            logger.warning(f"Could not get commits for conventional changelog: {e}")
            return f"## {version_tag}\n\nRelease created.\n"

        # Parse commits into categories based on conventional commit format
        # Format: type(scope): description
        categories: Dict[str, List[Tuple[str, str, str]]] = {
            "breaking": [],  # BREAKING CHANGE or !
            "feat": [],  # Features
            "fix": [],  # Bug fixes
            "perf": [],  # Performance improvements
            "refactor": [],  # Refactoring
            "docs": [],  # Documentation
            "test": [],  # Tests
            "build": [],  # Build system
            "ci": [],  # CI/CD
            "chore": [],  # Chores
            "style": [],  # Code style
            "revert": [],  # Reverts
            "other": [],  # Non-conventional commits
        }

        for line in log_output.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|", 2)
            if len(parts) < 3:
                continue
            message, commit_hash, author = parts

            # Check for breaking (keep commit in both breaking and its type category)
            if "BREAKING CHANGE" in message or re.match(r"^\w+!:", message):
                categories["breaking"].append((message, commit_hash, author))

            # Parse conventional commit format (supports optional "!" for breaking)
            match = re.match(r"^(\w+)(\(.+\))?(!)?: (.+)$", message)
            if match:
                commit_type = match.group(1).lower()
                if commit_type in categories:
                    categories[commit_type].append((message, commit_hash, author))
                else:
                    categories["other"].append((message, commit_hash, author))
            else:
                categories["other"].append((message, commit_hash, author))

        # Build changelog
        changelog = f"## {version_tag}\n\n"

        # Section configurations (type: title)
        sections = [
            ("breaking", "Breaking Changes"),
            ("feat", "Features"),
            ("fix", "Bug Fixes"),
            ("perf", "Performance Improvements"),
            ("refactor", "Code Refactoring"),
            ("docs", "Documentation"),
            ("test", "Tests"),
            ("build", "Build System"),
            ("ci", "CI/CD"),
            ("style", "Code Style"),
            ("chore", "Chores"),
            ("revert", "Reverts"),
        ]

        has_any_commits = (
            any(categories[cat_key] for cat_key, _ in sections) or categories["other"]
        )

        repo_url = f"{self._gh_url}/{self._repo.full_name}"

        for cat_key, title in sections:
            commits = categories[cat_key]
            if commits:
                changelog += f"### {title}\n\n"
                for message, commit_hash, author in commits:
                    changelog += (
                        f"- {message} ([`{commit_hash}`]"
                        f"({repo_url}/commit/{commit_hash})) - {author}\n"
                    )
                changelog += "\n"

        # Add other commits if any
        if categories["other"]:
            changelog += "### Other Changes\n\n"
            for message, commit_hash, author in categories["other"]:
                changelog += (
                    f"- {message} ([`{commit_hash}`]"
                    f"({repo_url}/commit/{commit_hash})) - {author}\n"
                )
            changelog += "\n"

        # If no commits were found, add an informative message
        if not has_any_commits:
            if previous_tag:
                changelog += "No new commits since the previous release.\n"
            else:
                changelog += "Initial release.\n"

        # Add compare link if we have a previous tag
        if previous_tag:
            changelog += (
                f"**Full Changelog**: {repo_url}/compare/"
                f"{previous_tag}...{version_tag}\n"
            )

        return changelog

    def create_issue_for_manual_tag(self, failures: list[tuple[str, str, str]]) -> None:
        """Create an issue requesting manual intervention for failed releases.

        Args:
            failures: List of (version, sha, error_message) tuples
        """
        if not failures:
            return

        # Check for existing open issue to avoid duplicates
        # Search by title since labels may not be available
        try:
            existing = list(self._repo.get_issues(state="open"))
            for issue in existing:
                if "TagBot: Manual intervention" in issue.title:
                    logger.info(
                        "Issue already exists for manual tag intervention: "
                        f"{issue.html_url}"
                    )
                    return
        except GithubException as e:
            logger.debug(f"Could not check for existing issues: {e}")

        # Try to create/get the label
        label_available = False
        try:
            self._repo.get_label("tagbot-manual")
            label_available = True
        except UnknownObjectException:
            try:
                self._repo.create_label(
                    "tagbot-manual", "d73a4a", "TagBot needs manual intervention"
                )
                label_available = True
            except GithubException as e:
                logger.debug(f"Could not create 'tagbot-manual' label: {e}")
        except GithubException as e:
            logger.debug(f"Could not check for 'tagbot-manual' label: {e}")

        # Build command list, checking which tags already exist
        commands = []
        for v, sha, _ in failures:
            if self._tag_exists(v):
                # Tag exists, just need to create release
                commands.append(f"gh release create {v} --generate-notes")
            else:
                # Need to create tag and release
                commands.append(
                    f"git tag -a {v} {sha} -m '{v}' && git push origin {v} && "
                    f"gh release create {v} --generate-notes"
                )

        versions_list = "\n".join(
            f"- [ ] `{v}` at commit `{sha[:8]}`\n  - Error: {self._sanitize(err)}"
            for v, sha, err in failures
        )
        pat_url = (
            "https://docs.github.com/en/authentication/"
            "keeping-your-account-and-data-secure/managing-your-personal-access-tokens"
        )
        troubleshoot_url = (
            "https://github.com/JuliaRegistries/TagBot"
            "#commits-that-modify-workflow-files"
        )
        body = f"""\
TagBot could not automatically create releases for the following versions. \
This may be because:
- The commits modify workflow files (`.github/workflows/`), \
which `GITHUB_TOKEN` cannot operate on
- The tag already exists but the release failed to be created
- A network or API error occurred

## Versions needing manual release

{versions_list}

## How to fix

Run these commands locally:

```bash
{chr(10).join(commands)}
```

Or create releases manually via the GitHub UI.

## Prevent this in the future

If this is due to workflow file changes, avoid modifying them in the same \
commit as version bumps, or use a \
[Personal Access Token with `workflow` scope]({pat_url}).

See [TagBot troubleshooting]({troubleshoot_url}) for details.

---
*This issue was automatically created by TagBot. ([Run logs]({self._run_url()}))*
"""
        try:
            issue = self._repo.create_issue(
                title="TagBot: Manual intervention needed for releases",
                body=body,
                labels=["tagbot-manual"] if label_available else [],
            )
            logger.info(f"Created issue for manual intervention: {issue.html_url}")
            self._manual_intervention_issue_url = issue.html_url
        except GithubException as e:
            logger.warning(
                f"Could not create issue for manual intervention: {e}\n"
                "To fix permission issues, check your repository settings:\n"
                "1. Go to Settings > Actions > General > Workflow permissions\n"
                "2. Select 'Read and write permissions'\n"
                "Or see: https://github.com/JuliaRegistries/TagBot#troubleshooting"
            )

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
        data: Dict[str, Any] = {
            "image": self._image_id(),
            "repo": self._repo.full_name,
            "run": self._run_url(),
            "stacktrace": trace,
            "version": _get_tagbot_version(),
        }
        if self._manual_intervention_issue_url:
            data["manual_intervention_url"] = self._manual_intervention_issue_url
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
        start_time = time.time()
        current = self._versions()
        logger.info(f"Found {len(current)} total versions in registry")
        # Check all versions every time (no lookback window)
        # This allows backfilling old releases if TagBot is set up later
        logger.debug(f"Checking all {len(current)} versions")
        # Make sure to insert items in SemVer order.
        versions = {}
        for v in sorted(current.keys(), key=VersionInfo.parse):
            versions[v] = current[v]
            _metrics.versions_checked += 1
        result = self._filter_map_versions(versions)
        elapsed = time.time() - start_time
        logger.info(
            f"Version check complete: {len(result)} new versions found "
            f"(checked {len(current)} total versions in {elapsed:.2f}s)"
        )
        return result

    def create_dispatch_event(self, payload: Mapping[str, object]) -> None:
        """Create a repository dispatch event."""
        # TODO: Remove the comment when PyGithub#1502 is published.
        self._repo.create_repository_dispatch("TagBot", payload)

    def configure_ssh(self, key: str, password: Optional[str], repo: str = "") -> None:
        """Configure the repo to use an SSH key for authentication."""
        decoded_key = self._maybe_decode_private_key(key)
        self._validate_ssh_key(decoded_key)
        if not repo:
            self._git.set_remote_url(self._repo.ssh_url)
        _, priv = mkstemp(prefix="tagbot_key_")
        with open(priv, "w") as f:
            # SSH keys must end with a single newline.
            f.write(decoded_key.strip() + "\n")
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
        # Test SSH authentication
        self._test_ssh_connection(cmd, host)

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

    def create_release(self, version: str, sha: str, is_latest: bool = True) -> None:
        """Create a GitHub release.

        Args:
            version: The version string (e.g., "v1.2.3")
            sha: The commit SHA to tag
            is_latest: Whether this release should be marked as the latest release.
                       Set to False when backfilling old releases to avoid marking
                       them as latest.
        """
        target = sha
        if self._commit_sha_of_release_branch(version) == sha:
            # If we use <branch> as the target, GitHub will show
            # "<n> commits to <branch> since this release" on the release page.
            target = self._release_branch(version)
        version_tag = self._get_version_tag(version)
        logger.debug(f"Release {version_tag} target: {target}")
        # Check if a release for this tag already exists before doing work
        # Also fetch releases list for later use in changelog generation
        releases = []
        try:
            releases = list(self._repo.get_releases())
            for release in releases:
                if release.tag_name == version_tag:
                    logger.info(
                        f"Release for tag {version_tag} already exists, skipping"
                    )
                    return
        except GithubException as e:
            logger.warning(f"Could not check for existing releases: {e}")

        # Generate release notes based on format
        if self._changelog_format == "github":
            log = ""  # Empty body triggers GitHub to auto-generate notes
            logger.info("Using GitHub auto-generated release notes")
        elif self._changelog_format == "conventional":
            # Find previous release for conventional changelog
            previous_tag = None
            if releases:
                # Find the most recent release before this one
                for release in releases:
                    if release.tag_name != version_tag:
                        previous_tag = release.tag_name
                        break

            logger.info("Generating conventional commits changelog")
            log = self._generate_conventional_changelog(version_tag, sha, previous_tag)
        else:  # custom format
            log = self._changelog.get(version_tag, sha) if self._changelog else ""

        if not self._draft:
            # Always create tags via the CLI as the GitHub API has a bug which
            # only allows tags to be created for SHAs which are the the HEAD
            # commit on a branch.
            # https://github.com/JuliaRegistries/TagBot/issues/239#issuecomment-2246021651
            self._git.create_tag(version_tag, sha, log)
        logger.info(f"Creating GitHub release {version_tag} at {sha}")
        # Use make_latest=False for backfilled old releases to avoid marking them
        # as the "Latest" release on GitHub
        make_latest_str = "true" if is_latest else "false"

        def _release_already_exists(exc: GithubException) -> bool:
            data = getattr(exc, "data", {}) or {}
            for err in data.get("errors", []):
                if isinstance(err, dict) and err.get("code") == "already_exists":
                    return True
            return "already exists" in str(exc)

        try:
            self._repo.create_git_release(
                version_tag,
                version_tag,
                log,
                target_commitish=target,
                draft=self._draft,
                make_latest=make_latest_str,
                generate_release_notes=(self._changelog_format == "github"),
            )
        except GithubException as e:
            if e.status == 422 and _release_already_exists(e):
                logger.info(f"Release for tag {version_tag} already exists, skipping")
                return
            elif e.status == 403 and "resource not accessible" in str(e).lower():
                logger.error(
                    "Release creation blocked: token lacks required permissions. "
                    "Use a PAT with contents:write (and workflows if tagging "
                    "workflow changes)."
                )
            elif e.status == 401:
                logger.error(
                    "Release creation failed: bad credentials. Refresh the token or "
                    "use a PAT with repo scope."
                )
            raise
        logger.info(f"GitHub release {version_tag} created successfully")

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
        trace = self._sanitize(traceback.format_exc())
        if isinstance(e, Abort):
            # Abort is raised for characterized failures (e.g., git command failures)
            # Don't report as "unexpected internal failure"
            internal = False
            allowed = False
        elif isinstance(e, RequestException):
            logger.warning("TagBot encountered a likely transient HTTP exception")
            logger.info(trace)
            allowed = True
        elif isinstance(e, GithubException):
            logger.info(e.headers)
            if 500 <= e.status < 600:
                logger.warning("GitHub returned a 5xx error code")
                logger.info(trace)
                allowed = True
            elif e.status == 401:
                logger.error(
                    "GitHub returned 401 Bad credentials. Verify that your token "
                    "is valid and has access to the repository and registry."
                )
                internal = False
                allowed = False
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

    def is_backport_commit(self, sha: str) -> bool:
        """Check if the commit is on a non-default branch."""
        try:
            branches_output = self._git.command("branch", "-r", "--contains", sha)
            default = f"origin/{self._repo.default_branch}"
            branches = [b.strip() for b in branches_output.splitlines() if b.strip()]
            if not branches:
                # If the commit is not on any remote branch, it cannot be a backport
                return False
            # A commit is considered a backport only if it is not on the default branch
            return default not in branches
        except Abort:
            # If git command fails, assume not backport
            logger.debug("Failed to determine backport status", exc_info=True)
            return False
