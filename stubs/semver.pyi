from __future__ import annotations

class VersionInfo:
    prerelease: str
    build: str
    def __lt__(self, other: VersionInfo) -> bool: ...

def parse_version_info(version: str) -> VersionInfo: ...
