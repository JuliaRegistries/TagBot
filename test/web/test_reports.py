from textwrap import dedent
from unittest.mock import Mock, patch

from tagbot.web import reports


@patch("tagbot.web.reports._handle_report")
def test_handler(handle_report):
    event = {"image": "i", "repo": "re", "run": "ru", "stacktrace": "s"}
    reports.handler(event)
    handle_report.assert_called_with(image="i", repo="re", run="ru", stacktrace="s")


@patch("tagbot.web.reports._find_duplicate", return_value=None)
@patch("tagbot.web.reports._already_commented", side_effect=[True, False])
@patch("tagbot.web.reports._add_duplicate_comment")
@patch("tagbot.web.reports._create_issue", return_value=Mock(html_url="new"))
def test_handle_report(
    create_issue, add_duplicate_comment, already_commented, find_duplicate
):
    kwargs = {"image": "img", "repo": "Foo/Bar", "run": "123", "stacktrace": "ow"}
    reports._handle_report(**kwargs)
    create_issue.assert_called()
    find_duplicate.return_value = Mock(html_url="dupe")
    reports._handle_report(**kwargs)
    add_duplicate_comment.assert_not_called()
    reports._handle_report(**kwargs)
    add_duplicate_comment.assert_called()


def test_already_commented():
    issue = Mock(
        body="Repo: Foo/Bar",
        get_comments=Mock(return_value=[Mock(body="Repo: Foo/Bar")]),
    )
    assert reports._already_commented(issue, repo="Foo/Bar")
    issue.get_comments.assert_not_called()
    issue.body = ""
    assert reports._already_commented(issue, repo="Foo/Bar")
    issue.get_comments.assert_called()
    assert not reports._already_commented(issue, repo="Bar/Baz")


def test_is_duplicate():
    assert reports._is_duplicate("hello friend", "hello friend")
    assert reports._is_duplicate("hello friend", "henlo FRIEND")
    assert not reports._is_duplicate("hello", "friend")


@patch("tagbot.web.reports.TAGBOT_ISSUES_REPO")
def test_find_duplicate(TAGBOT_ISSUES_REPO):
    body = "foo\n```py\nstack\n```\nbar"
    TAGBOT_ISSUES_REPO.get_issues.return_value = [Mock(body="hello"), Mock(body=body)]
    assert not reports._find_duplicate("foo bar")
    assert not reports._find_duplicate("hello")
    expected = TAGBOT_ISSUES_REPO.get_issues.return_value[1]
    assert reports._find_duplicate("stack") is expected


def test_report_body():
    body = reports._report_body(image="img", repo="Foo/Bar", run="123", stacktrace="ow")
    expected = """\
    Repo: Foo/Bar
    Run URL: 123
    Image ID: img
    Stacktrace:
    ```py
    ow
    ```
    """
    assert body == dedent(expected)


def test_add_duplicate_comment():
    issue = Mock()
    reports._add_duplicate_comment(
        issue, image="img", repo="Foo/Bar", run="123", stacktrace="ow"
    )
    expected = """\
    Probably duplicate error:
    Repo: Foo/Bar
    Run URL: 123
    Image ID: img
    Stacktrace:
    ```py
    ow
    ```
    """
    issue.create_comment.assert_called_with(dedent(expected))


@patch("tagbot.web.reports.TAGBOT_ISSUES_REPO")
def test_create_issue(TAGBOT_ISSUES_REPO):
    reports._create_issue(image="img", repo="Foo/Bar", run="123", stacktrace="ow")
    expected = """\
    Repo: Foo/Bar
    Run URL: 123
    Image ID: img
    Stacktrace:
    ```py
    ow
    ```
    """
    TAGBOT_ISSUES_REPO.create_issue.assert_called_with(
        "Automatic error report from Foo/Bar", dedent(expected)
    )
