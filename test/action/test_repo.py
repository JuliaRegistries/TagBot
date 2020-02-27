import os

from datetime import datetime, timedelta
from stat import S_IREAD, S_IWRITE, S_IEXEC
from subprocess import DEVNULL
from unittest.mock import Mock, call, mock_open, patch

import pytest

from github import UnknownObjectException

from tagbot.action import TAGBOT_WEB, Abort
from tagbot.action.repo import Repo


def _repo(
    *,
    repo="",
    registry="",
    token="",
    changelog="",
    ignore=[],
    ssh=False,
    gpg=False,
    lookback=3,
):
    return Repo(
        repo=repo,
        registry=registry,
        token=token,
        changelog=changelog,
        changelog_ignore=ignore,
        ssh=ssh,
        gpg=gpg,
        lookback=lookback,
    )


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
    with pytest.raises(Abort):
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


def test_maybe_b64():
    r = _repo()
    assert r._maybe_b64("foo bar") == "foo bar"
    assert r._maybe_b64("Zm9v") == "foo"


def test_create_release_branch_pr():
    r = _repo()
    r._repo = Mock(default_branch="default")
    r._create_release_branch_pr("v1.2.3", "branch")
    r._repo.create_pull.assert_called_once_with(
        title="Merge release branch for v1.2.3", body="", head="branch", base="default",
    )


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
    r._repo.get_git_ref.side_effect = UnknownObjectException(404, "???")
    assert r._commit_sha_of_tag("v3.4.5") is None


@patch("tagbot.action.repo.error")
@patch("tagbot.action.repo.warn")
@patch("tagbot.action.repo.info")
def test_filter_map_versions(info, warn, error):
    r = _repo()
    r._commit_sha_of_tree = Mock(return_value=None)
    assert not r._filter_map_versions({"1.2.3": "tree1"})
    warn.assert_called_with("No matching commit was found for version v1.2.3 (tree1)")
    r._commit_sha_of_tree.return_value = "sha"
    r._commit_sha_of_tag = Mock(return_value="sha")
    assert not r._filter_map_versions({"2.3.4": "tree2"})
    info.assert_called_with("Tag v2.3.4 already exists")
    r._commit_sha_of_tag.return_value = "abc"
    assert not r._filter_map_versions({"3.4.5": "tree3"})
    error.assert_called_with(
        "Existing tag v3.4.5 points at the wrong commit (expected sha)"
    )
    r._commit_sha_of_tag.return_value = None
    assert r._filter_map_versions({"4.5.6": "tree4"}) == {"v4.5.6": "sha"}


@patch("tagbot.action.repo.debug")
def test_versions(debug):
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
    debug.assert_not_called()
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
    debug.assert_not_called()
    r._registry.get_commits.return_value = []
    assert r._versions(min_age=delta) == {}
    debug.assert_called_with("No registry commits were found")
    r._registry.get_contents.side_effect = UnknownObjectException(0, 0)
    assert r._versions() == {}
    debug.assert_called_with("Versions.toml was not found")


def test_run_url():
    r = _repo()
    r._repo = Mock(html_url="https://github.com/Foo/Bar")
    with patch.dict(os.environ, {"GITHUB_RUN_ID": "123"}):
        assert r._run_url() == "https://github.com/Foo/Bar/actions/runs/123"
    with patch.dict(os.environ, clear=True):
        assert r._run_url() == "https://github.com/Foo/Bar/actions"


@patch("tagbot.action.repo.warn")
@patch("docker.from_env")
def test_image_id(from_env, warn):
    r = _repo()
    from_env.return_value.containers.get.return_value.image.id = "sha"
    with patch.dict(os.environ, {"HOSTNAME": "foo"}):
        assert r._image_id() == "sha"
    with patch.dict(os.environ, clear=True):
        assert r._image_id() == "Unknown"
    warn.assert_called_with("HOSTNAME is not set")


def test_new_versions():
    r = _repo()
    r._Repo__lookback = timedelta(days=3)
    r._versions = (
        lambda min_age=None: {"1.2.3": "abc"}
        if min_age
        else {"1.2.3": "abc", "2.3.4": "bcd"}
    )
    r._filter_map_versions = lambda vs: vs
    assert r.new_versions() == {"2.3.4": "bcd"}


@patch("requests.post")
def test_create_dispatch_event(post):
    r = _repo(token="x")
    r._repo = Mock(full_name="Foo/Bar")
    r.create_dispatch_event({"a": "b", "c": "d"})
    post.assert_called_once_with(
        "https://api.github.com/repos/Foo/Bar/dispatches",
        headers={
            "Accept": "application/vnd.github.everest-preview+json",
            "Authorization": f"token x",
        },
        json={"event_type": "TagBot", "client_payload": {"a": "b", "c": "d"}},
    )


