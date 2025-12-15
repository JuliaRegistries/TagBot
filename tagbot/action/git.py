import re
import subprocess

from datetime import datetime
from tempfile import mkdtemp
from typing import Optional, cast
from urllib.parse import urlparse

from .. import logger
from . import Abort


class Git:
    """Provides access to a local Git repository."""

    def __init__(
        self, github: str, repo: str, token: str, user: str, email: str
    ) -> None:
        self._github = cast(str, urlparse(github).hostname)
        self._repo = repo
        self._token = token
        self._user = user
        self._email = email
        self._gpgsign = False
        self.__default_branch: Optional[str] = None
        self.__dir: Optional[str] = None

    @property
    def _dir(self) -> str:
        """Get the repository clone location (cloning if necessary)."""
        if self.__dir is not None:
            return self.__dir
        url = f"https://oauth2:{self._token}@{self._github}/{self._repo}"
        dest = mkdtemp(prefix="tagbot_repo_")
        self.command("clone", url, dest, repo=None)
        self.__dir = dest
        return self.__dir

    def default_branch(self, repo: str = "") -> str:
        """Get the name of the default branch."""
        if not repo and self.__default_branch is not None:
            return self.__default_branch
        remote = self.command("remote", "show", "origin", repo=repo)
        m = re.search("HEAD branch:(.+)", remote)
        if m:
            branch = m[1].strip()
        else:
            logger.warning("Looking up default branch name failed, assuming master")
            branch = "master"
        if not repo:
            self.__default_branch = branch
        return branch

    def command(self, *argv: str, repo: Optional[str] = "") -> str:
        """Run a Git command."""
        args = ["git"]
        if repo is not None:
            # Ideally, we'd set self._dir as the default for repo,
            # but it gets evaluated at method definition.
            args.extend(["-C", repo or self._dir])
        args.extend(argv)
        cmd = " ".join(args)
        logger.debug(f"Running '{cmd}'")
        proc = subprocess.run(args, text=True, capture_output=True)
        out = proc.stdout.strip()
        if proc.returncode:
            if out:
                logger.info(out)
            if proc.stderr:
                logger.info(proc.stderr.strip())
            raise Abort(f"Git command '{cmd}' failed")
        return out

    def check(self, *argv: str, repo: Optional[str] = "") -> bool:
        """Run a Git command, but only return its success status."""
        try:
            self.command(*argv, repo=repo)
            return True
        except Abort:
            return False

    def commit_sha_of_tree(self, tree: str) -> Optional[str]:
        """Get the commit SHA of a corresponding tree SHA."""
        # We need --all in case the registered commit isn't on the default branch.
        for line in self.command("log", "--all", "--format=%H %T").splitlines():
            # The format of each line is "<commit sha> <tree sha>".
            c, t = line.split()
            if t == tree:
                return c
        return None

    def set_remote_url(self, url: str) -> None:
        """Update the origin remote URL."""
        self.command("remote", "set-url", "origin", url)

    def config(self, key: str, val: str, repo: str = "") -> None:
        """Configure the repository."""
        self.command("config", key, val, repo=repo)

    def remote_tag_exists(self, version: str) -> bool:
        """Check if a tag exists on the remote."""
        # Use ls-remote to check if the tag exists on origin
        try:
            output = self.command("ls-remote", "--tags", "origin", version)
            return bool(output.strip())
        except Abort:
            return False

    def create_tag(self, version: str, sha: str, message: str) -> None:
        """Create and push a Git tag."""
        self.config("user.name", self._user)
        self.config("user.email", self._email)
        # As mentioned in configure_gpg, we can't fully configure automatic signing.
        sign = ["--sign"] if self._gpgsign else []

        # Check if tag already exists on remote
        if self.remote_tag_exists(version):
            logger.info(f"Tag {version} already exists on remote, skipping tag creation")
            return

        self.command("tag", *sign, "-m", message, version, sha)
        try:
            self.command("push", "origin", version)
        except Abort:
            logger.error(
                f"Failed to push tag {version}. If this is due to workflow "
                f"file changes in the tagged commit, use an SSH deploy key "
                f"(see README) or manually run: "
                f"git tag -a {version} {sha} -m '{version}' && "
                f"git push origin {version}"
            )
            raise

    def fetch_branch(self, branch: str) -> bool:
        """Try to checkout a remote branch, and return whether or not it succeeded."""
        # Git lets us check out remote branches without the remote name,
        # and automatically creates a local branch that tracks the remote one.
        # Git does not let us do the same with a merge, so this method must be called
        # before we call merge_and_delete_branch.
        if not self.check("checkout", branch):
            return False
        self.command("checkout", self.default_branch())
        return True

    def is_merged(self, branch: str) -> bool:
        """Determine if a branch has been merged."""
        head = self.command("rev-parse", branch)
        shas = self.command("log", self.default_branch(), "--format=%H").splitlines()
        return head in shas

    def can_fast_forward(self, branch: str) -> bool:
        """Check whether the default branch can be fast-forwarded to branch."""
        # https://stackoverflow.com/a/49272912
        return self.check("merge-base", "--is-ancestor", self.default_branch(), branch)

    def merge_and_delete_branch(self, branch: str) -> None:
        """Merge a branch into master and delete the branch."""
        self.command("checkout", self.default_branch())
        self.command("merge", branch)
        self.command("push", "origin", self.default_branch())
        self.command("push", "-d", "origin", branch)

    def time_of_commit(self, sha: str, repo: str = "") -> datetime:
        """Get the time that a commit was made."""
        # The format %cI is "committer date, strict ISO 8601 format".
        date = self.command("show", "-s", "--format=%cI", sha, repo=repo)
        dt = datetime.fromisoformat(date)
        # Convert to UTC and remove time zone information.
        offset = dt.utcoffset()
        if offset:
            dt -= offset
        return dt.replace(tzinfo=None)
