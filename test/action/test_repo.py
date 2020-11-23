import os

from base64 import b64encode
from datetime import datetime, timedelta
from stat import S_IREAD, S_IWRITE, S_IEXEC
from subprocess import DEVNULL
from unittest.mock import Mock, call, mock_open, patch

import pytest

from github import GithubException, InputGitAuthor, UnknownObjectException
from github.Requester import requests

from tagbot.action import TAGBOT_WEB, Abort, InvalidProject
from tagbot.action.repo import Repo

RequestException = requests.RequestException


def _repo(
    *,
    repo="",
    registry="",
    github="",
    github_api="",
    token="",
    changelog="",
    ignore=[],
    ssh=False,
    gpg=False,
    user="",
    email="",
    lookback=3,
    branch=None,
):
    return Repo(
        repo=repo,
        registry=registry,
        github=github,
        github_api=github_api,
        token=token,
        changelog=changelog,
        changelog_ignore=ignore,
        ssh=ssh,
        gpg=gpg,
        user=user,
        email=email,
        lookback=lookback,
        branch=branch,
    )


def test_constuctor():
    r = _repo(github="github.com", github_api="api.github.com")
    assert r._gh_url == "https://github.com"
    assert r._gh_api == "https://api.github.com"
    assert r._git._github == "github.com"
    r = _repo(github="https://github.com", github_api="https://api.github.com")
    assert r._gh_url == "https://github.com"
    assert r._gh_api == "https://api.github.com"
    assert r._git._github == "github.com"


def test_project():
    r = _repo()
    r._repo.get_contents = Mock(
        return_value=Mock(decoded_content=b"""name = "FooBar"\nuuid="abc-def"\n""")
    )
    assert r._project("name") == "FooBar"
    assert r._project("uuid") == "abc-def"
    assert r._project("name") == "FooBar"
    r._repo.get_contents.assert_called_once_with("Project.toml")
    r._repo.get_contents.side_effect = UnknownObjectException(404, "???")
    r._Repo__project = None
    with pytest.raises(InvalidProject):
        r._project("name")


def test_registry_path():
    r = _repo()
    r._registry = Mock()
    r._registry.get_contents.return_value.decoded_content = b"""
    [packages]
    abc-def = { path = "B/Bar" }
    """
    r._project = lambda _k: "abc-ddd"
    assert r._registry_path is None
    r._project = lambda _k: "abc-def"
    assert r._registry_path == "B/Bar"
    assert r._registry_path == "B/Bar"
    assert r._registry.get_contents.call_count == 2


def test_release_branch():
    r = _repo()
    r._repo = Mock(default_branch="a")
    assert r._release_branch == "a"
    r = _repo(branch="b")
    assert r._release_branch == "b"


def test_only():
    r = _repo()
    assert r._only(1) == 1
    assert r._only([1]) == 1
    assert r._only([[1]]) == [1]


def test_maybe_decode_private_key():
    r = _repo()
    plain = "BEGIN OPENSSH PRIVATE KEY foo bar"
    b64 = b64encode(plain.encode()).decode()
    assert r._maybe_decode_private_key(plain) == plain
    assert r._maybe_decode_private_key(b64) == plain


def test_create_release_branch_pr():
    r = _repo()
    r._repo = Mock(default_branch="default")
    r._create_release_branch_pr("v1.2.3", "branch")
    r._repo.create_pull.assert_called_once_with(
        title="Merge release branch for v1.2.3", body="", head="branch", base="default",
    )


def test_registry_pr():
    r = _repo()
    r._Repo__project = {"name": "PkgName", "uuid": "abcdef0123456789"}
    r._registry = Mock(owner=Mock(login="Owner"))
    now = datetime.now()
    owner_pr = Mock(merged=True, merged_at=now)
    r._registry.get_pulls.return_value = [owner_pr]
    assert r._registry_pr("v1.2.3") is owner_pr
    r._registry.get_pulls.assert_called_once_with(
        head="Owner:registrator/pkgname/abcdef01/v1.2.3", state="closed",
    )
    r._registry.get_pulls.side_effect = [[], [Mock(closed_at=now - timedelta(days=10))]]
    assert r._registry_pr("v2.3.4") is None
    calls = [
        call(head="Owner:registrator/pkgname/abcdef01/v2.3.4", state="closed"),
        call(state="closed"),
    ]
    r._registry.get_pulls.assert_has_calls(calls)
    good_pr = Mock(
        closed_at=now - timedelta(days=2),
        merged=True,
        head=Mock(ref="registrator/pkgname/abcdef01/v3.4.5"),
    )
    r._registry.get_pulls.side_effect = [[], [good_pr]]
    assert r._registry_pr("v3.4.5") is good_pr
    calls = [
        call(head="Owner:registrator/pkgname/abcdef01/v3.4.5", state="closed"),
        call(state="closed"),
    ]
    r._registry.get_pulls.assert_has_calls(calls)


