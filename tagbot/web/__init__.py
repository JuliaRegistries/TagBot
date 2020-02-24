import os

from typing import Dict, Tuple, Union

from flask import Flask, render_template, request
from werkzeug.exceptions import InternalServerError, MethodNotAllowed, NotFound

HTMLResponse = Union[str, Tuple[str, int]]
JSONResponse = Tuple[Dict[str, object], int]
TAGBOT_REPO_NAME = os.getenv("TAGBOT_REPO", "")

from . import reports  # noqa: E402

app = Flask(__name__)


@app.errorhandler(NotFound)
def not_found(e: NotFound) -> Union[HTMLResponse, JSONResponse]:
    if request.is_json:
        return {"error": "Not found"}, 404
    return render_template("404.html"), 404


@app.errorhandler(MethodNotAllowed)
def method_not_allowed(e: MethodNotAllowed) -> Union[HTMLResponse, JSONResponse]:
    if request.is_json:
        return {"error": "Method not allowed"}, 405
    return render_template("405.html"), 405


@app.errorhandler(InternalServerError)
def error(e: InternalServerError) -> Union[HTMLResponse, JSONResponse]:
    ctx = getattr(request, "context", None)
    req_id = getattr(ctx, "aws_request_id", None)
    if request.is_json:
        return {"error": "Internal server error", "request_id": req_id}, 500
    resp = render_template("500.html", request_id=req_id, tagbot_repo=TAGBOT_REPO_NAME)
    return resp, 500


@app.route("/")
def index() -> HTMLResponse:
    return render_template("index.html")


@app.route("/report", methods=["POST"])
def report() -> JSONResponse:
    return reports.handle(
        image=request.json["image"],
        repo=request.json["repo"],
        run=request.json["run"],
        stacktrace=request.json["stacktrace"],
    )
