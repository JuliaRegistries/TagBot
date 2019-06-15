import json

from dataclasses import dataclass
from typing import Optional


@dataclass
class Context:
    """
    A container for job data.
    It gets passed through the execution pipeline, accumulating information.
    """

    id: str
    repo: str
    version: str
    commit: str
    target: str
    release_notes: Optional[str] = None
    comment_id: Optional[int] = None


def from_records(records):
    """Parse a list of Contexts from SNS messages."""
    return [_from_json(r["Sns"]["Message"]) for r in evt["Records"]]


def _from_json(s):
    return Context(**json.loads(s))
