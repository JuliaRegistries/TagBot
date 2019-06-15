import os


def _getenv_warn(key, default=""):
    """Get an environment variable, warning when it's not present."""
    val = os.getenv(key)
    if val is None:
        print(f"Variable '{key}' not in environment (using '{default}')")
        return default
    return val


def sns_topic(key):
    """Get an SNS topic ARN."""
    return _topic_prefix + key


_topic_prefix = _getenv_warn("SNS_TOPIC_PREFIX")
git_tagger_email = _getenv_warn("GIT_TAGGER_EMAIL")
git_tagger_name = _getenv_warn("GIT_TAGGER_NAME")
github_app_id = int(_getenv_warn("GITHUB_APP_ID", 0))
webhook_secret = _getenv_warn("GITHUB_WEBHOOK_SECRET")
