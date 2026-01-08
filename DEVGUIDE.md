# TagBot Developer Guide

> **For AI Agents**: This document serves as both DEVGUIDE.md and AGENTS.md (symlinked).

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Core Workflow](#core-workflow)
4. [Caching Strategy](#caching-strategy)
5. [Error Handling](#error-handling)
6. [Release Process](#release-process)
7. [Deploying the Web Service](#deploying-the-web-service)
8. [Agent Guidelines](#agent-guidelines)

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

## Core Workflow

### Main Execution (`action/__main__.py`)

1. Parse workflow inputs (token, registry, ssh, gpg, changelog config)
2. Create `Repo` instance
3. Check if package is registered → exit if not
4. Call `new_versions()` to find versions needing tags
5. If `dispatch=true`, create dispatch event and wait
6. Configure SSH/GPG keys if provided
7. Determine which version gets "latest" badge
8. For each version: optionally handle release branch, then `create_release()`
9. Handle errors, create manual intervention issue if needed

### Version Discovery (`repo.new_versions()`)

1. `_versions()` parses `Registry/Package/Versions.toml` → `{version: tree_sha}`
2. `_filter_map_versions()` for each version:
   - Skip if tag already exists (uses tags cache)
   - Find commit SHA for tree-sha1:
     - **Primary**: `git log --all --format="%H %T"` cache lookup (O(1))
     - **Fallback**: Search merged registry PRs for commit
3. Returns `{tag_name: commit_sha}` for versions needing tags

### Key Classes

**`Repo` (repo.py)** - Core logic:
- Registry interaction: `_registry_path`, `_versions()`, `_registry_pr()`
- Commit resolution: `_commit_sha_of_tree()`, `_build_tree_to_commit_cache()`
- Release creation: `create_release()`, `configure_ssh()`, `configure_gpg()`
- Error handling: `handle_error()`, `create_issue_for_manual_tag()`

**`Git` (git.py)** - Git operations:
- Clones repo to temp directory on first access
- Uses oauth2 token in clone URL
- Sanitizes output to hide tokens
- Methods: `command()`, `create_tag()`, `set_remote_url()`, `fetch_branch()`, etc.

**`Changelog` (changelog.py)** - Release notes:
- Finds previous release by SemVer
- Collects issues/PRs closed in time range
- Extracts custom notes from registry PR (`<!-- BEGIN RELEASE NOTES -->`)
- Renders Jinja2 template

### Special Features

**Subpackages**: For monorepos with `subdir` input:
- Tag format: `SubPkgA-v1.0.0`
- Tree SHA is for subdir, not root

**Private registries**: With `registry_ssh` input:
- Clones registry via SSH instead of API
- `_registry_pr()` returns None

**GitLab support**: `gitlab.py` wraps python-gitlab to match PyGithub interface.

**SSH keys**: Used when GITHUB_TOKEN can't push (protected branches, workflow files).

**GPG signing**: Optional tag signing via `configure_gpg()`.

---

## Caching Strategy

Performance: 600+ versions in ~4 seconds via aggressive caching.

| Cache | Purpose | Built By |
|-------|---------|----------|
| `__existing_tags_cache` | Skip existing tags | Single API call to `get_git_matching_refs("tags/")` |
| `__tree_to_commit_cache` | Tree SHA → commit | Single `git log --all --format=%H %T` |
| `__registry_prs_cache` | Fallback commit lookup | Fetch up to 300 merged PRs |
| `__commit_datetimes` | "Latest" determination | Lazily built |

**Pattern for new caches**:
```python
def __init__(self, ...):
    self.__cache: Optional[Dict[str, str]] = None

def _build_cache(self) -> Dict[str, str]:
    if self.__cache is not None:
        return self.__cache
    # Build cache...
    self.__cache = result
    return result
```

---

## Error Handling

1. `repo.handle_error()` classifies exceptions:
   - `Abort`: Expected, log only
   - `RequestException`: Transient, allow retry
   - `GithubException`: Check status (5xx/403 = transient, else report)

2. Reportable errors POST to `julia-tagbot.com/report`

3. Web service (`reports.handler()`):
   - Deduplicates by Levenshtein distance on stacktrace
   - Creates/updates issues in [TagBotErrorReports](https://github.com/JuliaRegistries/TagBotErrorReports)

4. Manual intervention: When auto-tag fails (workflow file changes, etc.), creates issue with ready-to-run commands.

---

## Release Process

### Creating a TagBot Release

1. Merge PRs to master
2. Go to [publish.yml workflow](https://github.com/JuliaRegistries/TagBot/actions/workflows/publish.yml)
3. Run with desired version bump (major/minor/patch)
4. Review and merge the created PR
5. CI builds and pushes Docker image to `ghcr.io/juliaregistries/tagbot:{version}`

---

## Deploying the Web Service

The web service runs on AWS Lambda via Serverless Framework.

### Prerequisites

- Node.js and npm
- AWS credentials with deployment permissions
- Docker (for building Linux-compatible packages on macOS)

### Setup

```bash
npm install
aws configure --profile tagbot  # region: us-east-1
```

### Deployment

```bash
# Production (with custom domain julia-tagbot.com)
GITHUB_TOKEN="ghp_..." npx serverless deploy --stage prod --aws-profile tagbot

# Dev (no custom domain)
npx serverless deploy --stage dev --aws-profile tagbot
```

### Configuration

| File | Purpose |
|------|---------|
| `serverless.yml` | Lambda functions, AWS config |
| `requirements.txt` | Python deps for Lambda (keep in sync with pyproject.toml) |
| `package.json` | Serverless plugins |

**Environment variables** (in serverless.yml):
- `GITHUB_TOKEN` - Access to TagBotErrorReports repo
- `TAGBOT_REPO` - Main repo (default: JuliaRegistries/TagBot)
- `TAGBOT_ISSUES_REPO` - Error reports repo (default: JuliaRegistries/TagBotErrorReports)

### Troubleshooting

**Missing Python modules**: Check `requirements.txt`, ensure `serverless-python-requirements` installed, try `rm -rf .requirements .serverless`

**Broken symlinks**: `find . -maxdepth 1 -type l ! -name "AGENTS.md" -delete`

### Checking Logs

```bash
# Recent API function logs (last 5 min)
aws logs filter-log-events --profile tagbot --region us-east-1 \
  --log-group-name /aws/lambda/TagBotWeb-prod-api \
  --start-time $(($(date +%s) * 1000 - 300000)) \
  --query 'events[*].message' --output text

# Reports function logs
aws logs filter-log-events --profile tagbot --region us-east-1 \
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
| Language | Python 3.12+ (Docker uses 3.14, Lambda uses 3.11) |
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

### Performance Rules

- Always use caches (`_build_tags_cache()`, `_build_tree_to_commit_cache()`)
- Batch operations (single API call > per-item calls)
- Git commands > GitHub API
- Lazy loading (build caches when first needed)

### Testing

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install . && pip install pytest pytest-cov black flake8 mypy boto3

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
