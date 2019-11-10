import os

GITHUB_SITE = os.getenv("INPUT_GITHUB-SITE", "https://github.com")
GITHUB_API = os.getenv("INPUT_GITHUB-API", "https://api.github.com")
GPG_KEY = os.getenv("INPUT_GPG-KEY", "")
REGISTRY = os.getenv("INPUT_REGISTRY", "JuliaRegistries/General")
REPO = os.getenv("GITHUB_REPOSITORY", "")
REPO_DIR = os.getenv("GITHUB_WORKSPACE", "")
TOKEN = os.getenv("INPUT_TOKEN", "")
