from __future__ import annotations
from typing import Optional

class VersionInfo:
    major: str
    minor: str
    patch: str
    prerelease: Optional[str]
    build: Optional[str]
    def __init__(self, major: int) -> None: ...
    def __lt__(self, other: VersionInfo) -> bool: ...
    @staticmethod
    def parse(version: str) -> VersionInfo: ...
    def next_version(self, bump: str) -> VersionInfo: ...
