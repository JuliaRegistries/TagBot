import os

GPG_KEY = os.getenv("INPUT_GPG-KEY", "")
REGISTRY = os.getenv("INPUT_REGISTRY", "")
REPO = os.getenv("GITHUB_REPOSITORY", "")
REPO_DIR = os.getenv("GITHUB_WORKSPACE", "")
TOKEN = os.getenv("INPUT_TOKEN", "")
