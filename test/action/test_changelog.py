import os.path
import textwrap

from datetime import datetime, timedelta
from unittest.mock import Mock

import yaml

from github.Issue import Issue
from github.PullRequest import PullRequest

from tagbot.action.repo import Repo


def _changelog(*, template="", ignore=set()):
    r = Repo(
        repo="",
        registry="",
        github="",
        github_api="",
        token="",
        changelog=template,
        changelog_ignore=ignore,
        ssh=False,
        gpg=False,
        user="",
        email="",
        lookback=3,
        branch=None,
    )
    return r._changelog


def test_slug():
    c = _changelog()
    assert c._slug("A b-c_d") == "abcd"


def test_previous_release():
    c = _changelog()
    tags = ["ignore", "v1.2.4-ignore", "v1.2.3", "v1.2.2", "v1.0.2", "v1.0.10"]
    c._repo._repo.get_releases = Mock(return_value=[Mock(tag_name=t) for t in tags])
    assert c._previous_release("v1.0.0") is None
    assert c._previous_release("v1.0.2") is None
    rel = c._previous_release("v1.2.5")
    assert rel and rel.tag_name == "v1.2.3"
    rel = c._previous_release("v1.0.3")
    assert rel and rel.tag_name == "v1.0.2"


def test_issues_and_pulls():
    c = _changelog()
    now = datetime.now()
    start = now - timedelta(days=10)
    end = now
    c._repo._repo.get_issues = Mock(return_value=[])
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
    c._previous_release = Mock(
        side_effect=[Mock(tag_name="v1.2.2", created_at=datetime.now()), None]
    )
    c._repo._git.time_of_commit = Mock(return_value=datetime.now())
    # TODO: Put stuff here.
    c._issues = Mock(return_value=[])
    c._pulls = Mock(return_value=[])
    c._custom_release_notes = Mock(return_value="custom")
    assert c._collect_data("v1.2.3", "abcdef") == {
        "compare_url": "https://github.com/A/B.jl/compare/v1.2.2...v1.2.3",
        "custom": "custom",
        "issues": [],
        "package": "B",
        "previous_release": "v1.2.2",
        "pulls": [],
        "sha": "abcdef",
        "version": "v1.2.3",
        "version_url": "https://github.com/A/B.jl/tree/v1.2.3",
    }
    data = c._collect_data("v2.3.4", "bcdefa")
    assert data["compare_url"] is None
    assert data["previous_release"] is None


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

    **Closed issues:**
    - Issue title (#1)

    **Merged pull requests:**
    - Pull title (#3) (@author)
    """
    data = {
        "compare_url": "https://github.com/Me/PkgName.jl/compare/v1.2.2...v1.2.3",
        "custom": "Custom release notes",
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
    }
    assert c._render(data) == textwrap.dedent(expected).strip()
    del data["pulls"]
    assert "**Merged pull requests:**" not in c._render(data)
    del data["issues"]
    assert "**Closed issues:**" not in c._render(data)
    data["previous_release"] = None
    assert "Diff since" not in c._render(data)


def test_get():
    c = _changelog(template="{{ version }}")
    c._collect_data = Mock(return_value={"version": "v1.2.3"})
    assert c.get("v1.2.3", "abc") == "v1.2.3"
    c._collect_data.assert_called_once_with("v1.2.3", "abc")
