import base64
from unittest.mock import Mock

import pytest

from tagbot.action.gitlab import ProjectWrapper, UnknownObjectException


def make_file_obj(content: str):
    b64 = base64.b64encode(content.encode()).decode("ascii")
    f = Mock()
    f.content = b64
    return f


def test_default_branch_and_owner():
    proj = Mock()
    proj.attributes = {"default_branch": "main", "namespace": {"path": "ownername"}}
    pw = ProjectWrapper(proj)
    assert pw.default_branch == "main"
    assert pw.owner.login == "ownername"


def test_get_pulls_filters_and_head():
    mr1 = Mock()
    mr1.source_branch = "feature-x"
    mr1.merged_at = None
    mr1.closed_at = None
    mr2 = Mock()
    mr2.source_branch = "feature-x"
    mr2.merged_at = "2023-01-01T00:00:00Z"
    mr2.closed_at = "2023-01-01T00:00:00Z"
    proj = Mock()
    proj.attributes = {"default_branch": "main", "namespace": {"path": "ownername"}}
    proj.mergerequests.list.return_value = [mr1, mr2]
    pw = ProjectWrapper(proj)
    prs = pw.get_pulls(head="ownername:feature-x", state="closed")
    assert len(prs) == 2
    assert prs[1].merged is True
    assert prs[0].head.ref == "feature-x"


def test_get_contents_and_git_blob_and_missing_blob():
    proj = Mock()
    proj.attributes = {"default_branch": "main", "namespace": {"path": "ownername"}}
    file_obj = make_file_obj("hello world")
    proj.files.get.return_value = file_obj
    pw = ProjectWrapper(proj)
    contents = pw.get_contents("Project.toml")
    assert contents.decoded_content == b"hello world"
    # ensure blob returned via fake sha
    fake_sha = f"gl-Project.toml-{pw.default_branch}"
    blob = pw.get_git_blob(fake_sha)
    assert blob.content == file_obj.content
    with pytest.raises(UnknownObjectException):
        pw.get_git_blob("no-such-sha")


def test_create_pull_calls_project():
    proj = Mock()
    proj.attributes = {"default_branch": "main", "namespace": {"path": "ownername"}}
    mr = Mock()
    proj.mergerequests.create.return_value = mr
    pw = ProjectWrapper(proj)
    got = pw.create_pull("Title", "Body", "branch-a", "main")
    assert got is mr
    proj.mergerequests.create.assert_called_once()
