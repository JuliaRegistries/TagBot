import os.path
import textwrap

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import yaml

from github.Issue import Issue
from github.PullRequest import PullRequest

from tagbot.action.repo import Repo


@patch("tagbot.action.repo.Github")
def _changelog(mock_gh, *, template="", ignore=set(), subdir=None):
    mock_gh_instance = Mock()
    mock_gh.return_value = mock_gh_instance
    mock_repo = Mock()
    mock_gh_instance.get_repo.return_value = mock_repo
    r = Repo(
        repo="",
        registry="",
        github="",
        github_api="",
        token="x",
        changelog=template,
        changelog_ignore=ignore,
        changelog_format="custom",
        ssh=False,
        gpg=False,
        draft=False,
        registry_ssh="",
        user="",
        email="",
        branch=None,
        subdir=subdir,
    )
    # Mock get_all_tags to return empty list (tests override as needed)
    r.get_all_tags = Mock(return_value=[])
    # Mock _build_tags_cache to return empty dict
    r._build_tags_cache = Mock(return_value={})
    return r._changelog


def test_slug():
    c = _changelog()
    assert c._slug("A b-c_d") == "abcd"


def test_previous_release():
    c = _changelog()
    tags = [
        "ignore",
        "v1.2.4-ignore",
        "v1.2.3",
        "v1.2.2",
        "v1.0.2",
        "v1.0.10",
    ]
    c._repo.get_all_tags = Mock(return_value=tags)
    c._repo._repo.get_release = Mock(side_effect=lambda t: Mock(tag_name=t))
    assert c._previous_release("v1.0.0") is None
    assert c._previous_release("v1.0.2") is None
    rel = c._previous_release("v1.2.5")
    assert rel and rel.tag_name == "v1.2.3"
    rel = c._previous_release("v1.0.3")
    assert rel and rel.tag_name == "v1.0.2"


def test_previous_release_no_github_release():
    """Test that _previous_release falls back to commit time when no GitHub release."""
    from datetime import datetime
    from github import UnknownObjectException

    c = _changelog()
    tags = ["v1.0.0", "v1.1.0"]
    c._repo.get_all_tags = Mock(return_value=tags)
    # Simulate no GitHub release existing for the tag
    c._repo._repo.get_release = Mock(
        side_effect=UnknownObjectException(404, "Not Found", {})
    )
    # Mock time_of_commit to return a datetime
    mock_time = datetime(2025, 1, 1, 12, 0, 0)
    c._repo._git.time_of_commit = Mock(return_value=mock_time)

    rel = c._previous_release("v1.1.1")
    assert rel is not None
    assert rel.tag_name == "v1.1.0"
    assert rel.created_at == mock_time
    c._repo._git.time_of_commit.assert_called_with("v1.1.0")


def test_previous_release_subdir():
    True
    c = _changelog(subdir="Foo")
    c._repo._repo.get_contents = Mock(
        return_value=Mock(decoded_content=b"""name = "Foo"\nuuid="abc-def"\n""")
    )
    tags = [
        "ignore",
        "v1.2.4-ignore",
        "Foo-v1.2.3",
        "Foo-v1.2.2",
        "Foo-v1.0.2",
        "Foo-v1.0.10",
        "v2.0.1",
        "Foo-v2.0.0",
    ]
    c._repo.get_all_tags = Mock(return_value=tags)
    c._repo._repo.get_release = Mock(side_effect=lambda t: Mock(tag_name=t))
    assert c._previous_release("Foo-v1.0.0") is None
    assert c._previous_release("Foo-v1.0.2") is None
    rel = c._previous_release("Foo-v1.2.5")
    assert rel and rel.tag_name == "Foo-v1.2.3"
    rel = c._previous_release("Foo-v1.0.3")
    assert rel and rel.tag_name == "Foo-v1.0.2"
    rel = c._previous_release("Foo-v2.1.0")
    assert rel and rel.tag_name == "Foo-v2.0.0"