@patch("tagbot.action.repo.logger")
def test_commit_sha_from_registry_pr(logger):
    r = _repo()
    r._registry_pr = Mock(return_value=None)
    assert r._commit_sha_from_registry_pr("v1.2.3", "abc") is None
    logger.info.assert_called_with("Did not find registry PR")
    r._registry_pr.return_value = Mock(body="")
    assert r._commit_sha_from_registry_pr("v2.3.4", "bcd") is None
    logger.info.assert_called_with("Registry PR body did not match")
    r._registry_pr.return_value.body = f"foo\n- Commit: {'a' * 32}\nbar"
    r._repo.get_commit = Mock()
    r._repo.get_commit.return_value.commit.tree.sha = "def"
    r._repo.get_commit.return_value.sha = "sha"
    assert r._commit_sha_from_registry_pr("v3.4.5", "cde") is None
    r._repo.get_commit.assert_called_with("a" * 32)
    logger.warning.assert_called_with(
        "Tree SHA of commit from registry PR does not match"
    )
    assert r._commit_sha_from_registry_pr("v4.5.6", "def") == "sha"


def test_commit_sha_of_tree_from_branch():
    r = _repo()
    since = datetime.now()
    r._repo.get_commits = Mock(return_value=[Mock(sha="abc"), Mock(sha="sha")])
    r._repo.get_commits.return_value[1].commit.tree.sha = "tree"
    assert r._commit_sha_of_tree_from_branch("master", "tree", since) == "sha"
    r._repo.get_commits.assert_called_with(sha="master", since=since)
    r._repo.get_commits.return_value.pop()
    assert r._commit_sha_of_tree_from_branch("master", "tree", since) is None


def test_commit_sha_of_tree():
    r = _repo()
    now = datetime.now()
    r._repo = Mock(default_branch="master",)
    branches = r._repo.get_branches.return_value = [Mock(), Mock()]
    branches[0].name = "foo"
    branches[1].name = "master"
    r._lookback = Mock(__rsub__=lambda x, y: now)
    r._commit_sha_of_tree_from_branch = Mock(side_effect=["sha1", None, "sha2"])
    assert r._commit_sha_of_tree("tree") == "sha1"
    r._repo.get_branches.assert_not_called()
    r._commit_sha_of_tree_from_branch.assert_called_once_with("master", "tree", now)
    assert r._commit_sha_of_tree("tree") == "sha2"
    r._commit_sha_of_tree_from_branch.assert_called_with("foo", "tree", now)
    r._commit_sha_of_tree_from_branch.side_effect = None
    r._commit_sha_of_tree_from_branch.return_value = None
    r._git.commit_sha_of_tree = Mock(side_effect=["sha", None])
    assert r._commit_sha_of_tree("tree") == "sha"
    assert r._commit_sha_of_tree("tree") is None


def test_commit_sha_of_tag():
    r = _repo()
    r._repo.get_git_ref = Mock()
    r._repo.get_git_ref.return_value.object.type = "commit"
    r._repo.get_git_ref.return_value.object.sha = "c"
    assert r._commit_sha_of_tag("v1.2.3") == "c"
    r._repo.get_git_ref.assert_called_with("tags/v1.2.3")
    r._repo.get_git_ref.return_value.object.type = "tag"
    r._repo.get_git_tag = Mock()
    r._repo.get_git_tag.return_value.object.sha = "t"
    assert r._commit_sha_of_tag("v2.3.4") == "t"
    r._repo.get_git_tag.assert_called_with("c")
    r._repo.get_git_ref.return_value.object = None
    assert r._commit_sha_of_tag("v3.4.5") is None
    r._repo.get_git_ref.side_effect = UnknownObjectException(404, "???")
    assert r._commit_sha_of_tag("v4.5.6") is None


def test_commit_sha_of_release_branch():
    r = _repo()
    r._repo = Mock(default_branch="a")
    r._repo.get_branch.return_value.commit.sha = "sha"
    assert r._commit_sha_of_release_branch() == "sha"
    r._repo.get_branch.assert_called_with("a")


