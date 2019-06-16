import os
import shutil
import subprocess
import tempfile

from . import env


class Git:
    """Provides access to the Git CLI."""

    _name = env.git_tagger_name
    _email = env.git_tagger_email

    def __call(*args: str) -> None:
        """Run a shell command."""
        subprocess.run(args, check=True)

    def _git_clone(self, repo: str, dir: str, auth: str) -> None:
        """Clone a Git repo."""
        url = f"https://oauth2:{auth}@github.com/{repo}"
        self.__call("git", "clone", url, dir)

    def _git_config(self, dir: str, key: str, val: str) -> None:
        """Configure a Git repo."""
        self.__call("git", "-C", dir, "config", key, val)

    def _git_tag(self, dir: str, tag: str, ref: str, body: str) -> None:
        """Create a Git tag."""
        self.__call("git", "-C", dir, "tag", tag, ref, "-s", "-m", body)

    def _git_push_tags(self, dir: str) -> None:
        """Push Git tags.`"""
        self.__call("git", "-C", dir, "push", "origin", "--tags")

    def create_tag(self, repo: str, tag: str, ref: str, body: str, auth: str) -> None:
        """Create and push a Git tag."""
        dir = tempfile.mkdtemp()
        try:
            self._git_clone(repo, dir, auth)
            self._git_config(dir, "user.name", self._name)
            self._git_config(dir, "user.email", self._email)
            self._git_tag(dir, tag, ref, body)
            self._git_push_tags(dir)
        finally:
            shutil.rmtree(dir)
