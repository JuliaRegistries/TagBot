import datetime
from unittest.mock import Mock

from tagbot.action.gitlab import ProjectWrapper


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


def test_get_commit_wraps_date():
    proj = Mock()
    c = Mock()
    c.committed_date = datetime.datetime(2023, 1, 3)
    proj.commits.get.return_value = c
    proj.attributes = {"default_branch": "main", "namespace": {"path": "owner"}}
    pw = ProjectWrapper(proj)
    commit = pw.get_commit("abc")
    assert commit.commit.author.date == datetime.datetime(2023, 1, 3)
