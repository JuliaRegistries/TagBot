"""Tests for auto-generated changelog feature (issue #216)."""

from unittest.mock import Mock, patch

import pytest

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
    auto_changelog=False,
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
        auto_changelog=auto_changelog,
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


@patch("tagbot.action.repo.Github")
def test_auto_changelog_disabled_by_default(mock_github):
    """Test that auto_changelog is False by default."""
    mock_gh_instance = Mock()
    mock_github.return_value = mock_gh_instance
    mock_gh_instance.get_repo.return_value = Mock()

    r = _repo(repo="test/repo", registry="test/registry")
    assert r._auto_changelog is False
    assert r._changelog is not None


@patch("tagbot.action.repo.Github")
def test_auto_changelog_enabled(mock_github):
    """Test that auto_changelog can be enabled."""
    mock_gh_instance = Mock()
    mock_github.return_value = mock_gh_instance
    mock_gh_instance.get_repo.return_value = Mock()

    r = _repo(repo="test/repo", registry="test/registry", auto_changelog=True)
    assert r._auto_changelog is True
    assert r._changelog is None


@patch("tagbot.action.repo.Github")
def test_create_release_with_auto_changelog(mock_github, logger):
    """Test that create_release uses GitHub's auto-generated notes when enabled."""
    mock_gh_instance = Mock()
    mock_github.return_value = mock_gh_instance

    mock_repo = Mock()
    mock_gh_instance.get_repo.return_value = mock_repo
    mock_repo.get_releases.return_value = []

    r = _repo(repo="test/repo", registry="test/registry", auto_changelog=True)
    r._git = Mock()
    r._git.create_tag = Mock()

    r.create_release("v1.0.0", "abc123")

    # Verify create_git_release was called with generate_release_notes=True
    mock_repo.create_git_release.assert_called_once()
    call_args = mock_repo.create_git_release.call_args
    assert call_args.kwargs["generate_release_notes"] is True
    # Body should be empty when using auto-generated notes
    assert call_args.args[2] == ""


@patch("tagbot.action.repo.Github")
def test_create_release_with_custom_changelog(mock_github, logger):
    """Test that create_release uses custom changelog when auto_changelog is False."""
    mock_gh_instance = Mock()
    mock_github.return_value = mock_gh_instance

    mock_repo = Mock()
    mock_gh_instance.get_repo.return_value = mock_repo
    mock_repo.get_releases.return_value = []

    r = _repo(repo="test/repo", registry="test/registry", auto_changelog=False)
    r._git = Mock()
    r._git.create_tag = Mock()

    # Mock the changelog generation
    r._changelog = Mock()
    r._changelog.get = Mock(return_value="Custom changelog content")

    r.create_release("v1.0.0", "abc123")

    # Verify changelog.get was called
    r._changelog.get.assert_called_once_with("v1.0.0", "abc123")

    # Verify create_git_release was called with generate_release_notes=False
    mock_repo.create_git_release.assert_called_once()
    call_args = mock_repo.create_git_release.call_args
    assert call_args.kwargs["generate_release_notes"] is False
    # Body should contain custom changelog
    assert call_args.args[2] == "Custom changelog content"


@patch("tagbot.action.repo.Github")
def test_auto_changelog_logging(mock_github, logger, caplog):
    """Test that auto_changelog logs appropriate message."""
    mock_gh_instance = Mock()
    mock_github.return_value = mock_gh_instance

    mock_repo = Mock()
    mock_gh_instance.get_repo.return_value = mock_repo
    mock_repo.get_releases.return_value = []

    r = _repo(repo="test/repo", registry="test/registry", auto_changelog=True)
    r._git = Mock()
    r._git.create_tag = Mock()

    r.create_release("v1.0.0", "abc123")

    # Check that the log message about auto-generated notes was logged
    assert "Using GitHub auto-generated release notes" in caplog.text
