# TagBot Developer Guide

> **For AI Agents**: This document serves as both DEVGUIDE.md and AGENTS.md (symlinked).
> Read sections 1-13 for architecture understanding, then follow the [Agent Guidelines](#agent-guidelines)
> at the end for coding conventions and contribution rules.

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Core Workflow](#core-workflow)
4. [Component Details](#component-details)
5. [Data Flow Diagrams](#data-flow-diagrams)
6. [Caching Strategy](#caching-strategy)
7. [Error Handling](#error-handling)
8. [Release Process](#release-process)
9. [Deploying the Web Service](#deploying-the-web-service)
10. [Monitoring](#monitoring)
11. [GitLab Support](#gitlab-support)
12. [SSH and GPG Configuration](#ssh-and-gpg-configuration)
13. [Manual Intervention](#manual-intervention)
14. [Agent Guidelines](#agent-guidelines)

---

## Overview

TagBot automatically creates Git tags and GitHub releases for Julia packages when they are
registered in a Julia registry (typically [General](https://github.com/JuliaRegistries/General)).

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           TagBot High-Level Flow                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Julia Package Repo          Registry (General)         TagBot Action      │
│   ──────────────────          ──────────────────         ────────────────   │
│                                                                             │
│   ┌──────────────┐            ┌──────────────┐           ┌──────────────┐   │
│   │ Project.toml │───────────>│ Versions.toml│<──────────│  new_versions│   │
│   │ (uuid, name) │  register  │ (tree-sha1)  │   query   │     ()       │   │
│   └──────────────┘            └──────────────┘           └──────┬───────┘   │
│                                                                 │           │
│   ┌──────────────┐                                              │           │
│   │ Git History  │<─────────────────────────────────────────────┘           │
│   │ (commits)    │   find commit for tree-sha1                              │
│   └──────┬───────┘                                                          │
│          │                                                                  │
│          v                                                                  │
│   ┌──────────────┐                                                          │
│   │  Git Tag +   │                                                          │
│   │ GH Release   │                                                          │
│   └──────────────┘                                                          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Architecture

TagBot consists of three main components:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            TagBot Components                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                     1. GitHub Action (tagbot/action/)               │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌───────────┐  ┌─────────────┐   │    │
│  │  │ __main__.py │  │   repo.py   │  │  git.py   │  │changelog.py │   │    │
│  │  │ (entrypoint)│  │ (core logic)│  │(git cmds) │  │ (notes gen) │   │    │
│  │  └─────────────┘  └─────────────┘  └───────────┘  └─────────────┘   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                     2. Web Service (tagbot/web/)                    │    │
│  │  ┌─────────────┐  ┌─────────────┐         AWS Lambda                │    │
│  │  │ __init__.py │  │ reports.py  │  ┌────────────────────────┐       │    │
│  │  │ (Flask app) │  │ (error rpts)│  │ julia-tagbot.com       │       │    │
│  │  └─────────────┘  └─────────────┘  └────────────────────────┘       │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                     3. Local CLI (tagbot/local/)                    │    │
│  │  For manual/local usage outside GitHub Actions                      │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### File Structure

```
tagbot/
├── __init__.py           # LogFormatter, logger
├── action/
│   ├── __init__.py       # TAGBOT_WEB, Abort, InvalidProject exceptions
│   ├── __main__.py       # GitHub Action entrypoint
│   ├── changelog.py      # Release notes generation (Jinja2 templates)
│   ├── git.py            # Git command wrapper (clone, tag, push)
│   ├── gitlab.py         # GitLab API wrapper (optional)
│   └── repo.py           # Core logic: version discovery, release creation
├── local/
│   ├── __init__.py
│   └── __main__.py       # CLI entrypoint for local usage
└── web/
    ├── __init__.py       # Flask app, /report endpoint
    ├── reports.py        # Lambda handler for error report processing
    └── templates/        # HTML templates for web UI
```

---

## Core Workflow

### Main Execution Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     GitHub Action Execution Flow                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  action/__main__.py                                                         │
│  ─────────────────                                                          │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────────┐                                                       │
│  │ Parse inputs     │  token, registry, ssh, gpg, changelog, etc.           │
│  │ from workflow    │                                                       │
│  └────────┬─────────┘                                                       │
│           │                                                                 │
│           ▼                                                                 │
│  ┌──────────────────┐     ┌─────────────────────────────────────────────┐   │
│  │ Create Repo      │────>│ Repo(repo, registry, token, changelog, ...) │   │
│  │ instance         │     └─────────────────────────────────────────────┘   │
│  └────────┬─────────┘                                                       │
│           │                                                                 │
│           ▼                                                                 │
│  ┌──────────────────┐                                                       │
│  │ is_registered()? │──No──> Exit (package not in registry)                 │
│  └────────┬─────────┘                                                       │
│           │ Yes                                                             │
│           ▼                                                                 │
│  ┌──────────────────┐                                                       │
│  │ new_versions()   │  Compare registry versions vs existing tags           │
│  └────────┬─────────┘                                                       │
│           │                                                                 │
│           ▼                                                                 │
│  ┌──────────────────┐                                                       │
│  │ No new versions? │──Yes─> Exit                                           │
│  └────────┬─────────┘                                                       │
│           │ Has versions                                                    │
│           ▼                                                                 │
│  ┌──────────────────┐                                                       │
│  │ Dispatch event?  │  (if dispatch=true)                                   │
│  │ Wait for hooks   │  create_dispatch_event(), sleep dispatch_delay        │
│  └────────┬─────────┘                                                       │
│           │                                                                 │
│           ▼                                                                 │
│  ┌──────────────────┐                                                       │
│  │ Configure SSH/   │  (if enabled)                                         │
│  │ GPG keys         │                                                       │
│  └────────┬─────────┘                                                       │
│           │                                                                 │
│           ▼                                                                 │
│  ┌──────────────────┐                                                       │
│  │ Determine which  │  version_with_latest_commit()                         │
│  │ is "latest"      │  Only newest commit gets "latest" badge               │
│  └────────┬─────────┘                                                       │
│           │                                                                 │
│           ▼                                                                 │
│  ┌──────────────────┐                                                       │
│  │ For each version:│                                                       │
│  │  • branches=true?│  handle_release_branch() - merge or create PR         │
│  │  • create_release│  Create git tag + GitHub release                      │
│  └────────┬─────────┘                                                       │
│           │                                                                 │
│           ▼                                                                 │
│  ┌──────────────────┐                                                       │
│  │ Handle errors,   │  Create issue for manual intervention if needed       │
│  │ log metrics      │                                                       │
│  └──────────────────┘                                                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Version Discovery (new_versions)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Version Discovery Flow                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  repo.new_versions()                                                        │
│  ───────────────────                                                        │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────────────────────────────────────────────┐                   │
│  │ _versions()                                          │                   │
│  │                                                      │                   │
│  │   Registry/Package/Versions.toml                     │                   │
│  │   ┌────────────────────────────────────────────┐     │                   │
│  │   │ [1.0.0]                                    │     │                   │
│  │   │ git-tree-sha1 = "abc123..."                │     │                   │
│  │   │                                            │     │                   │
│  │   │ [1.1.0]                                    │     │                   │
│  │   │ git-tree-sha1 = "def456..."                │     │                   │
│  │   └────────────────────────────────────────────┘     │                   │
│  │                                                      │                   │
│  │   Returns: {"1.0.0": "abc123", "1.1.0": "def456"}    │                   │
│  └─────────────────────────┬────────────────────────────┘                   │
│                            │                                                │
│                            ▼                                                │
│  ┌──────────────────────────────────────────────────────┐                   │
│  │ _filter_map_versions()                               │                   │
│  │                                                      │                   │
│  │   For each version:                                  │                   │
│  │   ┌────────────────────────────────────────────────┐ │                   │
│  │   │ 1. Check if tag exists (tags cache)            │ │                   │
│  │   │    └─> Skip if exists                          │ │                   │
│  │   │                                                │ │                   │
│  │   │ 2. Find commit SHA for tree-sha1:              │ │                   │
│  │   │    ┌─────────────────────────────────────────┐ │ │                   │
│  │   │    │ PRIMARY: git log tree lookup (fast)     │ │ │                   │
│  │   │    │   git log --all --format="%H %T"        │ │ │                   │
│  │   │    │   O(1) cache lookup                     │ │ │                   │
│  │   │    └─────────────────────────────────────────┘ │ │                   │
│  │   │              │                                 │ │                   │
│  │   │              ▼ (not found)                     │ │                   │
│  │   │    ┌─────────────────────────────────────────┐ │ │                   │
│  │   │    │ FALLBACK: Registry PR lookup            │ │ │                   │
│  │   │    │   Search merged PRs for version         │ │ │                   │
│  │   │    │   Extract commit from PR body           │ │ │                   │
│  │   │    └─────────────────────────────────────────┘ │ │                   │
│  │   └────────────────────────────────────────────────┘ │                   │
│  │                                                      │                   │
│  │   Returns: {"v1.1.0": "commit_sha_def456"}           │                   │
│  │   (only versions needing tags)                       │                   │
│  └──────────────────────────────────────────────────────┘                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Component Details

### Repo Class (repo.py)

The `Repo` class is the heart of TagBot. Key responsibilities:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Repo Class Structure                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  class Repo:                                                                │
│  ──────────                                                                 │
│                                                                             │
│  Initialization:                                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ • GitHub/GitLab client setup                                        │    │
│  │ • Registry repository reference                                     │    │
│  │ • Changelog template configuration                                  │    │
│  │ • Git helper initialization                                         │    │
│  │ • Various caches (tags, commits, PRs)                               │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  Registry Interaction:                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ _registry_path      → Package path in registry (e.g., "P/PackName") │    │
│  │ _versions()         → Parse Versions.toml for all registered vers   │    │
│  │ _registry_pr()      → Find merged PR that registered a version      │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  Commit Resolution:                                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ _commit_sha_of_tree()         → Tree SHA → Commit SHA (git log)     │    │
│  │ _commit_sha_from_registry_pr()→ Tree SHA → Commit SHA (via PR)      │    │
│  │ _build_tree_to_commit_cache() → Build tree→commit map from git log  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  Release Creation:                                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ create_release()    → Create git tag + GitHub release               │    │
│  │ _changelog.get()    → Generate release notes                        │    │
│  │ configure_ssh()     → Set up SSH key for pushing                    │    │
│  │ configure_gpg()     → Set up GPG for signing tags                   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  Error Handling:                                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ handle_error()               → Report errors to web service         │    │
│  │ create_issue_for_manual_tag()→ Create issue when auto-tag fails     │    │
│  │ _report_error()              → POST to julia-tagbot.com/report      │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Git Class (git.py)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Git Class Methods                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  class Git:                                                                 │
│  ──────────                                                                 │
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────┐         │
│  │ command(*argv)     Execute git command, return stdout          │         │
│  │ check(*argv)       Execute git command, return success bool    │         │
│  │ create_tag(...)    Create annotated tag at commit              │         │
│  │ set_remote_url()   Update origin URL (for SSH)                 │         │
│  │ config(k, v)       Set git config value                        │         │
│  │ fetch_branch()     Fetch specific branch from remote           │         │
│  │ is_merged()        Check if branch is merged into default      │         │
│  │ merge_and_delete() Fast-forward merge and delete branch        │         │
│  │ default_branch()   Get name of default branch                  │         │
│  │ time_of_commit()   Get datetime of a commit                    │         │
│  └────────────────────────────────────────────────────────────────┘         │
│                                                                             │
│  Key Implementation Details:                                                │
│  ┌────────────────────────────────────────────────────────────────┐         │
│  │ • Clones repo to temp directory on first access                │         │
│  │ • Uses oauth2 token in clone URL for authentication            │         │
│  │ • Sanitizes output to hide tokens in logs                      │         │
│  │ • Raises Abort on command failure                              │         │
│  └────────────────────────────────────────────────────────────────┘         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Changelog Class (changelog.py)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Changelog Generation                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  class Changelog:                                                           │
│  ────────────────                                                           │
│                                                                             │
│  Input: version_tag, commit_sha                                             │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────────┐       │
│  │ 1. Find previous release (by SemVer)                             │       │
│  │    - Iterate releases, find highest ver < current ver            │       │
│  └────────────────────────────────────────────────────────────────┬─┘       │
│                                                                   │         │
│         ┌─────────────────────────────────────────────────────────┘         │
│         ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────────┐       │
│  │ 2. Determine time range                                          │       │
│  │    start = previous release commit datetime                      │       │
│  │    end   = current commit datetime                               │       │
│  └────────────────────────────────────────────────────────────────┬─┘       │
│                                                                   │         │
│         ┌─────────────────────────────────────────────────────────┘         │
│         ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────────┐       │
│  │ 3. Collect issues/PRs closed in range                            │       │
│  │    - Filter by labels (ignore "duplicate", "invalid", etc.)      │       │
│  │    - Separate issues from merged PRs                             │       │
│  └────────────────────────────────────────────────────────────────┬─┘       │
│                                                                   │         │
│         ┌─────────────────────────────────────────────────────────┘         │
│         ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────────┐       │
│  │ 4. Fetch custom release notes from registry PR (if any)          │       │
│  │    - Look for <!-- BEGIN RELEASE NOTES --> block                 │       │
│  └────────────────────────────────────────────────────────────────┬─┘       │
│                                                                   │         │
│         ┌─────────────────────────────────────────────────────────┘         │
│         ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────────┐       │
│  │ 5. Render Jinja2 template with:                                  │       │
│  │    - package, version, previous_release, compare_url             │       │
│  │    - issues[], pulls[], custom notes                             │       │
│  │    - backport flag (if version < existing versions)              │       │
│  └──────────────────────────────────────────────────────────────────┘       │
│                                                                             │
│  Output: Rendered markdown release notes                                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow Diagrams

### Registry Lookup Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Registry Package Lookup                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Package Repo (e.g., Example.jl)          Registry (e.g., General)          │
│  ───────────────────────────────          ─────────────────────────         │
│                                                                             │
│  Project.toml:                            Registry.toml:                    │
│  ┌────────────────────┐                   ┌────────────────────────────┐    │
│  │ name = "Example"   │                   │ [packages]                 │    │
│  │ uuid = "abc123..." │──────────────────>│ abc123-... = {             │    │
│  │ version = "1.2.3"  │    lookup by      │   name="Example"           │    │
│  └────────────────────┘    UUID           │   path="E/Example" }       │    │
│                                           └────────────────────────────┘    │
│                                                      │                      │
│                                                      ▼                      │
│                                           E/Example/Package.toml:           │
│                                           ┌────────────────────────────┐    │
│                                           │ name = "Example"           │    │
│                                           │ uuid = "abc123..."         │    │
│                                           │ repo = "github.com/..."    │<───┘
│                                           └────────────────────────────┘    │
│                                                      │  Verify repo matches │
│                                                      ▼                      │
│                                           E/Example/Versions.toml:          │
│                                           ┌────────────────────────────┐    │
│                                           │ [1.0.0]                    │    │
│                                           │ git-tree-sha1 = "aaa..."   │    │
│                                           │                            │    │
│                                           │ [1.2.3]                    │    │
│                                           │ git-tree-sha1 = "bbb..."   │    │
│                                           └────────────────────────────┘    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Tree SHA to Commit SHA Resolution

See the detailed resolution strategy in [Version Discovery](#version-discovery-new_versions).
The key insight: registry stores `git-tree-sha1`, but tags require commit SHAs.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Tree SHA → Commit SHA Resolution                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  _commit_sha_of_tree(tree)                                                  │
│         │                                                                   │
│         ├──────────────────────────────────────────────────────────────┐    │
│         │ PRIMARY: git log --all --format="%H %T"                      │    │
│         │          Build Dict[tree_sha → commit_sha], O(1) lookup      │    │
│         │          Performance: 600+ versions in ~4 seconds            │    │
│         └──────────────────────────────────────────────────────────────┘    │
│         │                                                                   │
│         │ (not found)                                                       │
│         ▼                                                                   │
│         ├──────────────────────────────────────────────────────────────┐    │
│         │ FALLBACK: Registry PR lookup                                 │    │
│         │           Parse commit from PR body: "- Commit: abc123..."   │    │
│         │           Use case: commit not in local clone                │    │
│         └──────────────────────────────────────────────────────────────┘    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Subpackage Support

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Subpackage Handling                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Monorepo structure:                                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  MyMonorepo/                                                        │    │
│  │  ├── Project.toml        (main package)                             │    │
│  │  ├── SubPkgA/                                                       │    │
│  │  │   └── Project.toml    (subpackage A)                             │    │
│  │  └── SubPkgB/                                                       │    │
│  │      └── Project.toml    (subpackage B)                             │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  Tag naming with subdir:                                                    │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  subdir=SubPkgA  →  tag: SubPkgA-v1.0.0                             │    │
│  │  subdir=SubPkgB  →  tag: SubPkgB-v2.0.0                             │    │
│  │  (no subdir)     →  tag: v1.0.0                                     │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  Tree SHA resolution for subpackages:                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Registry tree-sha1 = hash of SubPkgA/ directory                    │    │
│  │                                                                     │    │
│  │  Resolution:                                                        │    │
│  │  1. For each commit, compute: git rev-parse {commit}:{subdir}       │    │
│  │  2. Compare subdir tree hash to registry tree-sha1                  │    │
│  │  3. Build cache: subdir_tree_sha → commit_sha                       │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Private Registry Access

When using a private registry, TagBot clones it via SSH instead of using the API:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Private Registry Access                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  registry_ssh input provided                                                │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ _clone_registry = True                                               │   │
│  │                                                                      │   │
│  │ 1. Create temp directory for registry clone                          │   │
│  │ 2. Configure SSH with registry_ssh key                               │   │
│  │ 3. git clone git@{host}:{registry}.git                               │   │
│  │ 4. Read Registry.toml, Versions.toml from local files                │   │
│  │                                                                      │   │
│  │ Affected methods:                                                    │   │
│  │  • _versions()      → _versions_clone() reads local files            │   │
│  │  • _registry_path   → reads local Registry.toml                      │   │
│  │  • _registry_pr()   → returns None (no API access)                   │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Caching Strategy

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Caching Architecture                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  class Repo caches:                                                         │
│  ──────────────────                                                         │
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ __existing_tags_cache: Dict[str, str]                                  │ │
│  │ ────────────────────────────────────                                   │ │
│  │ Purpose: Avoid per-version API calls to check if tag exists            │ │
│  │ Key:     Tag name (e.g., "v1.2.3")                                     │ │
│  │ Value:   Commit SHA (or "annotated:{sha}" for annotated tags)          │ │
│  │ Built:   Single API call to get_git_matching_refs("tags/")             │ │
│  │ Lookup:  O(1) dictionary access                                        │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ __tree_to_commit_cache: Dict[str, str]                                 │ │
│  │ ─────────────────────────────────────                                  │ │
│  │ Purpose: Fast tree SHA → commit SHA resolution                         │ │
│  │ Key:     Tree SHA (or subdir tree SHA)                                 │ │
│  │ Value:   Commit SHA                                                    │ │
│  │ Built:   Single `git log --all --format=%H %T` command                 │ │
│  │ Lookup:  O(1) dictionary access                                        │ │
│  │                                                                        │ │
│  │ Performance impact:                                                    │ │
│  │ ┌────────────────────────────────────────────────────────────────────┐ │ │
│  │ │ Before (API iteration): O(branches × commits) per version          │ │ │
│  │ │ After (git log cache):  O(1) per version, O(commits) total         │ │ │
│  │ │ Result: 600+ versions processed in ~4 seconds                      │ │ │
│  │ └────────────────────────────────────────────────────────────────────┘ │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ __registry_prs_cache: Dict[str, PullRequest]                           │ │
│  │ ───────────────────────────────────────────                            │ │
│  │ Purpose: Cache merged registry PRs for commit lookup fallback          │ │
│  │ Key:     PR head branch name (registrator-{pkg}-{uuid}-{ver}-{hash})   │ │
│  │ Value:   PullRequest object                                            │ │
│  │ Built:   Fetch up to MAX_PRS_TO_CHECK (default 300) merged PRs         │ │
│  │ Lookup:  O(1) dictionary access                                        │ │
│  │ Used:    Only as fallback when git log lookup fails                    │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ __commit_datetimes: Dict[str, datetime]                                │ │
│  │ ──────────────────────────────────────                                 │ │
│  │ Purpose: Cache commit times for "latest release" determination         │ │
│  │ Key:     Commit SHA                                                    │ │
│  │ Value:   Commit author datetime                                        │ │
│  │ Built:   Lazily, as commits are queried                                │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  class Changelog caches:                                                    │
│  ───────────────────────                                                    │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ __issues_and_pulls: List[Issue | PullRequest]                          │ │
│  │ __range: Tuple[datetime, datetime]                                     │ │
│  │ Purpose: Avoid re-fetching issues/PRs for same time range              │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Error Handling

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Error Handling Flow                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│                         Exception Occurs                                    │
│                               │                                             │
│                               ▼                                             │
│                   ┌───────────────────────┐                                 │
│                   │   repo.handle_error() │                                 │
│                   └───────────┬───────────┘                                 │
│                               │                                             │
│          ┌────────────────────┼────────────────────┐                        │
│          ▼                    ▼                    ▼                        │
│  ┌───────────────┐   ┌───────────────┐   ┌───────────────┐                  │
│  │    Abort      │   │ RequestExcept │   │ GithubExcept  │                  │
│  │ (expected)    │   │ (transient)   │   │ (API error)   │                  │
│  └───────┬───────┘   └───────┬───────┘   └───────┬───────┘                  │
│          │                   │                   │                          │
│          ▼                   ▼                   ▼                          │
│  ┌───────────────┐   ┌───────────────┐   ┌───────────────┐                  │
│  │ Log, no       │   │ Log warning,  │   │ Check status: │                  │
│  │ report        │   │ allow retry   │   │ 5xx: transient│                  │
│  └───────────────┘   └───────────────┘   │ 403: rate lim │                  │
│                                          │ other: report │                  │
│                                          └───────┬───────┘                  │
│                                                  │                          │
│                      ┌───────────────────────────┘                          │
│                      ▼                                                      │
│            ┌───────────────────────────────────────────────────────┐        │
│            │ Should Report?                                        │        │
│            │  • Not a private repo                                 │        │
│            │  • Running in GitHub Actions (GITHUB_ACTIONS=true)    │        │
│            │  • Not an allowed (transient) exception               │        │
│            └───────────────────────────┬───────────────────────────┘        │
│                                        │ Yes                                │
│                                        ▼                                    │
│            ┌───────────────────────────────────────────────────────┐        │
│            │ POST to julia-tagbot.com/report                       │        │
│            │ ───────────────────────────────                       │        │
│            │ {                                                     │        │
│            │   "image": "ghcr.io/juliaregistries/tagbot:1.x.x",    │        │
│            │   "repo": "Owner/PackageName",                        │        │
│            │   "run": "https://github.com/.../actions/runs/123",   │        │
│            │   "stacktrace": "...",                                │        │
│            │   "version": "1.23.0",                                │        │
│            │   "manual_intervention_url": "https://..."            │        │
│            │ }                                                     │        │
│            └───────────────────────────────────────────────────────┘        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Web Service Error Processing

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Error Report Processing (AWS Lambda)                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  julia-tagbot.com/report (Flask)                                            │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────────┐                                                       │
│  │ Lambda: api      │  (serverless-wsgi)                                    │
│  │ Validate payload │                                                       │
│  └────────┬─────────┘                                                       │
│           │                                                                 │
│           ▼                                                                 │
│  ┌──────────────────┐                                                       │
│  │ Invoke Lambda:   │                                                       │
│  │ reports          │  (async, reservedConcurrency=1)                       │
│  └────────┬─────────┘                                                       │
│           │                                                                 │
│           ▼                                                                 │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ reports.handler()                                                    │   │
│  │                                                                      │   │
│  │  ┌────────────────────────────────────────────────────────────────┐  │   │
│  │  │ 1. _find_duplicate(stacktrace)                                 │  │   │
│  │  │    - Search existing issues in TagBotErrorReports              │  │   │
│  │  │    - Compare stacktraces using Levenshtein distance            │  │   │
│  │  │    - Threshold: ratio < 0.1 = duplicate                        │  │   │
│  │  └────────────────────────────────────────────────────────────────┘  │   │
│  │                        │                                             │   │
│  │         ┌──────────────┴──────────────┐                              │   │
│  │         ▼                             ▼                              │   │
│  │  ┌─────────────────┐          ┌─────────────────┐                    │   │
│  │  │ Duplicate found │          │ New error       │                    │   │
│  │  └────────┬────────┘          └────────┬────────┘                    │   │
│  │           │                            │                             │   │
│  │           ▼                            ▼                             │   │
│  │  ┌──────────────────┐         ┌─────────────────┐                    │   │
│  │  │ Already reported │         │ _create_issue() │                    │   │
│  │  │ from this repo?  │         │ in TagBot-      │                    │   │
│  │  └────────┬─────────┘         │ ErrorReports    │                    │   │
│  │           │                   └─────────────────┘                    │   │
│  │     Yes   │   No                                                     │   │
│  │     ▼     ▼                                                          │   │
│  │  [Skip]  [Add comment                                                │   │
│  │          to existing issue]                                          │   │
│  │                                                                      │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Destination: github.com/JuliaRegistries/TagBotErrorReports                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Release Process

### Creating a TagBot Release

1. Merge all desired PRs onto master
2. Go to https://github.com/JuliaRegistries/TagBot/actions/workflows/publish.yml
3. Invoke with the desired major/minor/patch bump
4. Review CI on the PR created & merge to release
5. Review the tag release and edit text appropriately

### Docker Image Publication

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Release & Publish Flow                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  bin/publish.py (workflow_dispatch)                                         │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ 1. Bump version in:                                                  │   │
│  │    - pyproject.toml                                                  │   │
│  │    - action.yml (docker image tag)                                   │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ 2. Create PR with version bump                                       │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│         │                                                                   │
│         ▼ (after merge)                                                     │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ 3. CI builds Docker image                                            │   │
│  │    - FROM python:3.12-slim                                           │   │
│  │    - Install dependencies                                            │   │
│  │    - Push to ghcr.io/juliaregistries/tagbot:{version}                │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ 4. action.yml references new image                                   │   │
│  │    image: docker://ghcr.io/juliaregistries/tagbot:1.x.x              │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Deploying the Web Service

The error reporting web service runs on AWS Lambda and is deployed using the Serverless Framework.

**Prerequisites**:
- Node.js and npm
- AWS credentials with deployment permissions
- Docker (for building Linux-compatible Python packages on macOS)

**Setup**:

```bash
# Install Serverless and plugins
npm install

# Configure AWS credentials
aws configure --profile tagbot
# Set region to us-east-1
```

**Deployment**:

```bash
# Deploy to production
GITHUB_TOKEN="ghp_..." npx serverless deploy --stage prod --aws-profile tagbot

# Deploy to dev (no custom domain)
npx serverless deploy --stage dev --aws-profile tagbot
```

**Configuration files**:
- `serverless.yml` - Lambda function definitions and AWS configuration
- `requirements.txt` - Python dependencies for Lambda (keep in sync with pyproject.toml)
- `package.json` - Serverless plugins

**Environment variables** (set in serverless.yml or AWS console):
- `GITHUB_TOKEN` - Token with access to TagBotErrorReports repo
- `TAGBOT_REPO` - Main TagBot repo (default: JuliaRegistries/TagBot)
- `TAGBOT_ISSUES_REPO` - Error reports repo (default: JuliaRegistries/TagBotErrorReports)

**Troubleshooting**:

If deployment fails with missing Python modules:
1. Ensure `requirements.txt` has all needed dependencies
2. Check that `serverless-python-requirements` plugin is installed
3. Try `rm -rf .requirements .serverless` and redeploy

If you see broken symlinks after deployment:
```bash
find . -maxdepth 1 -type l ! -name "AGENTS.md" -delete
```

**Checking logs**:

View recent Lambda logs via AWS CLI:
```bash
# List log groups
aws logs describe-log-groups --profile tagbot --region us-east-1 \
  --log-group-name-prefix /aws/lambda/TagBotWeb-prod

# Get recent log events from the API function (last 5 minutes)
aws logs filter-log-events --profile tagbot --region us-east-1 \
  --log-group-name /aws/lambda/TagBotWeb-prod-api \
  --start-time $(($(date +%s) * 1000 - 300000)) \
  --query 'events[*].message' --output text

# Get logs from the reports function
aws logs filter-log-events --profile tagbot --region us-east-1 \
  --log-group-name /aws/lambda/TagBotWeb-prod-reports \
  --start-time $(($(date +%s) * 1000 - 300000)) \
  --query 'events[*].message' --output text
```

Or view logs in the AWS Console:
- https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#logsV2:log-groups/log-group/$252Faws$252Flambda$252FTagBotWeb-prod-api
- https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#logsV2:log-groups/log-group/$252Faws$252Flambda$252FTagBotWeb-prod-reports

---

## Monitoring

### Error Reports

TagBot automatically files error reports for unexpected errors:

- **Repository**: https://github.com/JuliaRegistries/TagBotErrorReports
- **Deduplication**: Errors are grouped by stacktrace similarity
- **Metadata**: Each report includes repo name, run URL, TagBot version

### Performance Metrics

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         _PerformanceMetrics                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Tracked metrics (logged at end of each run):                               │
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ api_calls         Total GitHub/GitLab API calls made                   │ │
│  │ prs_checked       Number of registry PRs examined                      │ │
│  │ versions_checked  Number of package versions processed                 │ │
│  │ elapsed           Total wall-clock time                                │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  Example output:                                                            │
│  "Performance: 5 API calls, 0 PRs checked, 623 versions processed, 4.2s"    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Environment Variables

```
TAGBOT_MAX_PRS_TO_CHECK    Maximum registry PRs to fetch (default: 300)
GITHUB_ACTIONS             Set to "true" in GitHub Actions
GITHUB_REPOSITORY          Owner/repo format
GITHUB_EVENT_PATH          Path to event JSON
GITHUB_RUN_ID              Workflow run ID
```

---

## GitLab Support

TagBot supports GitLab repositories with the same core functionality:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          GitLab Integration                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  tagbot/action/gitlab.py                                                    │
│  ───────────────────────                                                    │
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ class GitlabClient:                                                    │ │
│  │   Wraps python-gitlab to match PyGithub interface                      │ │
│  │                                                                        │ │
│  │   Methods:                                                             │ │
│  │   - get_repo()         → Project lookup                                │ │
│  │   - get_contents()     → File contents                                 │ │
│  │   - get_commits()      → Commit history                                │ │
│  │   - get_pulls()        → Merge requests                                │ │
│  │   - create_git_release()→ Tag + release                                │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  Usage:                                                                     │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ with:                                                                  │ │
│  │   token: ${{ secrets.GITLAB_TOKEN }}                                   │ │
│  │   github: https://gitlab.com                                           │ │
│  │   github_api: https://gitlab.com                                       │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## SSH and GPG Configuration

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     SSH Key Configuration Flow                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  configure_ssh(key, password)                                               │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ 1. Decode key (Base64 or PEM format)                                 │   │
│  │ 2. Validate key format                                               │   │
│  │ 3. Write key to temp file (chmod 400)                                │   │
│  │ 4. Generate known_hosts via ssh-keyscan                              │   │
│  │ 5. Configure git core.sshCommand                                     │   │
│  │ 6. If password: start ssh-agent, add identity                        │   │
│  │ 7. Update remote URL to SSH format                                   │   │
│  │ 8. Test authentication                                               │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Why SSH keys?                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ • GITHUB_TOKEN cannot trigger other workflows                        │   │
│  │ • GITHUB_TOKEN cannot push to protected branches                     │   │
│  │ • GITHUB_TOKEN cannot modify workflow files                          │   │
│  │                                                                      │   │
│  │ SSH deploy keys bypass these limitations                             │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                     GPG Signing Configuration                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  configure_gpg(key, password)                                               │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ 1. Create temp GNUPGHOME directory                                   │   │
│  │ 2. Import GPG key with python-gnupg                                  │   │
│  │ 3. If password: sign dummy data to cache passphrase in agent         │   │
│  │ 4. Configure git tag.gpgSign=true                                    │   │
│  │ 5. Configure git user.signingKey                                     │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Manual Intervention

When TagBot cannot automatically create a release (e.g., workflow file modifications):

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Manual Intervention Issue Creation                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Triggers:                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ • Commit modifies .github/workflows/ files                             │ │
│  │ • "Resource not accessible by integration" error                       │ │
│  │ • Git command failures (push rejected, etc.)                           │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  create_issue_for_manual_tag(failures)                                      │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ Creates issue with:                                                  │   │
│  │  - Title: "TagBot: Manual intervention needed for releases"          │   │
│  │  - Label: "tagbot-manual" (created if doesn't exist)                 │   │
│  │  - Body:                                                             │   │
│  │    • List of versions needing release                                │   │
│  │    • Ready-to-run git/gh commands                                    │   │
│  │    • Prevention tips (PAT with workflow scope)                       │   │
│  │    • Link to run logs                                                │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Example commands generated:                                                │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ git tag -a v1.2.3 abc123 -m 'v1.2.3' && \                              │ │
│  │   git push origin v1.2.3 && \                                          │ │
│  │   gh release create v1.2.3 --generate-notes                            │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Agent Guidelines

This section provides instructions for AI coding agents working on TagBot.

### Quick Reference

```
Language:       Python 3.12+
Formatter:      black
Linter:         flake8
Type Checker:   mypy (with stubs in stubs/)
Test Framework: pytest
Package Manager: pip (pyproject.toml)
```

### Project Structure Rules

```
tagbot/
├── __init__.py        # Shared: LogFormatter, logger
├── action/            # GitHub Action code (runs in Docker)
│   ├── __main__.py    # Entry point - parse inputs, orchestrate
│   ├── repo.py        # Core logic - DO NOT split this file
│   ├── git.py         # Git operations wrapper
│   ├── changelog.py   # Release notes generation
│   └── gitlab.py      # GitLab API adapter (optional)
├── local/             # CLI for manual local usage
└── web/               # AWS Lambda error reporting service
    ├── __init__.py    # Flask app
    └── reports.py     # Error deduplication logic
```

### Coding Conventions

**Style**:
- Use `black` for formatting (run `make black` to check)
- Maximum line length: 88 characters (black default)
- Use type hints for all function signatures
- Prefer `Optional[X]` over `X | None` for consistency with existing code

**Naming**:
- Private methods/attributes: single underscore prefix (`_method`)
- Cache attributes: double underscore prefix (`__cache`)
- Constants: UPPER_SNAKE_CASE
- Classes: PascalCase
- Functions/methods: snake_case

**Imports**:
- Group: stdlib, then third-party, then local
- Sort alphabetically within groups
- Use absolute imports for cross-module references

**Logging**:
- Use `from .. import logger` (not stdlib logging directly)
- Log levels: DEBUG for internal details, INFO for user-facing, WARNING/ERROR for problems
- Never log secrets (use `_sanitize()` method)

### Design Principles

Follow these principles when making changes:

1. **YAGNI** - Don't add features "just in case"
2. **SOLID** - Single responsibility, especially for new methods
3. **KISS** - Prefer simple solutions over clever ones
4. **DRY** - Use caching to avoid repeated API calls (see Caching Strategy)
5. **SRP** - Each method should do one thing well

### Performance Considerations

TagBot processes packages with 600+ versions in ~4 seconds. Maintain this by:

- **Always use caches**: `_build_tags_cache()`, `_build_tree_to_commit_cache()`
- **Batch operations**: Prefer single API call over per-item calls
- **Lazy loading**: Build caches only when first needed
- **Git over API**: Local git commands are faster than GitHub API

```python
# GOOD: O(1) lookup after cache build
cache = self._build_tree_to_commit_cache()
commit = cache.get(tree_sha)

# BAD: O(n) API calls
for commit in repo.get_commits():  # Paginated API calls!
    if commit.tree.sha == tree_sha:
        return commit
```

### Testing Requirements

**Local development setup**:

```bash
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install package with dependencies
pip install .

# Install dev tools
pip install pytest pytest-cov black flake8 mypy boto3
```

**Before submitting changes**:

```bash
# Run all checks (recommended)
make test

# Or run individual checks via make targets
make pytest    # Run tests with coverage
make black     # Check formatting
make flake8    # Lint
make mypy      # Type check
```

**Test file locations**:
- `test/action/` - Tests for GitHub Action components
- `test/web/` - Tests for web service
- `test/test_tagbot.py` - Integration tests

**Mocking guidelines**:
- Mock external services (GitHub API, git commands)
- Use `unittest.mock.patch` or pytest fixtures
- Don't mock internal caches - test the real caching behavior

### Common Patterns

**Adding a new cache**:
```python
def __init__(self, ...):
    self.__new_cache: Optional[Dict[str, str]] = None

def _build_new_cache(self) -> Dict[str, str]:
    if self.__new_cache is not None:
        return self.__new_cache
    # Build cache...
    self.__new_cache = result
    return result
```

**Handling API errors**:
```python
try:
    result = self._repo.some_api_call()
except GithubException as e:
    if e.status == 404:
        return None  # Expected case
    raise  # Unexpected - let handle_error() deal with it
```

**Adding optional functionality**:
```python
# Check input before doing work
if not some_input:
    return  # Early return if feature not enabled
```

### What NOT to Do

- ❌ Don't add print statements (use logger)
- ❌ Don't catch broad `Exception` without re-raising
- ❌ Don't make API calls in loops without caching
- ❌ Don't store secrets in variables longer than necessary
- ❌ Don't modify `action.yml` without also updating `pyproject.toml` version
- ❌ Don't add dependencies without updating `pyproject.toml`
- ❌ Don't use emoji in code comments (sparingly OK in user-facing text)

### Making Changes Checklist

- [ ] Read relevant sections of this guide first
- [ ] Understand the data flow (see diagrams above)
- [ ] Check if caching already exists for your use case
- [ ] Write tests for new functionality
- [ ] Run `make test` to verify all checks pass
- [ ] Update DEVGUIDE.md if architecture changes

### Commit Message Format

```
Short summary (50 chars or less)

Longer description if needed. Explain what and why,
not how (the code shows how).

Co-authored-by: Name <email>  # If pair programming with AI
```
