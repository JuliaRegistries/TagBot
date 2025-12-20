import pytest

from unittest.mock import Mock, patch

from tagbot.action import Abort
from tagbot.action.repo import Repo


def _repo(
    *,
    repo="",
    registry="",
    github="",
    github_api="",
    token="x",
    changelog="",
    ignore=None,
    ssh=False,
    gpg=False,
    draft=False,
    registry_ssh="",
    user="",
    email="",
    branch=None,
    subdir=None,
    tag_prefix=None,
):
    return Repo(
        repo=repo,
        registry=registry,
        github=github,
        github_api=github_api,
        token=token,
        changelog=changelog,
        changelog_ignore=ignore if ignore is not None else [],
        ssh=ssh,
        gpg=gpg,
        draft=draft,
        registry_ssh=registry_ssh,
        user=user,
        email=email,
        branch=branch,
        subdir=subdir,
        tag_prefix=tag_prefix,
    )


@patch("tagbot.action.repo.GitlabClient")
def test_constructor_gitlab_initializes_client(mock_gitlab_client):
    # Ensure that when a GitLab host is detected, GitlabClient is called
    mock_gl_instance = Mock()
    mock_gitlab_client.return_value = mock_gl_instance
    mock_gl_instance.get_repo.return_value = Mock()

    r = _repo(github="gitlab.com", github_api="gitlab.com", registry="test/registry")

    # GitlabClient should have been instantiated
    mock_gitlab_client.assert_called_once()
    assert r._gh is mock_gl_instance


@patch("tagbot.action.repo.GitlabClient")
def test_constructor_gitlab_detection_by_api_host(mock_gitlab_client):
    # Detection should work when the api host contains 'gitlab'
    mock_gl_instance = Mock()
    mock_gitlab_client.return_value = mock_gl_instance
    mock_gl_instance.get_repo.return_value = Mock()

    r = _repo(
        github="example.com", github_api="https://gitlab.example.com", registry="reg"
    )

    mock_gitlab_client.assert_called_once()
    assert r._gh is mock_gl_instance


def test_constructor_raises_when_python_gitlab_missing():
    # Temporarily ensure GitlabClient is not available
    with patch("tagbot.action.repo.GitlabClient", new=None):
        with pytest.raises(Abort):
            _repo(github="gitlab.com", github_api="gitlab.com", registry="reg")
