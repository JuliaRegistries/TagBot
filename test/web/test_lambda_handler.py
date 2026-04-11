from unittest.mock import Mock

from tagbot.web.lambda_handler import handler


def _event(method="GET", path="/", headers=None, body=None, qs=None):
    return {
        "httpMethod": method,
        "path": path,
        "headers": headers or {"Host": "julia-tagbot.com"},
        "queryStringParameters": qs,
        "body": body,
        "isBase64Encoded": False,
    }


def test_get_index():
    resp = handler(_event(), Mock())
    assert resp["statusCode"] == 200
    assert "TagBot" in resp["body"]
    assert "Content-Type" in resp["headers"]


def test_not_found():
    resp = handler(_event(path="/nonexistent"), Mock())
    assert resp["statusCode"] == 404


def test_post_report_missing_body():
    event = _event(
        method="POST",
        path="/report",
        headers={"Host": "julia-tagbot.com", "Content-Type": "application/json"},
    )
    resp = handler(event, Mock())
    assert resp["statusCode"] in (400, 500)


def test_headers_forwarded():
    event = _event(headers={"Host": "example.com", "Content-Type": "text/plain"})
    resp = handler(event, Mock())
    assert resp["statusCode"] == 200


def test_query_string():
    resp = handler(_event(qs={"foo": "bar"}), Mock())
    assert resp["statusCode"] == 200