@patch("tagbot.action.repo.logger")
def test_filter_map_versions(logger):
    r = _repo()
    r._commit_sha_from_registry_pr = Mock(return_value=None)
    r._commit_sha_of_tree = Mock(return_value=None)
    assert not r._filter_map_versions({"1.2.3": "tree1"})
    logger.warning.assert_called_with(
        "No matching commit was found for version v1.2.3 (tree1)"
    )
    r._commit_sha_of_tree.return_value = "sha"
    r._commit_sha_of_tag = Mock(return_value="sha")
    assert not r._filter_map_versions({"2.3.4": "tree2"})
    logger.info.assert_called_with("Tag v2.3.4 already exists")
    r._commit_sha_of_tag.return_value = "abc"
    assert not r._filter_map_versions({"3.4.5": "tree3"})
    logger.error.assert_called_with(
        "Existing tag v3.4.5 points at the wrong commit (expected sha)"
    )
    r._commit_sha_of_tag.return_value = None
    assert r._filter_map_versions({"4.5.6": "tree4"}) == {"v4.5.6": "sha"}


@patch("tagbot.action.repo.logger")
def test_versions(logger):
    r = _repo()
    r._Repo__registry_path = "path"
    r._registry = Mock()
    r._registry.get_contents.return_value.decoded_content = b"""
    ["1.2.3"]
    git-tree-sha1 = "abc"

    ["2.3.4"]
    git-tree-sha1 = "bcd"
    """
    assert r._versions() == {"1.2.3": "abc", "2.3.4": "bcd"}
    r._registry.get_contents.assert_called_with("path/Versions.toml")
    logger.debug.assert_not_called()
    commit = Mock()
    commit.commit.sha = "abcdef"
    r._registry.get_commits.return_value = [commit]
    delta = timedelta(days=3)
    assert r._versions(min_age=delta) == {"1.2.3": "abc", "2.3.4": "bcd"}
    r._registry.get_commits.assert_called_once()
    assert len(r._registry.get_commits.mock_calls) == 1
    [c] = r._registry.get_commits.mock_calls
    assert not c.args and len(c.kwargs) == 1 and "until" in c.kwargs
    assert isinstance(c.kwargs["until"], datetime)
    r._registry.get_contents.assert_called_with("path/Versions.toml", ref="abcdef")
    logger.debug.assert_not_called()
    r._registry.get_commits.return_value = []
    assert r._versions(min_age=delta) == {}
    logger.debug.assert_called_with("No registry commits were found")
    r._registry.get_contents.side_effect = UnknownObjectException(404, "???")
    assert r._versions() == {}
    logger.debug.assert_called_with("Versions.toml was not found ({})")
    r._Repo__registry_path = Mock(__bool__=lambda self: False)
    assert r._versions() == {}
    logger.debug.assert_called_with("Package is not registered")


def test_run_url():
    r = _repo()
    r._repo = Mock(html_url="https://github.com/Foo/Bar")
    with patch.dict(os.environ, {"GITHUB_RUN_ID": "123"}):
        assert r._run_url() == "https://github.com/Foo/Bar/actions/runs/123"
    with patch.dict(os.environ, clear=True):
        assert r._run_url() == "https://github.com/Foo/Bar/actions"


@patch("tagbot.action.repo.logger")
@patch("docker.from_env")
def test_image_id(from_env, logger):
    r = _repo()
    from_env.return_value.containers.get.return_value.image.id = "sha"
    with patch.dict(os.environ, {"HOSTNAME": "foo"}):
        assert r._image_id() == "sha"
    with patch.dict(os.environ, clear=True):
        assert r._image_id() == "Unknown"
    logger.warning.assert_called_with("HOSTNAME is not set")


@patch("requests.post")
def test_report_error(post):
    post.return_value.json.return_value = {"status": "ok"}
    r = _repo(token="x")
    r._repo = Mock(full_name="Foo/Bar", private=True)
    r._image_id = Mock(return_value="id")
    r._run_url = Mock(return_value="url")
    r._report_error("ahh")
    post.assert_not_called()
    r._repo.private = False
    with patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}):
        r._report_error("ahh")
    post.assert_not_called()
    with patch.dict(os.environ, {}, clear=True):
        r._report_error("ahh")
    post.assert_not_called()
    with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
        r._report_error("ahh")
    post.assert_called_with(
        f"{TAGBOT_WEB}/report",
        json={"image": "id", "repo": "Foo/Bar", "run": "url", "stacktrace": "ahh"},
    )