def test_issues_and_pulls():
    c = _changelog()
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=10)
    end = now
    # Mock _repo._repo.full_name for search query construction
    c._repo._repo = Mock()
    c._repo._repo.full_name = "owner/repo"
    c._repo._repo.get_issues = Mock(return_value=[])
    # Mock search_issues to raise an exception so we fall back to get_issues
    mock_gh = Mock()
    mock_gh.search_issues.side_effect = Exception("search failed")
    c._repo._gh = mock_gh
    assert c._issues_and_pulls(end, end) == []
    assert c._issues_and_pulls(end, end) == []
    c._repo._repo.get_issues.assert_called_once_with(state="closed", since=end)
    assert c._issues_and_pulls(end, end) == []
    c._repo._repo.get_issues.assert_called_with(state="closed", since=end)
    n = 1
    for days in [-1, 0, 5, 10, 11]:
        i = Mock(
            closed_at=end - timedelta(days=days), n=n, pull_request=False, labels=[]
        )
        p = Mock(
            closed_at=end - timedelta(days=days),
            pull_request=True,
            labels=[],
            as_pull_request=Mock(return_value=Mock(merged=days % 2 == 0, n=n + 1)),
        )
        n += 2
        c._repo._repo.get_issues.return_value.extend([i, p])
    assert [x.n for x in c._issues_and_pulls(start, end)] == [5, 4, 3]


def test_issues_pulls():
    c = _changelog()
    mocks = []
    for i in range(0, 20, 2):
        mocks.append(Mock(spec=Issue, number=i))
        mocks.append(Mock(spec=PullRequest, number=i + 1))
    c._issues_and_pulls = Mock(return_value=mocks)
    a = datetime(1, 1, 1)
    b = datetime(2, 2, 2)
    assert all(isinstance(x, Issue) and not x.number % 2 for x in c._issues(a, b))
    c._issues_and_pulls.assert_called_with(a, b)
    assert all(isinstance(x, PullRequest) and x.number % 2 for x in c._pulls(b, a))
    c._issues_and_pulls.assert_called_with(b, a)


def test_custom_release_notes():
    c = _changelog()
    notes = """
    blah blah blah
    <!-- BEGIN RELEASE NOTES -->
    `````
    Foo
    Bar
    `````
    <!-- END RELEASE NOTES -->
    blah blah blah
    """
    notes = textwrap.dedent(notes)
    c._repo._registry_pr = Mock(side_effect=[None, Mock(body="foo"), Mock(body=notes)])
    assert c._custom_release_notes("v1.2.3") is None
    c._repo._registry_pr.assert_called_with("v1.2.3")
    assert c._custom_release_notes("v2.3.4") is None
    c._repo._registry_pr.assert_called_with("v2.3.4")
    assert c._custom_release_notes("v3.4.5") == "Foo\nBar"
    c._repo._registry_pr.assert_called_with("v3.4.5")


def test_old_format_custom_release_notes():
    c = _changelog()
    notes = """
    blah blah blah
    <!-- BEGIN RELEASE NOTES -->
    > Foo
    > Bar
    <!-- END RELEASE NOTES -->
    blah blah blah
    """
    notes = textwrap.dedent(notes)
    c._repo._registry_pr = Mock(side_effect=[None, Mock(body="foo"), Mock(body=notes)])
    assert c._custom_release_notes("v1.2.3") is None
    c._repo._registry_pr.assert_called_with("v1.2.3")
    assert c._custom_release_notes("v2.3.4") is None
    c._repo._registry_pr.assert_called_with("v2.3.4")
    assert c._custom_release_notes("v3.4.5") == "Foo\nBar"
    c._repo._registry_pr.assert_called_with("v3.4.5")


def test_format_user():
    c = _changelog()
    m = Mock(html_url="url", login="username")
    m.name = "Name"
    assert c._format_user(m) == {"name": "Name", "url": "url", "username": "username"}
    assert c._format_user(None) == {}


