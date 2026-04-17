# TagBot Developer Guide

> **For AI Agents**: This document serves as both DEVGUIDE.md and AGENTS.md (symlinked).

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Special Features](#special-features)
4. [Error Handling](#error-handling)
5. [Release Process](#release-process)
6. [Deploying the Web Service](#deploying-the-web-service)
7. [Agent Guidelines](#agent-guidelines)

---

## Overview

TagBot automatically creates Git tags and GitHub releases for Julia packages when they are registered in a Julia registry (typically [General](https://github.com/JuliaRegistries/General)).

**Flow**: Package registered → TagBot queries registry for tree-sha1 → finds matching commit → creates tag + release.

---

## Architecture

TagBot has three components:

| Component | Location | Purpose |
|-----------|----------|---------|
| GitHub Action | `tagbot/action/` | Main functionality, runs in Docker |
| Web Service | `tagbot/web/` | Error reporting API on AWS Lambda (julia-tagbot.com) |
| Local CLI | `tagbot/local/` | Manual usage outside GitHub Actions |

### File Structure

```
tagbot/
├── __init__.py           # LogFormatter, logger
├── action/
│   ├── __init__.py       # TAGBOT_WEB, Abort, InvalidProject exceptions
│   ├── __main__.py       # GitHub Action entrypoint
│   ├── changelog.py      # Release notes generation (Jinja2)
│   ├── git.py            # Git command wrapper
│   ├── gitlab.py         # GitLab API wrapper (optional)
│   └── repo.py           # Core logic: version discovery, release creation
├── local/
│   └── __main__.py       # CLI entrypoint
└── web/
    ├── __init__.py       # Flask app, /report endpoint
    ├── reports.py        # Error report processing
    └── templates/        # HTML templates
```

---

## Special Features

**Subpackages**: For monorepos with `subdir` input, tag format is `SubPkgA-v1.0.0`.

**Private registries**: With `registry_ssh` input, the registry is cloned via SSH instead of the API.

**GitLab support**: `gitlab.py` provides a PyGithub-compatible wrapper for python-gitlab.

**SSH keys**: Used when `GITHUB_TOKEN` can't push (e.g. protected branches, workflow files).

**GPG signing**: Optional tag signing via the `gpg` input.

---

## Error Handling

Errors are classified as expected (`Abort`), transient (network/5xx), or reportable. Reportable errors are POSTed to `julia-tagbot.com/report`, where the web service deduplicates by stacktrace similarity and creates/updates issues in [TagBotErrorReports](https://github.com/JuliaRegistries/TagBotErrorReports).

When auto-tagging fails due to workflow file changes or other manual intervention requirements, TagBot creates an issue with ready-to-run commands.

---

## Release Process

### Creating a TagBot Release

1. Merge PRs to master
2. Go to [publish.yml workflow](https://github.com/JuliaRegistries/TagBot/actions/workflows/publish.yml)
3. Run with desired version bump (major/minor/patch) and approve the `production` environment gate
4. The workflow builds and pushes the versioned Docker image, commits the version bump to master, creates the Git tag and GitHub release, pushes floating Docker tags (`latest`, `{major}`, `{major}.{minor}`), and commits updated SHA pins to `example.yml`, `README.md`, and other doc files

---

## Deploying the Web Service

The web service runs on AWS Lambda via AWS SAM.

### Prerequisites

- AWS SAM CLI (`brew install aws-sam-cli` or `pip install aws-sam-cli`)
- AWS credentials with deployment permissions
- Python 3.12+ venv (the Makefile uses `--platform manylinux2014_x86_64` pip flags to cross-install Linux wheels, so Docker is **not** required)

### Setup

```bash
aws configure --profile julia_tagbot  # region: us-east-1
```

### Deployment

```bash
# Activate the venv (must be Python 3.12+ so pip markers match)
source .venv/bin/activate

# Pre-generate requirements.txt (poetry is not available in Lambda build containers)
poetry export --extras web --without-hashes --output requirements.txt

# Production (with custom domain julia-tagbot.com)
sam build && sam deploy --config-env prod \
  --parameter-overrides "TagbotCommit=$(git rev-parse HEAD)" \
  --profile julia_tagbot

# Dev
sam build && sam deploy \
  --parameter-overrides "TagbotCommit=$(git rev-parse HEAD)" \
  --profile julia_tagbot
```

> **Note**: Do NOT use `sam build --use-container`. SAM's CopySource follows symlinks in `.venv/` which don't exist inside the container, causing build failures. The Makefile's `--platform manylinux2014_x86_64 --only-binary=:all:` pip flags handle cross-compilation without Docker.

### Configuration

| File | Purpose |
|------|---------|
| `template.yaml` | SAM template: Lambda functions, API Gateway, IAM |
| `samconfig.toml` | Deploy config per environment |

**Parameters** (in template.yaml, pass via `--parameter-overrides`):
- `GithubTokenParam` - SSM parameter name for the GitHub token (default: `/tagbot/github-token`)
- `TagbotRepo` - Main repo (default: JuliaRegistries/TagBot)
- `TagbotIssuesRepo` - Error reports repo (default: JuliaRegistries/TagBotErrorReports)
- `TagbotCommit` - Git commit SHA shown on index page (default: unknown)

The GitHub token is stored in SSM Parameter Store as a SecureString at `/tagbot/github-token` and read at runtime by the reports Lambda.

### Troubleshooting

**Missing Python modules on Lambda** (`No module named 'flask'`): Your local Python is likely < 3.12, so pip skips packages with `python_version >= "3.12"` markers. Use the `.venv` (Python 3.13) or ensure `--python-version 3.12` is passed to pip.

**Invalid ELF header on Lambda** (`_rust.abi3.so: invalid ELF header`): Native extensions were built for macOS. The Makefile passes `--platform manylinux2014_x86_64 --only-binary=:all:` to pip, which installs Linux wheels. If this still happens, run `rm -rf .aws-sam/` and rebuild.

**`sam build --use-container` fails with `.venv`**: SAM's CopySource tries to follow `.venv/bin/python3` symlinks inside the container where they don't exist. `.samignore` does not help. Use the default `sam build` (without `--use-container`) instead.

**Stale cached state**: Try `rm -rf .aws-sam/` and rebuild.

### Checking Logs

Log group names include CloudFormation-generated suffixes. Discover them first:

```bash
aws logs describe-log-groups --profile julia_tagbot --region us-east-1 \
  --log-group-name-prefix /aws/lambda/TagBotWeb-prod \
  --query 'logGroups[*].logGroupName' --output text
```

Then query with the actual names:

```bash
# Recent API function logs (last 5 min)
aws logs filter-log-events --profile julia_tagbot --region us-east-1 \
  --log-group-name /aws/lambda/TagBotWeb-prod-ApiFunction-XXXX \
  --start-time $(($(date +%s) * 1000 - 300000)) \
  --query 'events[*].message' --output text

# Reports function logs
aws logs filter-log-events --profile julia_tagbot --region us-east-1 \
  --log-group-name /aws/lambda/TagBotWeb-prod-ReportsFunction-XXXX \
  --start-time $(($(date +%s) * 1000 - 300000)) \
  --query 'events[*].message' --output text
```

Or view in [AWS Console](https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#logsV2:log-groups).

### Updating the GitHub Token

The reports Lambda reads the GitHub PAT from SSM at runtime and caches it globally. After updating the token, you must force a cold start:

```bash
# Update the token
aws ssm put-parameter --profile julia_tagbot --region us-east-1 \
  --name /tagbot/github-token --type SecureString \
  --value "ghp_XXXXX" --overwrite

# Force cold start (updates description to invalidate warm instances)
aws lambda update-function-configuration --profile julia_tagbot --region us-east-1 \
  --function-name TagBotWeb-prod-ReportsFunction-XXXX \
  --description "Force cold start $(date +%s)"
```

---

## Agent Guidelines

### Quick Reference

| Item | Value |
|------|-------|
| Language | Python 3.12+ (Docker uses 3.14, Lambda uses 3.12) |
| Formatter | black |
| Linter | flake8 |
| Type Checker | mypy (stubs in `stubs/`) |
| Tests | pytest |
| Package Manager | pip (pyproject.toml) |

### Coding Conventions

**Style**:
- `black` formatting, 88 char lines
- Type hints on all functions
- Prefer `Optional[X]` over `X | None`

**Naming**:
- `_method` for private
- `__cache` for cache attributes
- `UPPER_SNAKE` for constants

**Logging**:
- Use `from .. import logger`
- Never log secrets (use `_sanitize()`)

### Design Principles

1. **YAGNI** - Don't add features "just in case"
2. **KISS** - Simple over clever
3. **DRY** - Use caching for repeated operations
4. **SRP** - Each method does one thing

### Testing

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install '.[all]' && pip install pytest pytest-cov black flake8 mypy boto3

# Run all checks
make test

# Individual checks
make pytest black flake8 mypy
```

**Test locations**: `test/action/`, `test/web/`, `test/test_tagbot.py`

### What NOT to Do

- ❌ Print statements (use logger)
- ❌ Catch broad `Exception` without re-raising
- ❌ API calls in loops without caching
- ❌ Store secrets longer than necessary
- ❌ Modify `action.yml` without updating `pyproject.toml` version
- ❌ Add dependencies without updating `pyproject.toml`

### Checklist

- [ ] Understand the data flow
- [ ] Check if caching exists for your use case
- [ ] Write tests
- [ ] Run `make test`
- [ ] Update DEVGUIDE.md if architecture changes
