from typing import List, Optional

class ImportResult:
    stderr: str
    fingerprints: List[str]
    sec_imported: int

class Sign:
    stderr: str
    status: Optional[str]

class GPG:
    def __init__(self, *, gnupghome: str, use_agent: bool) -> None: ...
    def import_keys(self, data: str) -> ImportResult: ...
    def sign(self, data: str, passphrase: Optional[str]) -> Sign: ...
