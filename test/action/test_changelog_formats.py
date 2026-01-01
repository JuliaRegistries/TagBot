"""Tests for multiple changelog format support (issues #216, #402)."""

from unittest.mock import Mock, patch

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
    changelog_format="custom",
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
        changelog_format=changelog_format,
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
def test_changelog_format_custom_by_default(mock_github):
    """Test that changelog_format is 'custom' by default."""
    mock_gh_instance = Mock()
    mock_github.return_value = mock_gh_instance
    mock_gh_instance.get_repo.return_value = Mock()

    r = _repo(repo="test/repo", registry="test/registry")
    assert r._changelog_format == "custom"
    assert r._changelog is not None


@patch("tagbot.action.repo.Github")
def test_changelog_format_github(mock_github):
    """Test that changelog_format can be set to 'github'."""
    mock_gh_instance = Mock()
    mock_github.return_value = mock_gh_instance
    mock_gh_instance.get_repo.return_value = Mock()

    r = _repo(repo="test/repo", registry="test/registry", changelog_format="github")
    assert r._changelog_format == "github"
    assert r._changelog is None


@patch("tagbot.action.repo.Github")
def test_changelog_format_conventional(mock_github):
    """Test that changelog_format can be set to 'conventional'."""
    mock_gh_instance = Mock()
    mock_github.return_value = mock_gh_instance
    mock_gh_instance.get_repo.return_value = Mock()

    r = _repo(
        repo="test/repo", registry="test/registry", changelog_format="conventional"
    )
    assert r._changelog_format == "conventional"
    assert r._changelog is None


@patch("tagbot.action.repo.logger")
@patch("tagbot.action.repo.Github")
def test_create_release_with_github_format(mock_github, mock_logger):
    """Test that create_release uses GitHub's auto-generated notes with github format."""
    mock_gh_instance = Mock()
    mock_github.return_value = mock_gh_instance

    mock_repo = Mock()
    mock_gh_instance.get_repo.return_value = mock_repo
    mock_repo.get_releases.return_value = []

    r = _repo(repo="test/repo", registry="test/registry", changelog_format="github")
    r._git = Mock()
    r._git.create_tag = Mock()

    r.create_release("v1.0.0", "abc123")

    # Verify create_git_release was called with generate_release_notes=True
    mock_repo.create_git_release.assert_called_once()
    call_args = mock_repo.create_git_release.call_args
    assert call_args.kwargs["generate_release_notes"] is True
    # Body should be empty when using auto-generated notes
    assert call_args.args[2] == ""


@patch("tagbot.action.repo.logger")
@patch("tagbot.action.repo.Github")
def test_create_release_with_custom_format(mock_github, mock_logger):
    """Test that create_release uses custom changelog with custom format."""
    mock_gh_instance = Mock()
    mock_github.return_value = mock_gh_instance

    mock_repo = Mock()
    mock_gh_instance.get_repo.return_value = mock_repo
    mock_repo.get_releases.return_value = []

    r = _repo(repo="test/repo", registry="test/registry", changelog_format="custom")
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


@patch("tagbot.action.repo.logger")
@patch("tagbot.action.repo.Github")
def test_create_release_with_conventional_format(mock_github, mock_logger):
    """Test that create_release generates conventional commits changelog."""
    mock_gh_instance = Mock()
    mock_github.return_value = mock_gh_instance

    mock_repo = Mock()
    mock_gh_instance.get_repo.return_value = mock_repo
    mock_repo.get_releases.return_value = []
    mock_repo.full_name = "test/repo"

    r = _repo(
        repo="test/repo", registry="test/registry", changelog_format="conventional"
    )
    r._git = Mock()
    r._git.create_tag = Mock()
    # Mock git log output with conventional commits
    r._git.command = Mock(
        return_value="feat: add new feature|abc123|johndoe\nfix: fix bug|def456|janedoe\nchore: update deps|ghi789|bob"
    )

    r.create_release("v1.0.0", "abc123")

    # Verify git command was called to get commits
    r._git.command.assert_called_once()

    # Verify create_git_release was called with generate_release_notes=False
    mock_repo.create_git_release.assert_called_once()
    call_args = mock_repo.create_git_release.call_args
    assert call_args.kwargs["generate_release_notes"] is False

    # Body should contain conventional changelog
    changelog_body = call_args.args[2]
    assert "## v1.0.0" in changelog_body
    assert "Features" in changelog_body or "feat:" in changelog_body
    assert "Bug Fixes" in changelog_body or "fix:" in changelog_body


@patch("tagbot.action.repo.Github")
def test_conventional_changelog_parsing(mock_github):
    """Test that conventional commits are parsed correctly through create_release.

    This tests the internal conventional changelog generation by calling through
    the public create_release method, making it more robust to internal refactoring.
    """
    mock_gh_instance = Mock()
    mock_github.return_value = mock_gh_instance

    mock_repo = Mock()
    mock_gh_instance.get_repo.return_value = mock_repo
    mock_repo.full_name = "test/repo"
    mock_repo.get_releases.return_value = []
    mock_repo.create_git_release = Mock()

    r = _repo(
        repo="test/repo", registry="test/registry", changelog_format="conventional"
    )
    r._git = Mock()
    r._git.create_tag = Mock()

    # Test various conventional commit formats
    r._git.command = Mock(
        return_value=(
            "feat(api): add new endpoint|abc123|dev1\n"
            "fix!: critical security fix|def456|dev2\n"
            "docs: update README|ghi789|dev3\n"
            "test: add unit tests|jkl012|dev4\n"
            "not conventional commit|mno345|dev5"
        )
    )

    r.create_release("v1.0.0", "abc123")

    # Verify create_git_release was called
    mock_repo.create_git_release.assert_called_once()

    # Check the generated changelog body
    call_args = mock_repo.create_git_release.call_args
    changelog = call_args.args[2]

    # Check structure
    assert "## v1.0.0" in changelog
    assert "Features" in changelog
    assert "Breaking Changes" in changelog or "fix!" in changelog
    assert "Documentation" in changelog
    assert "Tests" in changelog
    assert "Other Changes" in changelog


@patch("tagbot.action.repo.Github")
def test_github_format_logging(mock_github, caplog):
    """Test that github format logs appropriate message."""
    import logging

    caplog.set_level(logging.INFO)

    mock_gh_instance = Mock()
    mock_github.return_value = mock_gh_instance

    mock_repo = Mock()
    mock_gh_instance.get_repo.return_value = mock_repo
    mock_repo.get_releases.return_value = []

    r = _repo(repo="test/repo", registry="test/registry", changelog_format="github")
    r._git = Mock()
    r._git.create_tag = Mock()

    r.create_release("v1.0.0", "abc123")

    # Check that the log message about auto-generated notes was logged
    assert "Using GitHub auto-generated release notes" in caplog.text


@patch("tagbot.action.repo.Github")
def test_conventional_format_logging(mock_github, caplog):
    """Test that conventional format logs appropriate message."""
    import logging

    caplog.set_level(logging.INFO)

    mock_gh_instance = Mock()
    mock_github.return_value = mock_gh_instance

    mock_repo = Mock()
    mock_gh_instance.get_repo.return_value = mock_repo
    mock_repo.get_releases.return_value = []
    mock_repo.full_name = "test/repo"

    r = _repo(
        repo="test/repo", registry="test/registry", changelog_format="conventional"
    )
    r._git = Mock()
    r._git.create_tag = Mock()
    r._git.command = Mock(return_value="feat: test|abc|dev")

    r.create_release("v1.0.0", "abc123")

    # Check that the log message about conventional commits was logged
    assert "Generating conventional commits changelog" in caplog.text
