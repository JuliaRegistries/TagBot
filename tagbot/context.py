from dataclasses import dataclass
from typing import Optional


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
    notification: Optional[str] = None
    changelog: Optional[str] = None
