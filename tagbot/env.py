import os

if "GITHUB_ACTION" in os.environ:
    GITHUB_SITE = os.getenv("INPUT_GH-SITE", "")
    GITHUB_API = os.getenv("INPUT_GH-API", "")
else:  # For dev (can't set environment variables with dashes).
    GITHUB_SITE = os.getenv("GH_SITE", "")
    GITHUB_API = os.getenv("GH_API", "")
GPG_KEY = os.getenv("INPUT_GPG-KEY", "")
REGISTRY = os.getenv("INPUT_REGISTRY", "")
REPO = os.getenv("GITHUB_REPOSITORY", "")
REPO_DIR = os.getenv("GITHUB_WORKSPACE", "")
TOKEN = os.getenv("INPUT_TOKEN", "")
