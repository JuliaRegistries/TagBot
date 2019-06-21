from unittest.mock import call, patch

from tagbot import env, resources
from tagbot.mixins import Git

mixin = Git()

# TODO: Better way to patch has_gpg.


@patch("subprocess.run")
def test_git(run):
    git = mixin._Git__git
    git("foo", "bar")
    run.assert_called_once_with(["git", "foo", "bar"], check=True)
    run.reset_mock()
    git("foo", "bar", dir="baz")
    run.assert_called_once_with(["git", "-C", "baz", "foo", "bar"], check=True)


@patch("tagbot.mixins.Git._Git__git")
def test_git_clone(git):
    mixin._git_clone("foo/bar", "baz", "token")
    git.assert_called_once_with(
        "clone", "https://oauth2:token@github.com/foo/bar", "baz"
    )


@patch("tagbot.mixins.Git._Git__git")
def test_git_config(git):
    mixin._git_config("foo", "bar", "baz")
    git.assert_called_once_with("config", "bar", "baz", dir="foo")


@patch("tagbot.mixins.Git._Git__git")
def test_git_tag(git):
    old_gpg = resources.has_gpg
    resources.has_gpg = True
    mixin._git_tag("foo", "v0.1.2", "abc", "body")
    git.assert_called_once_with("tag", "v0.1.2", "abc", "-m", "body", "-s", dir="foo")
    git.reset_mock()
    resources.has_gpg = False
    mixin._git_tag("foo", "v0.1.2", "abc", "body")
    git.assert_called_once_with("tag", "v0.1.2", "abc", "-m", "body", dir="foo")
    resources.has_gpg = old_gpg


@patch("tagbot.mixins.Git._Git__git")
def test_git_push_tags(git):
    mixin._git_push_tags("foo")
    git.assert_called_once_with("push", "origin", "--tags", dir="foo")


@patch("tagbot.mixins.Git._Git__git")
@patch("tempfile.mkdtemp")
@patch("shutil.rmtree")
def test_create_tag(rmtree, mkdtemp, git):
    old_gpg = resources.has_gpg
    resources.has_gpg = True
    mkdtemp.return_value = "dir"
    mixin.create_tag("foo/bar", "v0.1.2", "abc", "body", "token")
    rmtree.assert_called_once_with("dir")
    git.assert_has_calls(
        [
            call("clone", "https://oauth2:token@github.com/foo/bar", "dir"),
            call("config", "user.name", env.git_tagger_name, dir="dir"),
            call("config", "user.email", env.git_tagger_email, dir="dir"),
            call("tag", "v0.1.2", "abc", "-m", "body", "-s", dir="dir"),
            call("push", "origin", "--tags", dir="dir"),
        ]
    )
