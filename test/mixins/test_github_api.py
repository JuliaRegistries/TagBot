from requests import HTTPError
from unittest.mock import Mock, call, patch

from tagbot.exceptions import NotInstalledForOwner, NotInstalledForRepo
from tagbot.mixins import GitHubAPI


mixin = GitHubAPI()
mixin._app = Mock()
mixin._app.create_jwt = Mock(return_value="jwt")
token = Mock()
token.token = "token"
mixin._app.get_access_token = Mock(return_value=token)


# TODO: Much better patching!


def test_client():
    assert (
        mixin._client()._Github__requester._Requester__authorizationHeader
        == "Bearer jwt"
    )
    mixin._app.create_jwt.reset_mock()


def test_headers():
    assert mixin._GitHubAPI__headers() == {
        "Accept": "application/vnd.github.machine-man-preview+json",
        "Authorization": "Bearer jwt",
    }
    mixin._app.create_jwt.assert_called_once_with()
    mixin._app.create_jwt.reset_mock()


@patch("requests.get")
def test_installation_id(get):
    resp = Mock()
    resp.configure_mock(status_code=200, json=lambda: {"id": 123})
    get.return_value = resp
    assert mixin._GitHubAPI__installation_id("repos", "foo/bar") == 123
    resp.status_code = 404
    assert mixin._GitHubAPI__installation_id("users", "foo") is None
    resp.raise_for_status.assert_not_called()
    resp.status_code = 500
    mixin._GitHubAPI__installation_id("orgs", "foo")
    resp.raise_for_status.assert_called_once()
    h = mixin._GitHubAPI__headers()
    get.assert_has_calls(
        [
            call("https://api.github.com/repos/foo/bar/installation", headers=h),
            call("https://api.github.com/users/foo/installation", headers=h),
            call("https://api.github.com/orgs/foo/installation", headers=h),
        ]
    )
    mixin._app.create_jwt.reset_mock()


def test_installation():
    old = mixin.auth_token
    mixin.auth_token = Mock(return_value="token")
    assert mixin._installation("foo/bar")._Github__requester._Requester__authorizationHeader == "token token"
    mixin.auth_token.assert_called_once_with("foo/bar")
    mixin.auth_token = old


def test_get_repo():
    pass


def test_get_pull_request():
    pass


def test_get_issue():
    pass


def test_get_issue_comment():
    pass


def test_get_default_branch():
    pass


def test_get_tag():
    pass


def test_create_comment():
    pass


def test_append_comment():
    pass


def test_auth_token():
    old = mixin._GitHubAPI__installation_id
    mixin._GitHubAPI__installation_id = Mock(
        side_effect=[123, None, 123, None, None, 123, None, None, None]
    )
    assert mixin.auth_token("a/b") == "token"
    try:
        mixin.auth_token("b/c")
    except NotInstalledForRepo:
        pass
    else:
        assert False, "Expected NotInstalledForRepo to be raised"
    try:
        mixin.auth_token("c/d")
    except NotInstalledForRepo:
        pass
    else:
        assert False, "Expected NotInstalledForRepo to be raised"
    try:
        mixin.auth_token("d/e")
    except NotInstalledForOwner:
        pass
    else:
        assert False, "Expected NotInstalledForOwner to be raised"
    assert mixin._GitHubAPI__installation_id.has_calls(
        [
            call("repos", "a/b"),
            call("repos", "b/c"),
            call("users", "b/c"),
            call("repos", "c/d"),
            call("users", "c/d"),
            call("orgs", "c/d"),
            call("repos", "d/e"),
            call("users", "d/e"),
            call("orgs", "d/e"),
        ]
    )
    mixin._app.get_access_token.called_once_with(123)
    mixin._app.get_access_token.reset_mock()
    mixin._GitHubAPI__installation_id = old


def test_create_release():
    pass