def test_format_issue_pull():
    c = _changelog()
    m = Mock(
        user=Mock(html_url="url", login="username"),
        closed_by=Mock(html_url="url", login="username"),
        merged_by=Mock(html_url="url", login="username"),
        body="body",
        labels=[Mock(), Mock()],
        number=1,
        title="title",
        html_url="url",
    )
    m.user.name = "User"
    m.closed_by.name = "Closer"
    m.merged_by.name = "Merger"
    m.labels[0].name = "label1"
    m.labels[1].name = "label2"
    assert c._format_issue(m) == {
        "author": {"name": "User", "url": "url", "username": "username"},
        "body": "body",
        "labels": ["label1", "label2"],
        "closer": {"name": "Closer", "url": "url", "username": "username"},
        "number": 1,
        "title": "title",
        "url": "url",
    }
    assert c._format_pull(m) == {
        "author": {"name": "User", "url": "url", "username": "username"},
        "body": "body",
        "labels": ["label1", "label2"],
        "merger": {"name": "Merger", "url": "url", "username": "username"},
        "number": 1,
        "title": "title",
        "url": "url",
    }


def test_collect_data():
    c = _changelog()
    c._repo._repo = Mock(full_name="A/B.jl", html_url="https://github.com/A/B.jl")
    c._repo._project = Mock(return_value="B")
    c._repo.is_version_yanked = Mock(return_value=False)
    c._previous_release = Mock(
        side_effect=[
            Mock(tag_name="v1.2.2", created_at=datetime.now(timezone.utc)),
            None,
        ]
    )
    c._is_backport = Mock(return_value=False)
    commit = Mock(author=Mock(date=datetime.now(timezone.utc)))
    c._repo._repo.get_commit = Mock(return_value=Mock(commit=commit))
    # TODO: Put stuff here.
    c._issues = Mock(return_value=[])
    c._pulls = Mock(return_value=[])
    c._custom_release_notes = Mock(return_value="custom")
    assert c._collect_data("v1.2.3", "abcdef") == {
        "compare_url": "https://github.com/A/B.jl/compare/v1.2.2...v1.2.3",
        "custom": "custom",
        "backport": False,
        "issues": [],
        "package": "B",
        "previous_release": "v1.2.2",
        "pulls": [],
        "sha": "abcdef",
        "version": "v1.2.3",
        "version_url": "https://github.com/A/B.jl/tree/v1.2.3",
        "yanked": False,
    }
    data = c._collect_data("v2.3.4", "bcdefa")
    assert data["compare_url"] is None
    assert data["previous_release"] is None


def test_is_backport():
    c = _changelog()
    assert c._is_backport("v1.2.3", ["v1.2.1", "v1.2.2"]) is False
    assert c._is_backport("v1.2.3", ["v1.2.1", "v1.2.2", "v2.0.0"]) is True
    assert c._is_backport("Foo-v1.2.3", ["v1.2.1", "v1.2.2", "v2.0.0"]) is False
    assert c._is_backport("Foo-v1.2.3", ["Foo-v1.2.2", "Foo-v2.0.0"]) is True
    assert c._is_backport("Foo-v1.2.3", ["Foo-v1.2.2", "Bar-v2.0.0"]) is False
    assert c._is_backport("v1.2.3", []) is False
    assert c._is_backport("v1.2.3", ["v1.2.3"]) is False


