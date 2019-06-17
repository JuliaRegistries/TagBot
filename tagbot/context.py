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
    issue: int
    release_notes: Optional[str] = None
    comment_id: Optional[int] = None
    notification: Optional[str] = None
