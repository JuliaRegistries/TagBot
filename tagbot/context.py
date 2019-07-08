import json
import sys

from dataclasses import dataclass


@dataclass
class Context:
    """Contains job data."""

    registry: str
    repo: str
    version: str
    commit: str
    issue: int
    id: str = ""
    target: str = ""
    comment_id: int = 0
    notification: str = ""
    changelog: str = ""

    def dump(self):
        json.dump(self.__dict__, sys.stdout, indent=2)
        print()
