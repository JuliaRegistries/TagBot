import json
import os

from typing import Dict, Optional, Tuple, TypeVar, Union, cast

import boto3

from flask import Flask, Response, render_template, request
from werkzeug.exceptions import InternalServerError, MethodNotAllowed, NotFound

from .. import log_handler

T = TypeVar("T")
StatusOptional = Union[T, Tuple[T, int]]
HTML = StatusOptional[str]
JSON = StatusOptional[Dict[str, object]]

LAMBDA = boto3.client("lambda", region_name=os.getenv("AWS_REGION", "us-east-1"))
REPORTS_FUNCTION_NAME = os.getenv("REPORTS_FUNCTION", "")
TAGBOT_REPO_NAME = os.getenv("TAGBOT_REPO", "")
TAGBOT_ISSUES_REPO_NAME = os.getenv("TAGBOT_ISSUES_REPO", "")

app = Flask(__name__)
app.logger.addHandler(log_handler)


def _request_id() -> Optional[str]:
    """Get the AWS request ID if it's set."""
    ctx = request.environ.get("context")
    return ctx.aws_request_id if ctx else None


@app.after_request
def after_request(r: Response) -> Response:
    msg = f"{request.method} {request.path}: {r.status_code}"
    req_id = _request_id()
    if req_id:
        msg = f"{req_id} - {msg}"
    app.logger.info(msg)
    return r


@app.errorhandler(NotFound)
def not_found(e: NotFound) -> Union[HTML, JSON]:
    if request.is_json:
        resp: JSON = ({"error": "Not found"}, 404)
        return resp
    return render_template("404.html"), 404


@app.errorhandler(MethodNotAllowed)
def method_not_allowed(e: MethodNotAllowed) -> Union[HTML, JSON]:
    if request.is_json:
        resp: JSON = ({"error": "Method not allowed"}, 405)
        return resp
    return render_template("405.html"), 405


@app.errorhandler(InternalServerError)
def error(e: InternalServerError) -> Union[HTML, JSON]:
    req_id = _request_id()
    # mypy really hates this.
    if request.is_json:
        json = {"error": "Internal server error", "request_id": req_id}
        return cast(JSON, (json, 500))
    html = render_template("500.html", request_id=req_id, tagbot_repo=TAGBOT_REPO_NAME)
    return html, 500


@app.route("/")
def index() -> HTML:
    return render_template("index.html")


@app.route("/report", methods=["POST"])
def report() -> JSON:
    payload = {
        "image": request.json["image"],
        "repo": request.json["repo"],
        "run": request.json["run"],
        "stacktrace": request.json["stacktrace"],
    }
    LAMBDA.invoke(FunctionName=REPORTS_FUNCTION_NAME, Payload=json.dumps(payload))
    return {"status": "Submitted error report"}, 200
