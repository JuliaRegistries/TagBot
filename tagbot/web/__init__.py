import json
import os

from random import randrange
from typing import Dict, Tuple, TypeVar, Union

import boto3

from flask import Flask, render_template, request
from werkzeug.exceptions import InternalServerError, MethodNotAllowed, NotFound

T = TypeVar("T")
StatusOptional = Union[T, Tuple[T, int]]
HTML = StatusOptional[str]
JSON = StatusOptional[Dict[str, object]]

MAX_DELAY = 900
SQS = boto3.resource("sqs", region_name=os.getenv("AWS_REGION", "us-east-1"))
REPORTS_QUEUE = SQS.Queue(os.getenv("REPORTS_QUEUE", ""))
TAGBOT_REPO_NAME = os.getenv("TAGBOT_REPO", "")

app = Flask(__name__)


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
    ctx = request.environ.get("context")
    req_id = ctx.aws_request_id if ctx else None
    if request.is_json:
        return {"error": "Internal server error", "request_id": req_id}, 500
    resp = render_template("500.html", request_id=req_id, tagbot_repo=TAGBOT_REPO_NAME)
    return resp, 500


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
    # Because the GitHub Action usually runs on the hour, we tend to get a lot of
    # requests at once, which botches the duplicate report detection.
    # To deal with that, wait a random period before the message becomes available.
    delay = randrange(MAX_DELAY)
    REPORTS_QUEUE.send_message(MessageBody=json.dumps(payload), DelaySeconds=delay)
    return {"status": "Submitted error report", "delay": delay}, 200