def test_render():
    path = os.path.join(os.path.dirname(__file__), "..", "..", "action.yml")
    with open(path) as f:
        action = yaml.safe_load(f)
    default = action["inputs"]["changelog"]["default"]
    c = _changelog(template=default)
    expected = """
    ## PkgName v1.2.3

    [Diff since v1.2.2](https://github.com/Me/PkgName.jl/compare/v1.2.2...v1.2.3)

    Custom release notes

    **Merged pull requests:**
    - Pull title (#3) (@author)

    **Closed issues:**
    - Issue title (#1)
    """
    data = {
        "compare_url": "https://github.com/Me/PkgName.jl/compare/v1.2.2...v1.2.3",
        "custom": "Custom release notes",
        "backport": False,
        "issues": [{"number": 1, "title": "Issue title", "labels": []}],
        "package": "PkgName",
        "previous_release": "v1.2.2",
        "pulls": [
            {
                "number": 3,
                "title": "Pull title",
                "labels": [],
                "author": {"username": "author"},
            },
        ],
        "version": "v1.2.3",
        "version_url": "https://github.com/Me/PkgName.jl/tree/v1.2.3",
        "yanked": False,
    }
    assert c._render(data) == textwrap.dedent(expected).strip()
    del data["pulls"]
    assert "**Merged pull requests:**" not in c._render(data)
    del data["issues"]
    assert "**Closed issues:**" not in c._render(data)
    data["previous_release"] = None
    assert "Diff since" not in c._render(data)


def test_render_backport():
    path = os.path.join(os.path.dirname(__file__), "..", "..", "action.yml")
    with open(path) as f:
        action = yaml.safe_load(f)
    default = action["inputs"]["changelog"]["default"]
    c = _changelog(template=default)
    expected = """
    ## PkgName v1.2.3

    [Diff since v1.2.2](https://github.com/Me/PkgName.jl/compare/v1.2.2...v1.2.3)

    Custom release notes

    This release has been identified as a backport.
    Automated changelogs for backports tend to be wildly incorrect.
    Therefore, the list of issues and pull requests is hidden.
    <!--
    **Merged pull requests:**
    - Pull title (#3) (@author)

    **Closed issues:**
    - Issue title (#1)

    -->
    """
    data = {
        "compare_url": "https://github.com/Me/PkgName.jl/compare/v1.2.2...v1.2.3",
        "custom": "Custom release notes",
        "backport": True,
        "issues": [{"number": 1, "title": "Issue title", "labels": []}],
        "package": "PkgName",
        "previous_release": "v1.2.2",
        "pulls": [
            {
                "number": 3,
                "title": "Pull title",
                "labels": [],
                "author": {"username": "author"},
            },
        ],
        "version": "v1.2.3",
        "version_url": "https://github.com/Me/PkgName.jl/tree/v1.2.3",
        "yanked": False,
    }
    assert c._render(data) == textwrap.dedent(expected).strip()
    del data["pulls"]
    assert "**Merged pull requests:**" not in c._render(data)
    del data["issues"]
    assert "**Closed issues:**" not in c._render(data)
    data["previous_release"] = None
    assert "Diff since" not in c._render(data)


def test_render_yanked():
    """Test that yanked releases show a warning."""
    path = os.path.join(os.path.dirname(__file__), "..", "..", "action.yml")
    with open(path) as f:
        action = yaml.safe_load(f)
    default = action["inputs"]["changelog"]["default"]
    c = _changelog(template=default)

    data = {
        "compare_url": "https://github.com/Me/PkgName.jl/compare/v1.2.2...v1.2.3",
        "custom": None,
        "backport": False,
        "issues": [],
        "package": "PkgName",
        "previous_release": "v1.2.2",
        "pulls": [],
        "version": "v1.2.3",
        "version_url": "https://github.com/Me/PkgName.jl/tree/v1.2.3",
        "yanked": True,
    }
    rendered = c._render(data)
    assert ":warning: **This release has been yanked from the registry.**" in rendered

    # Non-yanked should not have warning
    data["yanked"] = False
    rendered = c._render(data)
    assert "yanked" not in rendered.lower()


def test_get():
    c = _changelog(template="{{ version }}")
    c._collect_data = Mock(return_value={"version": "v1.2.3"})
    assert c.get("v1.2.3", "abc") == "v1.2.3"
    c._collect_data.assert_called_once_with("v1.2.3", "abc")

    c = _changelog(template="{{ version }}")
    c._collect_data = Mock(return_value={"version": "Foo-v1.2.3"})
    assert c.get("Foo-v1.2.3", "abc") == "Foo-v1.2.3"
    c._collect_data.assert_called_once_with("Foo-v1.2.3", "abc")
