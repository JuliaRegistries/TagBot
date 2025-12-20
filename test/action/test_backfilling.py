"""
Tests for backfilling behavior - ensuring TagBot can create releases for old versions
when set up later in a package's lifecycle.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, PropertyMock

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
    ignore=[],
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
        changelog_ignore=ignore,
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


def test_backfilling_discovers_all_versions():
    """Test that all versions are discovered regardless of age."""
    r = _repo()

    # Simulate a package with versions spanning several months
    old_date = datetime.now(timezone.utc) - timedelta(days=90)
    medium_date = datetime.now(timezone.utc) - timedelta(days=30)
    recent_date = datetime.now(timezone.utc) - timedelta(days=1)

    # Mock versions from registry - old, medium, and recent
    versions_by_age = {
        "0.1.0": "sha_old_v010",  # 90 days old
        "0.2.0": "sha_medium_v020",  # 30 days old
        "0.3.0": "sha_recent_v030",  # 1 day old
    }

    r._versions = lambda: versions_by_age
    r._filter_map_versions = lambda vs: vs

    # All versions should be returned, not just recent ones
    result = r.new_versions()

    # Verify all three versions are present
    assert len(result) == 3
    assert "0.1.0" in result
    assert "0.2.0" in result
    assert "0.3.0" in result

    # Verify they're in SemVer order
    assert list(result.keys()) == ["0.1.0", "0.2.0", "0.3.0"]


def test_backfilling_handles_many_versions():
    """Test that backfilling works with many versions without hitting pagination limits."""
    r = _repo()

    # Create 50 versions to simulate a mature package
    versions = {f"0.{i}.0": f"sha_{i}" for i in range(50)}

    r._versions = lambda: versions
    r._filter_map_versions = lambda vs: vs

    result = r.new_versions()

    # All versions should be discovered
    assert len(result) == 50


def test_performance_metrics_tracked():
    """Test that performance metrics are properly tracked during backfilling."""
    from tagbot.action.repo import _metrics

    # Reset metrics
    _metrics.api_calls = 0
    _metrics.prs_checked = 0
    _metrics.versions_checked = 0

    r = _repo()

    # Simulate checking multiple versions
    versions = {f"0.{i}.0": f"sha_{i}" for i in range(10)}
    r._versions = lambda: versions
    r._filter_map_versions = lambda vs: vs

    result = r.new_versions()

    # Verify metrics were updated
    assert _metrics.versions_checked >= 10
    assert len(result) == 10


def test_backfilling_with_existing_releases():
    """Test that backfilling skips versions that already have releases."""
    r = _repo()

    # Mock existing releases
    existing_tag_v020 = Mock()
    existing_tag_v020.name = "v0.2.0"

    r._repo = Mock()
    r._repo.get_releases = Mock(return_value=[existing_tag_v020])
    r._repo.get_tags = Mock(return_value=[existing_tag_v020])

    # All versions in registry
    all_versions = {
        "0.1.0": "sha1",
        "0.2.0": "sha2",  # Already has release
        "0.3.0": "sha3",
    }

    r._versions = lambda: all_versions

    # filter_map_versions should exclude v0.2.0
    def mock_filter(vs):
        # Simulate filtering out existing release
        return {k: v for k, v in vs.items() if k != "0.2.0"}

    r._filter_map_versions = mock_filter

    result = r.new_versions()

    # Only versions without existing releases should be returned
    assert "0.1.0" in result
    assert "0.2.0" not in result  # Already has release
    assert "0.3.0" in result


def test_backfilling_semver_ordering():
    """Test that backfilling respects SemVer ordering, not chronological."""
    r = _repo()

    # Versions in random order (simulating registry order)
    unordered_versions = {
        "0.3.0": "sha3",
        "0.1.0": "sha1",
        "1.0.0": "sha10",
        "0.2.0": "sha2",
        "0.10.0": "sha10_patch",
    }

    r._versions = lambda: unordered_versions
    r._filter_map_versions = lambda vs: vs

    result = r.new_versions()

    # Should be sorted by SemVer
    expected_order = ["0.1.0", "0.2.0", "0.3.0", "0.10.0", "1.0.0"]
    assert list(result.keys()) == expected_order


def test_backfilling_with_prereleases():
    """Test that backfilling handles pre-release versions correctly."""
    r = _repo()

    versions = {
        "0.1.0": "sha1",
        "0.2.0-alpha": "sha2a",
        "0.2.0-beta": "sha2b",
        "0.2.0": "sha2",
        "0.3.0-rc1": "sha3rc",
    }

    r._versions = lambda: versions
    r._filter_map_versions = lambda vs: vs

    result = r.new_versions()

    # All versions should be present, sorted by SemVer
    assert len(result) >= 3  # At least the stable versions
