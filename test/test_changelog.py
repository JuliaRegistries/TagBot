from datetime import datetime
from unittest.mock import Mock

from github.Issue import Issue
from github.PullRequest import PullRequest

from tagbot.repo import Repo


def _changelog(*, name="", registry="", token="", template=""):
    r = Repo(name, registry, token, template)
    return r._changelog


def test_previous_release():
    c = _changelog()
    mocks = []
    c._repo._repo.get_releases = lambda: mocks
    for t in ["ignore", "v1.2.4-ignore", "v1.2.3", "v1.2.2", "v1.0.2", "v1.0.10"]:
        m = Mock()
        m.tag_name = t
        mocks.append(m)
    assert c._previous_release("v1.0.0") is None
    assert c._previous_release("v1.0.2") is None
    assert c._previous_release("v1.2.5").tag_name == "v1.2.3"
    assert c._previous_release("v1.0.3").tag_name == "v1.0.2"


def test_version_end():
    c = _changelog()
    c._repo._git = Mock(return_value="2019-10-05T13:45:17+07:00")
    assert c._version_end("abcdef") == datetime(2019, 10, 5, 6, 45, 17)
    c._repo._git.assert_called_once_with("show", "-s", "--format=%cI", "abcdef")


def test_first_sha():
    c = _changelog()
    c._repo._git = Mock(return_value="abc\ndef\nghi")
    assert c._first_sha() == "ghi"
    c._repo._git.assert_called_once_with("log", "--format=%H")


def test_issues_and_pulls():
    pass


def test_issues_pulls():
    c = _changelog()
    mocks = []
    for i in range(0, 20, 2):
        mocks.append(Mock(spec=Issue, number=i))
        mocks.append(Mock(spec=PullRequest, number=i + 1))
    c._issues_and_pulls = Mock(return_value=mocks)
    assert all(isinstance(x, Issue) and not x.number % 2 for x in c._issues(0, 1))
    c._issues_and_pulls.assert_called_with(0, 1)
    assert all(isinstance(x, PullRequest) and x.number % 2 for x in c._pulls(2, 3))
    c._issues_and_pulls.assert_called_with(2, 3)


def test_custom_release_notes():
    pass


def test_format_user():
    c = _changelog()
    m = Mock(html_url="url", login="username")
    m.name = "Name"
    assert c._format_user(m) == {"name": "Name", "url": "url", "username": "username"}


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


def test_get():
    pass
