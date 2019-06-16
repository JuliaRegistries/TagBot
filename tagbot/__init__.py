from typing import Any

from . import notify, prepare, release, tag, webhook


def get_in(d: dict, *keys: str, default: Any = None) -> Any:
    """Safely retrieve a nested value from a dict."""
    for k in keys:
        if k not in d:
            return None
        d = d[k]
    return d
