import os

# Duplicating the default value for these required ones:
# https://github.community/t5/GitHub-Actions/Actions-input-parameters-are-not-passed-to-images-pulled-from-a/m-p/33883
GITHUB_SITE = os.getenv("INPUT_GITHUB-SITE") or "https://github.com"
GITHUB_API = os.getenv("INPUT_GITHUB-API") or "https://api.github.com"

# This one has no good default, so I think it will be broken until a GitHub fix.
GPG_KEY = os.getenv("INPUT_GPG-KEY", "")

REGISTRY = os.getenv("INPUT_REGISTRY", "")
REPO = os.getenv("GITHUB_REPOSITORY", "")
REPO_DIR = os.getenv("GITHUB_WORKSPACE", "")
TOKEN = os.getenv("INPUT_TOKEN", "")
