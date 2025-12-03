import datetime
from unittest.mock import Mock

import pytest

from tagbot.action.gitlab import (
    GitlabException,
    ProjectWrapper,
    UnknownObjectException,
)


def test_get_releases_returns_list():
    proj = Mock()
    r1 = Mock()
    r1.tag_name = "v1"
    r1.created_at = "2020-01-01T00:00:00Z"
    proj.releases.list.return_value = [r1]
    proj.attributes = {"default_branch": "main", "namespace": {"path": "owner"}}
    pw = ProjectWrapper(proj)
    rels = pw.get_releases()
    assert len(rels) == 1
    assert rels[0].tag_name == "v1"


def test_get_issues_combines_issues_and_merged_mrs():
    proj = Mock()
    # issue
    i = Mock()
    i.closed_at = datetime.datetime(2023, 1, 1)
    i.labels = ["bug"]
    i.author = {"username": "alice"}
    i.description = "issue body"
    i.iid = 5
    i.title = "Issue"
    i.web_url = "https://gitlab/issue/5"
    proj.issues.list.return_value = [i]
    # merged MR
    m = Mock()
    m.merged_at = datetime.datetime(2023, 1, 2)
    m.labels = ["enhancement"]
    m.author = {"username": "bob"}
    m.description = "mr body"
    m.iid = 6
    m.title = "MR"
    m.web_url = "https://gitlab/mr/6"
    proj.mergerequests.list.return_value = [m]
    proj.attributes = {"default_branch": "main", "namespace": {"path": "owner"}}
    pw = ProjectWrapper(proj)
    items = pw.get_issues(state="closed", since=None)
    # should contain issue and MR-as-PR
    assert any(not it.pull_request for it in items)
    assert any(hasattr(it, "as_pull_request") for it in items if it.pull_request)
    # check labels are passed through
    issue_item = next(it for it in items if not it.pull_request)
    assert issue_item.labels[0].name == "bug"
    mr_item = next(it for it in items if it.pull_request)
    assert mr_item.labels[0].name == "enhancement"


def test_get_commit_wraps_date():
    proj = Mock()
    c = Mock()
    c.committed_date = datetime.datetime(2023, 1, 3)
    proj.commits.get.return_value = c
    proj.attributes = {"default_branch": "main", "namespace": {"path": "owner"}}
    pw = ProjectWrapper(proj)
    commit = pw.get_commit("abc")
    assert commit.commit.author.date == datetime.datetime(2023, 1, 3)


def test_private_property():
    proj = Mock()
    proj.attributes = {"default_branch": "main", "namespace": {"path": "owner"}}
    proj.visibility = "public"
    pw = ProjectWrapper(proj)
    assert pw.private is False

    proj.visibility = "private"
    pw = ProjectWrapper(proj)
    assert pw.private is True

    proj.visibility = "internal"
    pw = ProjectWrapper(proj)
    assert pw.private is True


def test_full_name_and_urls():
    proj = Mock()
    proj.attributes = {"default_branch": "main", "namespace": {"path": "owner"}}
    proj.path_with_namespace = "owner/repo"
    proj.ssh_url_to_repo = "git@gitlab.com:owner/repo.git"
    proj.web_url = "https://gitlab.com/owner/repo"
    pw = ProjectWrapper(proj)
    assert pw.full_name == "owner/repo"
    assert pw.ssh_url == "git@gitlab.com:owner/repo.git"
    assert pw.html_url == "https://gitlab.com/owner/repo"


def test_get_branches():
    proj = Mock()
    proj.attributes = {"default_branch": "main", "namespace": {"path": "owner"}}
    b1 = Mock()
    b1.name = "main"
    b1.commit = {"id": "abc123"}
    b2 = Mock()
    b2.name = "feature"
    b2.commit = {"id": "def456"}
    proj.branches.list.return_value = [b1, b2]
    pw = ProjectWrapper(proj)
    branches = pw.get_branches()
    assert len(branches) == 2
    assert branches[0].name == "main"
    assert branches[0].commit.sha == "abc123"
    assert branches[1].name == "feature"


def test_get_git_ref_tag():
    proj = Mock()
    proj.attributes = {"default_branch": "main", "namespace": {"path": "owner"}}
    tag = Mock()
    tag.commit = {"id": "abc123"}
    proj.tags.get.return_value = tag
    pw = ProjectWrapper(proj)
    ref = pw.get_git_ref("tags/v1.0.0")
    assert ref.object.type == "tag"
    assert ref.object.sha == "abc123"