@patch("tagbot.action.repo.mkstemp", side_effect=[(0, "abc"), (0, "xyz")] * 3)
@patch("os.chmod")
@patch("subprocess.run")
@patch("pexpect.spawn")
def test_configure_ssh(spawn, run, chmod, mkstemp):
    r = _repo(repo="foo")
    r._repo = Mock(ssh_url="sshurl")
    r._git.set_remote_url = Mock()
    r._git.config = Mock()
    open = mock_open()
    with patch("builtins.open", open):
        r.configure_ssh(" sshkey ", None)
    r._git.set_remote_url.assert_called_with("sshurl")
    open.assert_has_calls(
        [call("abc", "w"), call("xyz", "w")], any_order=True,
    )
    open.return_value.write.assert_called_with("sshkey\n")
    run.assert_called_with(
        ["ssh-keyscan", "-t", "rsa", "github.com"],
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
        r.configure_ssh(" key ", "mypassword")
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
    r.configure_gpg("foo bar", None)
    assert os.getenv("GNUPGHOME") == "gpgdir"
    chmod.assert_called_with("gpgdir", S_IREAD | S_IWRITE | S_IEXEC)
    GPG.assert_called_with(gnupghome="gpgdir", use_agent=True)
    gpg.import_keys.assert_called_with("foo bar")
    calls = [
        call("user.signingKey", "k"),
        call("user.name", "github-actions[bot]"),
        call("user.email", "actions@github.com"),
        call("tag.gpgSign", "true"),
    ]
    r._git.config.assert_has_calls(calls)
    r.configure_gpg("Zm9v", None)
    gpg.import_keys.assert_called_with("foo")
    gpg.sign.return_value = Mock(status="signature created")
    r.configure_gpg("foo bar", "mypassword")
    gpg.sign.assert_called_with("test", passphrase="mypassword")
    gpg.sign.return_value = Mock(status=None, stderr="e")
    with pytest.raises(Abort):
        r.configure_gpg("foo bar", "mypassword")
    gpg.import_keys.return_value.sec_imported = 0
    with pytest.raises(Abort):
        r.configure_gpg("foo bar", None)


def test_handle_release_branch():
    r = _repo()
    r._create_release_branch_pr = Mock()
    r._git = Mock(
        fetch_branch=Mock(side_effect=[False, True, True]),
        can_fast_forward=Mock(side_effect=[True, False]),
    )
    r.handle_release_branch("v1")
    r._git.fetch_branch.assert_called_with("release-1")
    r._git.can_fast_forward.assert_not_called()
    r.handle_release_branch("v2")
    r._git.fetch_branch.assert_called_with("release-2")
    r._git.can_fast_forward.assert_called_with("release-2")
    r._git.merge_and_delete_branch.assert_called_with("release-2")
    r.handle_release_branch("v3")
    r._git.fetch_branch.assert_called_with("release-3")
    r._git.can_fast_forward.assert_called_with("release-3")
    r._create_release_branch_pr.assert_called_with("v3", "release-3")


def test_create_release():
    r = _repo()
    r._git.commit_sha_of_default = Mock(return_value="a")
    r._repo = Mock(default_branch="default")
    r._changelog.get = Mock(return_value="log")
    r._git.create_tag = Mock()
    r.create_release("v1.2.3", "a")
    r._repo.create_git_release.assert_called_with(
        "v1.2.3", "v1.2.3", "log", target_commitish="default",
    )
    r.create_release("v1.2.3", "b")
    r._repo.create_git_release.assert_called_with(
        "v1.2.3", "v1.2.3", "log", target_commitish="b",
    )
    r._git.create_tag.assert_not_called()
    r._ssh = True
    r.create_release("v1.2.3", "c")
    r._git.create_tag.assert_called_with("v1.2.3", "c", annotate=False)
    r._repo.create_git_release.assert_called_with(
        "v1.2.3", "v1.2.3", "log", target_commitish="c",
    )


@patch("requests.post")
def test_report_error(post):
    post.return_value.json.return_value = {"status": "ok"}
    r = _repo(token="x")
    r._repo = Mock(full_name="Foo/Bar")
    r._image_id = Mock(return_value="id")
    r._run_url = Mock(return_value="url")
    with patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}):
        r.report_error("ahh")
    post.assert_not_called()
    with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
        r.report_error("ahh")
    post.assert_called_with(
        f"{TAGBOT_WEB}/report",
        json={"image": "id", "repo": "Foo/Bar", "run": "url", "stacktrace": "ahh"},
    )