def test_is_registered():
    r = _repo(github="gh.com")
    r._repo = Mock(full_name="Foo/Bar.jl")
    r._Repo__registry_path = Mock(__bool__=lambda self: False)
    r._registry.get_contents = Mock()
    contents = r._registry.get_contents.return_value
    contents.decoded_content = b"""repo = "https://gh.com/Foo/Bar.jl.git"\n"""
    assert not r.is_registered()
    r._registry.get_contents.assert_not_called()
    r._Repo__registry_path = "path"
    assert r.is_registered()
    r._registry.get_contents.assert_called_with("path/Package.toml")
    contents.decoded_content = b"""repo = "https://gh.com/Foo/Bar.jl"\n"""
    assert r.is_registered()
    contents.decoded_content = b"""repo = "https://gitlab.com/Foo/Bar.jl.git"\n"""
    assert not r.is_registered()
    contents.decoded_content = b"""repo = "git@gh.com:Foo/Bar.jl.git"\n"""
    assert r.is_registered()
    contents.decoded_content = b"""repo = "git@github.com:Foo/Bar.jl.git"\n"""
    assert not r.is_registered()
    # TODO: We should test for the InvalidProject behaviour,
    # but I'm not really sure how it's possible.


def test_new_versions():
    r = _repo()
    r._versions = (
        lambda min_age=None: {"1.2.3": "abc"}
        if min_age
        else {"1.2.3": "abc", "3.4.5": "cde", "2.3.4": "bcd"}
    )
    r._filter_map_versions = lambda vs: vs
    assert list(r.new_versions().items()) == [("2.3.4", "bcd"), ("3.4.5", "cde")]


def test_create_dispatch_event():
    r = _repo()
    r._repo = Mock(full_name="Foo/Bar")
    r.create_dispatch_event({"a": "b", "c": "d"})
    r._repo.create_repository_dispatch.assert_called_once_with(
        "TagBot", {"a": "b", "c": "d"}
    )


@patch("tagbot.action.repo.mkstemp", side_effect=[(0, "abc"), (0, "xyz")] * 3)
@patch("os.chmod")
@patch("subprocess.run")
@patch("pexpect.spawn")
def test_configure_ssh(spawn, run, chmod, mkstemp):
    r = _repo(github="gh.com", repo="foo")
    r._repo = Mock(ssh_url="sshurl")
    r._git.set_remote_url = Mock()
    r._git.config = Mock()
    open = mock_open()
    with patch("builtins.open", open):
        r.configure_ssh(" BEGIN OPENSSH PRIVATE KEY ", None)
    r._git.set_remote_url.assert_called_with("sshurl")
    open.assert_has_calls(
        [call("abc", "w"), call("xyz", "w")], any_order=True,
    )
    open.return_value.write.assert_called_with("BEGIN OPENSSH PRIVATE KEY\n")
    run.assert_called_with(
        ["ssh-keyscan", "-t", "rsa", "gh.com"],
        check=True,
        stdout=open.return_value,
        stderr=DEVNULL,
    )
    chmod.assert_called_with("abc", S_IREAD)
    r._git.config.assert_called_with(
        "core.sshCommand", "ssh -i abc -o UserKnownHostsFile=xyz",
    )
    with patch("builtins.open", open):
        r.configure_ssh("Zm9v", None)
    open.return_value.write.assert_any_call("foo\n")
    spawn.assert_not_called()
    run.return_value.stdout = """
    VAR1=value; export VAR1;
    VAR2=123; export VAR2;
    echo Agent pid 123;
    """
    with patch("builtins.open", open):
        r.configure_ssh("Zm9v", "mypassword")
    open.return_value.write.assert_called_with("foo\n")
    run.assert_called_with(["ssh-agent"], check=True, text=True, capture_output=True)
    assert os.getenv("VAR1") == "value"
    assert os.getenv("VAR2") == "123"
    spawn.assert_called_with("ssh-add abc")
    calls = [
        call.expect("Enter passphrase"),
        call.sendline("mypassword"),
        call.expect("Identity added"),
    ]
    spawn.return_value.assert_has_calls(calls)


@patch("tagbot.action.repo.GPG")
@patch("tagbot.action.repo.mkdtemp", return_value="gpgdir")
@patch("os.chmod")
def test_configure_gpg(chmod, mkdtemp, GPG):
    r = _repo()
    r._git.config = Mock()
    gpg = GPG.return_value
    gpg.import_keys.return_value = Mock(sec_imported=1, fingerprints=["k"], stderr="e")
    r.configure_gpg("BEGIN PGP PRIVATE KEY", None)
    assert os.getenv("GNUPGHOME") == "gpgdir"
    chmod.assert_called_with("gpgdir", S_IREAD | S_IWRITE | S_IEXEC)
    GPG.assert_called_with(gnupghome="gpgdir", use_agent=True)
    gpg.import_keys.assert_called_with("BEGIN PGP PRIVATE KEY")
    calls = [call("user.signingKey", "k"), call("tag.gpgSign", "true")]
    r._git.config.assert_has_calls(calls)
    r.configure_gpg("Zm9v", None)
    gpg.import_keys.assert_called_with("foo")
    gpg.sign.return_value = Mock(status="signature created")
    r.configure_gpg("Zm9v", "mypassword")
    gpg.sign.assert_called_with("test", passphrase="mypassword")
    gpg.sign.return_value = Mock(status=None, stderr="e")
    with pytest.raises(Abort):
        r.configure_gpg("Zm9v", "mypassword")
    gpg.import_keys.return_value.sec_imported = 0
    with pytest.raises(Abort):
        r.configure_gpg("Zm9v", None)


