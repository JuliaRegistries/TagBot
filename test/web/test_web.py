import json

from unittest.mock import Mock, patch

from tagbot import web


def test_request_id():
    with_id = {"context": Mock(aws_request_id="id")}
    with web.app.test_request_context(environ_base=with_id):
        assert web._request_id() == "id"
    with web.app.test_request_context(environ_base={}):
        assert web._request_id() is None
    with web.app.test_request_context():
        assert web._request_id() is None


def test_not_found(client):
    resp = client.get("/abcdef", content_type="application/json")
    assert resp.status_code == 404
    assert resp.is_json
    assert resp.json["error"] == "Not found"
    resp = client.get("/abcdef")
    assert resp.status_code == 404
    assert not resp.is_json
    assert b"Sorry, this page doesn't exist." in resp.data


def test_method_not_allowed(client):
    resp = client.get("/report")
    assert resp.status_code == 405
    assert not resp.is_json
    assert b"Sorry, this method is not allowed for this URL." in resp.data
    resp = client.get("/report", content_type="application/json")
    assert resp.status_code == 405
    assert resp.is_json
    assert resp.json["error"] == "Method not allowed"


@patch("tagbot.web.TAGBOT_REPO_NAME", __str__=lambda x: "Foo/Bar")
@patch("tagbot.web._request_id", return_value=None)
@patch("tagbot.web.after_request", lambda r: r)
def test_error(request_id, repo_name, client):
    resp = client.get("/die")
    assert resp.status_code == 500
    assert not resp.is_json
    assert b"Sorry, there has been an internal server error." in resp.data
    assert b"https://github.com/Foo/Bar/issues" in resp.data
    assert b"Include the following error ID:" not in resp.data
    request_id.return_value = "id"
    resp = client.get("/die", content_type="application/json")
    assert resp.status_code == 500
    assert resp.is_json
    assert resp.json["error"] == "Internal server error"
    assert resp.json["request_id"] == "id"


def test_index(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Home" in resp.data


@patch("tagbot.web.REPORTS_FUNCTION_NAME")
@patch("tagbot.web.LAMBDA")
def test_report(LAMBDA, REPORTS, client):
    payload = {"image": "img", "repo": "repo", "run": "123", "stacktrace": "ow"}
    resp = client.post("/report", json=payload)
    assert resp.status_code == 200
    assert resp.is_json
    assert resp.json == {"status": "Submitted error report"}
    LAMBDA.invoke.assert_called_with(FunctionName=REPORTS, Payload=json.dumps(payload))
