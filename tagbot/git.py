import os
import shutil
import subprocess
import tempfile

from . import env


class Git:
    _name = env.git_tagger_name
    _email = env.git_tagger_email

    def __call(*args):
        subprocess.run(args, check=True)

    def _git_clone(repo, dir, auth):
        url = f"https://oauth2:{auth}@github.com/{repo}"
        __call("git", "clone", url, dir)

    def _git_config(dir, key, val):
        __call("git", "-C", dir, "config", key, val)

    def _git_tag(dir, tag, ref, body):
        __call("git", "-C", dir, "tag", tag, ref, "-s", "-m", body)

    def _git_push_tags(dir):
        __call("git", "-C", dir, "push", "origin", "--tags")

    def create_tag(self, repo, tag, ref, body, auth):
        """Create and push a Git tag."""
        dir = tempfile.mkdtemp()
        try:
            _git_clone(repo, dir, auth)
            _git_config(dir, "user.name", self.name)
            _git_config(dir, "user.email", self.email)
            _git_tag(dir, tag, ref, body)
            _git_push_tags(dir)
        finally:
            shutil.rmtree(dir)
