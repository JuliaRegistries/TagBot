import os.path
import subprocess

from datetime import datetime
from tempfile import mkdtemp
from typing import Optional

from . import Abort, debug, info


class Git:
    """Provides access to a local Git repository."""

    def __init__(self, repo: str, token: str) -> None:
        self._repo = repo
        self._token = token
        self._default_branch = ""
        self.__dir: Optional[str] = None

    @property
    def _dir(self) -> str:
        """Get the repository clone location (cloning if necessary)."""
        if self.__dir is not None:
            return self.__dir
        url = f"https://oauth2:{self._token}@github.com/{self._repo}"
        dest = mkdtemp(prefix="tagbot_repo_")
        self.command("clone", url, dest, repo=None)
        self.__dir = dest
        self._default_branch = self.command("rev-parse", "--abbrev-ref", "HEAD")
        return self.__dir

    def command(self, *argv: str, repo: Optional[str] = "") -> str:
        """Run a Git command."""
        args = ["git"]
        if repo is not None:
            args.extend(["-C", repo or self._dir])
        args.extend(argv)
        cmd = " ".join(args)
        debug(f"Running '{cmd}'")
        p = subprocess.run(args, text=True, capture_output=True)
        out = p.stdout.strip()
        if p.returncode:
            if out:
                info(out)
            if p.stderr:
                info(p.stderr.strip())
            raise Abort(f"Git command '{cmd}' failed")
        return out

    def check(self, *argv: str, repo: Optional[str] = "") -> bool:
        """Run a Git command, but only return its success status."""
        try:
            self.command(*argv, repo=repo)
            return True
        except Abort:
            return False

    def path(self, *paths: str) -> str:
        """Get a path relative to the repository root."""
        return os.path.join(self._dir, *paths)

    def commit_sha_of_default(self) -> str:
        return self.command("rev-parse", self._default_branch)

    def commit_sha_of_tree(self, tree: str) -> Optional[str]:
        """Get the commit SHA that corresponds to a tree SHA."""
        lines = self.command("log", "--all", "--format=%H %T").splitlines()
        for line in lines:
            c, t = line.split()
            if t == tree:
                return c
        return None

    def commit_sha_of_tag(self, version: str) -> str:
        """Get the commit SHA that corresponds to a tag."""
        lines = self.command("show-ref", "-d", version).splitlines()
        # The output looks like this: <sha> refs/tags/<version>.
        # For lightweight tags, there's just one line which has the commit SHA.
        # For annotaetd tags, there is a second entry where the ref has a ^{} suffix.
        # That line's SHA is that of the commit rather than that of the tag object.
        return max(lines, key=len).split()[0]

    def invalid_tag_exists(self, version: str, sha: str) -> bool:
        """Check whether or not an existing tag points at the wrong commit."""
        if not self.command("tag", "--list", version):
            return False
        return self.commit_sha_of_tag(version) != sha

    def set_remote_url(self, url: str) -> None:
        """Update the origin remote URL."""
        self.command("remote", "set-url", "origin", url)

    def config(self, key: str, val: str) -> None:
        """Configure a repository."""
        self.command("config", key, val)

    def create_tag(self, version: str, sha: str) -> None:
        """Create and push a Git tag."""
        self.command("tag", version, sha)
        self.command("push", "origin", version)

    def fetch_branch(self, branch: str) -> bool:
        """Try to checkout a remote branch, and return whether or not it succeeded."""
        if not self.check("checkout", branch):
            return False
        self.command("checkout", self._default_branch)
        return True

    def can_fast_forward(self, branch: str) -> bool:
        """Check whether the default branch can be fast-forwarded to branch."""
        return self.check("merge-base", "--is-ancestor", self._default_branch, branch)

    def merge_and_delete_branch(self, branch: str) -> None:
        """Merge a branch into master and delete the branch."""
        self.command("checkout", self._default_branch)
        self.command("merge", branch)
        self.command("push", "origin", self._default_branch)
        self.command("push", "-d", "origin", branch)

    def time_of_commit(self, sha: str) -> datetime:
        """Get the time that a commit was made."""
        date = self.command("show", "-s", "--format=%cI", sha)
        dt = datetime.fromisoformat(date)
        # Convert to UTC and remove time zone information.
        offset = dt.utcoffset()
        if offset:
            dt -= offset
        return dt.replace(tzinfo=None)