def test_handle_release_branch():
    r = _repo()
    r._create_release_branch_pr = Mock()
    r._git = Mock(
        fetch_branch=Mock(side_effect=[False, True, True, True, True]),
        is_merged=Mock(side_effect=[True, False, False, False]),
        can_fast_forward=Mock(side_effect=[True, False, False]),
    )
    r._pr_exists = Mock(side_effect=[True, False])
    r.handle_release_branch("v1")
    r._git.fetch_branch.assert_called_with("release-1")
    r._git.is_merged.assert_not_called()
    r.handle_release_branch("v2")
    r._git.is_merged.assert_called_with("release-2")
    r._git.can_fast_forward.assert_not_called()
    r.handle_release_branch("v3")
    r._git.merge_and_delete_branch.assert_called_with("release-3")
    r._pr_exists.assert_not_called()
    r.handle_release_branch("v4")
    r._pr_exists.assert_called_with("release-4")
    r._create_release_branch_pr.assert_not_called()
    r.handle_release_branch("v5")
    r._create_release_branch_pr.assert_called_with("v5", "release-5")


def test_create_release():
    r = _repo(user="user", email="email")
    r._commit_sha_of_release_branch = Mock(return_value="a")
    r._git.create_tag = Mock()
    r._repo = Mock(default_branch="default")
    r._repo.create_git_tag.return_value.sha = "t"
    r._changelog.get = Mock(return_value="l")
    r.create_release("v1", "a")
    r._git.create_tag.assert_not_called()
    # InputGitAuthor doesn't support equality so we can't use a normal
    # assert_called_with here.
    r._repo.create_git_tag.assert_called_once()
    call = r._repo.create_git_tag.mock_calls[0]
    assert call.args == ("v1", "l", "a", "commit")
    assert len(call.kwargs) == 1 and "tagger" in call.kwargs
    tagger = call.kwargs["tagger"]
    assert isinstance(tagger, InputGitAuthor) and tagger._identity == {
        "name": "user",
        "email": "email",
    }
    r._repo.create_git_ref.assert_called_with("refs/tags/v1", "t")
    r._repo.create_git_release.assert_called_with(
        "v1", "v1", "l", target_commitish="default"
    )
    r.create_release("v1", "b")
    r._repo.create_git_release.assert_called_with("v1", "v1", "l", target_commitish="b")
    r._ssh = True
    r.create_release("v1", "c")
    r._git.create_tag.assert_called_with("v1", "c", "l")


@patch("traceback.format_exc", return_value="ahh")
@patch("tagbot.action.repo.logger")
def test_handle_error(logger, format_exc):
    r = _repo()
    r._report_error = Mock(side_effect=[None, RuntimeError("!")])
    r.handle_error(RequestException())
    r._report_error.assert_not_called()
    r.handle_error(GithubException(502, "oops"))
    r._report_error.assert_not_called()
    r.handle_error(GithubException(404, "???"))
    r._report_error.assert_called_with("ahh")
    r.handle_error(RuntimeError("?"))
    r._report_error.assert_called_with("ahh")
    logger.error.assert_called_with("Issue reporting failed")


def test_commit_sha_of_version():
    r = _repo()
    r._Repo__registry_path = ""
    r._registry.get_contents = Mock(
        return_value=Mock(decoded_content=b"""["3.4.5"]\ngit-tree-sha1 = "abc"\n""")
    )
    r._commit_sha_of_tree = Mock(return_value="def")
    assert r.commit_sha_of_version("v1.2.3") is None
    r._registry.get_contents.assert_not_called()
    r._Repo__registry_path = "path"
    assert r.commit_sha_of_version("v2.3.4") is None
    r._registry.get_contents.assert_called_with("path/Versions.toml")
    r._commit_sha_of_tree.assert_not_called()
    assert r.commit_sha_of_version("v3.4.5") == "def"
    r._commit_sha_of_tree.assert_called_with("abc")
