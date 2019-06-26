import os


def _getenv_warn(key: str, default: str = "") -> str:
    """Get an environment variable, warning when it's not present."""
    val = os.getenv(key)
    if val is None:
        print(f"Variable '{key}' not in environment (using '{default}')")
        return default
    return val


dynamodb_table_name = _getenv_warn("DYNAMODB_TABLE_NAME")
git_tagger_email = _getenv_warn("GIT_TAGGER_EMAIL")
git_tagger_name = _getenv_warn("GIT_TAGGER_NAME")
github_app_id = int(_getenv_warn("GITHUB_APP_ID", "0"))
github_app_name = _getenv_warn("GITHUB_APP_NAME")
lambda_function_prefix = _getenv_warn("LAMBDA_FUNCTION_PREFIX")
registrator_username = _getenv_warn("REGISTRATOR_USERNAME")
webhook_secret = _getenv_warn("GITHUB_WEBHOOK_SECRET")
