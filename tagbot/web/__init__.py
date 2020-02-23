from flask import Flask, request
from flask.app import InternalServerError

from . import reports

app = Flask(__name__)


@app.errorhandler(404)
def not_found(e):
    return {"error": "Not found"}, 404


@app.errorhandler(InternalServerError)
def error(e):
    return {"error": "Internal server error"}, 500


@app.route("/report", methods=["POST"])
def report():
    return reports.handle(
        image=request.json["image"],
        repo=request.json["repo"],
        run=request.json["run"],
        stacktrace=request.json["stacktrace"],
        token=request.json["token"],
    )
