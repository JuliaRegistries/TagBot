import json

from unittest.mock import patch


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
def test_error(repo_name, client):
    # TODO: How to test the request ID?
    resp = client.get("/die")
    assert resp.status_code == 500
    assert not resp.is_json
    assert b"Sorry, there has been an internal server error." in resp.data
    assert b"https://github.com/Foo/Bar/issues" in resp.data
    assert b"Include the following error ID:" not in resp.data
    resp = client.get("/die", content_type="application/json")
    assert resp.status_code == 500
    assert resp.is_json
    assert resp.json["error"] == "Internal server error"


def test_index(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Home" in resp.data


@patch("tagbot.web.randrange", return_value=10)
@patch("tagbot.web.REPORTS_QUEUE")
def test_report(REPORTS_QUEUE, randrange, client):
    payload = {"image": "img", "repo": "repo", "run": "123", "stacktrace": "ow"}
    resp = client.post("/report", json=payload)
    assert resp.status_code == 200
    assert resp.is_json
    assert resp.json == {"status": "Submitted error report", "delay": 10}
    REPORTS_QUEUE.send_message.assert_called_with(
        MessageBody=json.dumps(payload), DelaySeconds=10
    )
