import os

EVENT_NAME = os.getenv("GITHUB_EVENT_NAME", "")
EVENT_PATH = os.getenv("GITHUB_EVENT_PATH", "")
REPO = os.getenv("GITHUB_REPOSITORY", "")
REPO_DIR = os.getenv("GITHUB_WORKSPACE", "")
TOKEN = os.getenv("INPUT_TOKEN", "")
