def get_in(d, *keys, default=None):
    """Safely retrieve a nested value from a dict."""
    for k in keys:
        if k not in d:
            return None
        d = d[k]
    return d


from . import notify
from . import prepare
from . import webhook
