import os

from typing import Dict, Tuple, Union

from flask import Flask, redirect, request
from werkzeug import Response
from werkzeug.exceptions import InternalServerError

JSONResponse = Tuple[Dict[str, object], int]
TAGBOT_REPO_NAME = os.getenv("TAGBOT_REPO")

from . import reports  # noqa: E402

app = Flask(__name__)


@app.errorhandler(InternalServerError)
def error(e: InternalServerError) -> Union[JSONResponse, None]:
    if request.is_json:
        return {"error": "Internal server error"}, 500
    return None  # TODO: An HTML error page.


@app.route("/")
def index() -> Response:
    return redirect(f"https://github.com/{TAGBOT_REPO_NAME}")


@app.route("/report", methods=["POST"])
def report() -> JSONResponse:
    return reports.handle(
        image=request.json["image"],
        repo=request.json["repo"],
        run=request.json["run"],
        stacktrace=request.json["stacktrace"],
        token=request.json["token"],
    )
