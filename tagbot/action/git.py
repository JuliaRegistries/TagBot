import re
import subprocess

from datetime import datetime, timezone
from tempfile import mkdtemp
from typing import Optional, cast
from urllib.parse import urlparse

from .. import logger
from . import Abort


def parse_git_datetime(
    date_str: str, _depth: int = 0, _max_depth: int = 2
) -> Optional[datetime]:
    """Parse Git date output into a naive UTC datetime.

    Handles common Git formats and normalizes timezone offsets.
    Returns None if parsing fails.
    """

    def normalize_offset(s: str) -> str:
        match = re.search(r"([+-]\d{2})(:?)(\d{2})$", s)
        if match and not match.group(2):
            # Build prefix separately to avoid an overly long formatted line
            prefix = s[: -len(match.group(0))]
            return f"{prefix}{match.group(1)}:{match.group(3)}"
        return s

    cleaned = date_str.strip()
    attempts = [cleaned, normalize_offset(cleaned)]
    formats = ["%Y-%m-%d %H:%M:%S %z", "%a %b %d %H:%M:%S %Y %z"]

    for candidate in attempts:
        try:
            dt = datetime.fromisoformat(candidate)
        except ValueError:
            dt = None
        if dt:
            offset = dt.utcoffset()
            if offset:
                dt -= offset
            return dt.replace(tzinfo=None)
        for fmt in formats:
            try:
                dt = datetime.strptime(candidate, fmt)
            except ValueError:
                continue
            return dt.astimezone(timezone.utc).replace(tzinfo=None)

    match = re.search(
        r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[+-]\d{2}:?\d{2})",
        cleaned,
    )
    if match:
        candidate = normalize_offset(match.group(1))
        # Prevent infinite recursion: only recurse if normalization changed
        # the matched string and we haven't exceeded a small depth cap.
        if (
            candidate != match.group(1)
            and candidate != date_str
            and _depth < _max_depth
        ):
            return parse_git_datetime(candidate, _depth + 1, _max_depth)
        return None

    return None


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

    def _sanitize_command(self, cmd: str) -> str:
        """Remove sensitive tokens from command strings."""
        if self._token:
            cmd = cmd.replace(self._token, "***")
        return cmd

    def command(self, *argv: str, repo: Optional[str] = "") -> str:
        """Run a Git command."""
        args = ["git"]
        if repo is not None:
            # Ideally, we'd set self._dir as the default for repo,
            # but it gets evaluated at method definition.
            args.extend(["-C", repo or self._dir])
        args.extend(argv)
        cmd = " ".join(args)
        logger.debug(f"Running '{self._sanitize_command(cmd)}'")
        proc = subprocess.run(args, text=True, capture_output=True)
        out = proc.stdout.strip()
        if proc.returncode:
            err = proc.stderr.strip()
            if out:
                logger.error(f"stdout: {self._sanitize_command(out)}")
            if err:
                logger.error(f"stderr: {self._sanitize_command(err)}")

            detail = err or out
            hint = self._hint_for_failure(detail)
            message = f"Git command '{self._sanitize_command(cmd)}' failed"
            if detail:
                message = f"{message}: {self._sanitize_command(detail)}"
            if hint:
                message = f"{message} ({hint})"
            raise Abort(message)
        return out

    def _hint_for_failure(self, detail: str) -> Optional[str]:
        """Return a user-facing hint for common git errors."""
        lowered = detail.casefold()
        if "permission to" in lowered and "denied" in lowered:
            return "use a PAT with contents:write or a deploy key"
        if "workflow" in lowered or "workflows" in lowered:
            if "refusing" in lowered or "permission" in lowered:
                return "provide workflow scope or avoid workflow changes"
        if "publickey" in lowered or "permission denied (publickey)" in lowered:
            return "configure SSH deploy key or switch to https with PAT"
        if "bad credentials" in lowered or "authentication failed" in lowered:
            return "token is invalid or lacks access"
        return None

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
            logger.info(
                f"Tag {version} already exists on remote, skipping tag creation"
            )
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
        # Use git log with ^{commit} to dereference tags to their underlying commit,
        # since git show on annotated tags outputs the tag message before the commit.
        date = self.command("log", "-1", "--format=%cI", f"{sha}^{{commit}}", repo=repo)
        parsed = parse_git_datetime(date)
        if not parsed:
            logger.warning(
                "Could not parse git date '%s', using current UTC", date.strip()
            )
            return datetime.now(timezone.utc).replace(tzinfo=None)
        return parsed