def test_get_git_ref_branch():
    proj = Mock()
    proj.attributes = {"default_branch": "main", "namespace": {"path": "owner"}}
    branch = Mock()
    branch.commit = {"id": "def456"}
    proj.branches.get.return_value = branch
    pw = ProjectWrapper(proj)
    ref = pw.get_git_ref("main")
    assert ref.object.type == "commit"
    assert ref.object.sha == "def456"


def test_get_git_ref_not_found():
    proj = Mock()
    proj.attributes = {"default_branch": "main", "namespace": {"path": "owner"}}
    proj.tags.get.side_effect = Exception("not found")
    pw = ProjectWrapper(proj)
    with pytest.raises(UnknownObjectException):
        pw.get_git_ref("tags/nonexistent")


def test_get_git_tag():
    proj = Mock()
    proj.attributes = {"default_branch": "main", "namespace": {"path": "owner"}}
    pw = ProjectWrapper(proj)
    tag = pw.get_git_tag("abc123")
    assert tag.object.sha == "abc123"


def test_get_branch():
    proj = Mock()
    proj.attributes = {"default_branch": "main", "namespace": {"path": "owner"}}
    branch = Mock()
    branch.commit = {"id": "abc123"}
    proj.branches.get.return_value = branch
    pw = ProjectWrapper(proj)
    b = pw.get_branch("main")
    assert b.commit.sha == "abc123"


def test_get_branch_not_found():
    proj = Mock()
    proj.attributes = {"default_branch": "main", "namespace": {"path": "owner"}}
    proj.branches.get.side_effect = Exception("not found")
    pw = ProjectWrapper(proj)
    with pytest.raises(UnknownObjectException):
        pw.get_branch("nonexistent")


def test_get_commits():
    proj = Mock()
    proj.attributes = {"default_branch": "main", "namespace": {"path": "owner"}}
    c1 = Mock()
    c1.id = "abc123"
    c1.tree_id = "tree1"
    c2 = Mock()
    c2.id = "def456"
    c2.tree_id = "tree2"
    proj.commits.list.return_value = [c1, c2]
    pw = ProjectWrapper(proj)
    commits = list(pw.get_commits(sha="main"))
    assert len(commits) == 2
    assert commits[0].sha == "abc123"
    assert commits[0].commit.tree.sha == "tree1"


def test_create_git_release():
    proj = Mock()
    proj.attributes = {"default_branch": "main", "namespace": {"path": "owner"}}
    rel = Mock()
    proj.releases.create.return_value = rel
    pw = ProjectWrapper(proj)
    result = pw.create_git_release("v1.0.0", "Version 1.0.0", "Release notes")
    assert result is rel
    proj.releases.create.assert_called_once_with(
        {
            "name": "Version 1.0.0",
            "tag_name": "v1.0.0",
            "description": "Release notes",
        }
    )


def test_create_git_release_with_target():
    proj = Mock()
    proj.attributes = {"default_branch": "main", "namespace": {"path": "owner"}}
    rel = Mock()
    proj.releases.create.return_value = rel
    pw = ProjectWrapper(proj)
    pw.create_git_release("v1.0.0", "Version 1.0.0", "Notes", target_commitish="abc123")
    proj.releases.create.assert_called_once_with(
        {
            "name": "Version 1.0.0",
            "tag_name": "v1.0.0",
            "description": "Notes",
            "ref": "abc123",
        }
    )


def test_create_git_release_draft_raises():
    proj = Mock()
    proj.attributes = {"default_branch": "main", "namespace": {"path": "owner"}}
    pw = ProjectWrapper(proj)
    with pytest.raises(GitlabException, match="Draft releases are not supported"):
        pw.create_git_release("v1.0.0", "Version 1.0.0", "Notes", draft=True)


def test_create_repository_dispatch_logs_warning(caplog):
    proj = Mock()
    proj.attributes = {"default_branch": "main", "namespace": {"path": "owner"}}
    pw = ProjectWrapper(proj)
    pw.create_repository_dispatch("TagBot", {"version": "1.0.0"})
    assert "not supported on GitLab" in caplog.text


def test_get_contents_raw_fallback():
    proj = Mock()
    proj.attributes = {"default_branch": "main", "namespace": {"path": "owner"}}
    # First call returns file without content attribute
    file_obj = Mock(spec=[])  # No content attribute
    proj.files.get.return_value = file_obj
    proj.files.raw.return_value = b"raw content"
    pw = ProjectWrapper(proj)
    contents = pw.get_contents("README.md")
    assert contents.decoded_content == b"raw content"
