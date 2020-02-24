from textwrap import dedent
from unittest.mock import Mock, patch

from github import BadCredentialsException

from tagbot.web import reports


@patch("tagbot.web.reports._validate_token", return_value=True)
@patch("tagbot.web.reports._find_duplicate", return_value=None)
@patch("tagbot.web.reports._add_duplicate_comment", return_value=Mock(html_url="dupe"))
@patch("tagbot.web.reports._create_issue", return_value=Mock(html_url="new"))
def test_handle(create_issue, add_duplicate_comment, find_duplicate, validate_token):
    kwargs = {
        "image": "img",
        "repo": "Foo/Bar",
        "run": "123",
        "stacktrace": "ow",
        "token": "x",
    }
    assert reports.handle(**kwargs) == (
        {"status": "Created new issue", "url": "new"},
        200,
    )
    find_duplicate.return_value = Mock()
    assert reports.handle(**kwargs) == (
        {"status": "Found duplicate issue", "url": "dupe"},
        200,
    )
    validate_token.return_value = False
    assert reports.handle(**kwargs) == ({"error": "Invalid token"}, 400)


@patch("tagbot.web.reports.Github")
def test_validate_token(Github):
    Github.return_value.get_user.return_value.login = "foo"
    assert not reports._validate_token(None)
    assert not reports._validate_token("")
    assert reports._validate_token("bar")
    Github.return_value.get_user.side_effect = BadCredentialsException(400, "?")
    assert not reports._validate_token("foo")


def test_is_duplicate():
    assert reports._is_duplicate("hello friend", "hello friend")
    assert reports._is_duplicate("hello friend", "henlo FRIEND")
    assert not reports._is_duplicate("hello", "friend")


@patch("tagbot.web.reports.TAGBOT_REPO")
def test_find_duplicate(TAGBOT_REPO):
    body = "foo\n```py\nstack\n```\nbar"
    TAGBOT_REPO.get_issues.return_value = [Mock(body="hello"), Mock(body=body)]
    assert not reports._find_duplicate("foo bar")
    assert not reports._find_duplicate("hello")
    assert reports._find_duplicate("stack") is TAGBOT_REPO.get_issues.return_value[1]


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


@patch("tagbot.web.reports.TAGBOT_REPO")
def test_create_issue(TAGBOT_REPO):
    reports._create_issue(image="img", repo="Foo/Bar", run="123", stacktrace="ow")
    expected = """\
    Repo: Foo/Bar
    Run URL: 123
    Image ID: img
    Stacktrace:
    ```py
    ow
    ```
    [err]
    """
    TAGBOT_REPO.create_issue.assert_called_with(
        "Automatic error report from Foo/Bar", dedent(expected)
    )
