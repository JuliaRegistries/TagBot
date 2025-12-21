# TagBot Julia Port Guide

This document describes the Julia port of TagBot (TagBot.jl).

## Status: ✅ Complete

The Julia port is fully implemented and tested with **70 passing tests**.

**Completed**:
- Full feature parity with Python implementation
- Uses GitHub.jl for API interactions
- PrecompileTools integration for fast startup
- Docker deployment ready
- Comprehensive test suite

---

## Architecture

### Module Structure

```
julia/
├── Project.toml          # Dependencies & compat
├── Manifest.toml         # Locked versions
├── Dockerfile            # Container build
├── action.yml            # GitHub Action definition
├── README.md
├── bin/
│   ├── build-docker.sh
│   └── test.sh
├── src/
│   ├── TagBot.jl         # Main module & exports
│   ├── types.jl          # Type definitions (Abort, InvalidProject, RepoConfig, SemVer, etc.)
│   ├── logging.jl        # Logging utilities & sanitization
│   ├── git.jl            # Git command wrapper
│   ├── changelog.jl      # Release notes generation (Mustache templates)
│   ├── repo.jl           # Core logic using GitHub.jl
│   ├── gitlab.jl         # GitLab support
│   ├── main.jl           # Entry point & input parsing
│   └── precompile.jl     # PrecompileTools workload
└── test/
    ├── runtests.jl
    ├── test_changelog.jl
    ├── test_git.jl
    ├── test_repo.jl
    └── test_types.jl
```

### Dependencies

| Julia Package | Purpose |
|---------------|---------|
| `GitHub.jl` | GitHub API client (tags, releases, PRs, issues) |
| `HTTP.jl` | HTTP client (search API fallback) |
| `JSON3.jl` | JSON parsing |
| `TOML` (stdlib) | Registry parsing |
| `Mustache.jl` | Changelog templates |
| `PrecompileTools.jl` | Fast startup |
| `URIs.jl` | URL handling for GitHub Enterprise |
| `SHA` (stdlib) | Hash computations |
| `Base64` (stdlib) | Key decoding |

---

## Key Implementation Details

### GitHub.jl Integration

The `Repo` struct holds GitHub.jl client state:

```julia
mutable struct Repo
    config::RepoConfig
    git::Git
    changelog::Changelog

    # GitHub.jl client
    _api::GitHubAPI              # GitHubWebAPI for GHE
    _auth::GitHub.Authorization  # OAuth2 token
    _gh_repo::Union{GHRepo,Nothing}
    _registry_repo::Union{GHRepo,Nothing}

    # Caches (same as Python)
    _tags_cache::Union{Dict{String,String},Nothing}
    _tree_to_commit_cache::Union{Dict{String,String},Nothing}
    _registry_prs_cache::Union{Dict{String,GitHubPullRequest},Nothing}
    _commit_datetimes::Dict{String,DateTime}
    # ...
end
```

API calls use GitHub.jl methods:
- `GitHub.tags()` - List repository tags
- `GitHub.pull_requests()` - List PRs
- `GitHub.releases()` - List releases
- `GitHub.branch()` - Get branch info
- `GitHub.file()` - Get file contents
- `GitHub.create_release()` - Create release
- `GitHub.create_issue()` - Create manual intervention issue

**HTTP fallback**: `search_issues()` uses raw HTTP since GitHub.jl lacks search API support.

### Caching Strategy

Same O(1) caching as Python:
- `_tags_cache`: tag name → commit SHA
- `_tree_to_commit_cache`: tree SHA → commit SHA (built from `git log`)
- `_registry_prs_cache`: PR branch name → PR object
- `_commit_datetimes`: commit SHA → DateTime

### GitHub Enterprise Support

```julia
api = if api_url == "https://api.github.com"
    GitHub.DEFAULT_API
else
    GitHubWebAPI(URIs.URI(api_url))
end
```

---

    is_registered(repo) || return
    versions = new_versions(repo)
    isempty(versions) && return

    for (version, sha) in versions
        create_release(repo, version, sha)
    end
end

# Core operations
function new_versions(repo::Repo)::Dict{String,String}
function create_release(repo::Repo, version::String, sha::String; is_latest::Bool=true)
function configure_ssh(repo::Repo, key::String, password::Union{String,Nothing})
function configure_gpg(repo::Repo, key::String, password::Union{String,Nothing})
```

---

## Docker Strategy

### Multi-Stage Build

```dockerfile
# Stage 1: Build with precompilation
FROM julia:1.12 AS builder

WORKDIR /app
COPY Project.toml ./
RUN julia --project=. -e 'using Pkg; Pkg.instantiate()'

COPY src/ src/
COPY precompile/ precompile/

# Create system image with precompilation
RUN julia --project=. -e '
    using PackageCompiler
    create_sysimage(
        [:TagBot],
        sysimage_path="tagbot.so",
        precompile_execution_file="precompile/workload.jl"
    )
'

# Stage 2: Minimal runtime
FROM julia:1.12-slim

RUN apt-get update && apt-get install -y git gnupg openssh-client
COPY --from=builder /app/tagbot.so /app/
COPY --from=builder /app/src /app/src
COPY --from=builder /app/Project.toml /app/

WORKDIR /app
CMD ["julia", "-J/app/tagbot.so", "--project=.", "-e", "using TagBot; TagBot.main()"]
```

### Alternative: PrecompileTools Only (Simpler)

```dockerfile
FROM julia:1.12-slim

RUN apt-get update && apt-get install -y git gnupg openssh-client

WORKDIR /app
COPY Project.toml ./
RUN julia --project=. -e 'using Pkg; Pkg.instantiate(); Pkg.precompile()'

COPY src/ src/
# Trigger precompilation
RUN julia --project=. -e 'using TagBot'

CMD ["julia", "--project=.", "-e", "using TagBot; TagBot.main()"]
```

---

## Testing Strategy

1. **Unit Tests**: Mirror Python tests
2. **Integration Tests**: Test against real GitHub API (with mocks)
3. **Docker Tests**: Verify containerized execution

---

## Migration Path

1. **Dual Runtime**: Ship both Python and Julia versions
2. **Environment Variable**: `TAGBOT_RUNTIME=julia` to select
3. **Gradual Rollout**: Default to Python, opt-in to Julia
4. **Full Migration**: After validation, make Julia the default

---

## Timeline

- Phase 1 (Infrastructure): 2-3 hours
- Phase 2 (Core Logic): 4-6 hours
- Phase 3 (Precompilation & Docker): 2-3 hours
- Phase 4 (Testing & Validation): 2-3 hours

Total: ~12-15 hours

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| GitHub.jl API gaps | Fall back to HTTP.jl for missing features |
| Precompilation time | Use PackageCompiler if needed |
| Template compatibility | Adapt changelog template syntax |
| GPG/SSH edge cases | Shell out like Python version |
