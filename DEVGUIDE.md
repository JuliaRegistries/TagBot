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
- Docker (for building Linux-compatible packages on macOS)

### Setup

```bash
aws configure --profile julia_tagbot  # region: us-east-1
```

### Deployment

```bash
# Production (with custom domain julia-tagbot.com)
sam build && sam deploy --config-env prod \
  --parameter-overrides "GithubToken=ghp_... TagbotCommit=$(git rev-parse HEAD)" \
  --profile julia_tagbot

# Dev
sam build && sam deploy \
  --parameter-overrides "TagbotCommit=$(git rev-parse HEAD)" \
  --profile julia_tagbot
```

### Configuration

| File | Purpose |
|------|---------|
| `template.yaml` | SAM template: Lambda functions, API Gateway, IAM |
| `samconfig.toml` | Deploy config per environment |
| `requirements.txt` | Python deps for Lambda (keep in sync with pyproject.toml) |

**Parameters** (in template.yaml, pass via `--parameter-overrides`):
- `GithubToken` - Access to TagBotErrorReports repo
- `TagbotRepo` - Main repo (default: JuliaRegistries/TagBot)
- `TagbotIssuesRepo` - Error reports repo (default: JuliaRegistries/TagBotErrorReports)
- `TagbotCommit` - Git commit SHA shown on index page (default: unknown)
- `Stage` - dev or prod (default: dev)

### Troubleshooting

**Missing Python modules**: Check `requirements.txt`, try `rm -rf .aws-sam/`

**Build issues**: `sam build --use-container` to build in a Docker container matching the Lambda runtime

### Checking Logs

```bash
# Recent API function logs (last 5 min)
aws logs filter-log-events --profile julia_tagbot --region us-east-1 \
  --log-group-name /aws/lambda/TagBotWeb-prod-api \
  --start-time $(($(date +%s) * 1000 - 300000)) \
  --query 'events[*].message' --output text

# Reports function logs
aws logs filter-log-events --profile julia_tagbot --region us-east-1 \
  --log-group-name /aws/lambda/TagBotWeb-prod-reports \
  --start-time $(($(date +%s) * 1000 - 300000)) \
  --query 'events[*].message' --output text
```

Or view in [AWS Console](https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#logsV2:log-groups).

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
