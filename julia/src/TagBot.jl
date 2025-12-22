"""
    TagBot

Automatically creates Git tags and GitHub releases for Julia packages when they
are registered in a Julia registry.

This is a Julia port of the original Python TagBot implementation.
"""
module TagBot

using Base64
using Dates
using GitHub
using HTTP
using JSON3
using Logging
using Mocking
using Mustache
using PrecompileTools
using SHA
using TOML
using URIs
using UUIDs

# Explicit GitHub imports for API usage
import GitHub: GitHubAPI, GitHubWebAPI, OAuth2, Repo as GHRepo, PullRequest as GHPullRequest
import GitHub: Issue as GHIssue, Release as GHRelease, Commit as GHCommit, Branch as GHBranch
import GitHub: name, authenticate, repo as gh_repo, pull_requests, issues, releases, commits
import GitHub: file, create_release as gh_create_release, create_issue as gh_create_issue
import GitHub: branch, branches

# Version
const VERSION = v"1.23.4"

# Web service URL
const TAGBOT_WEB = "https://julia-tagbot.com"

# Include core modules
include("types.jl")
include("logging.jl")
include("git.jl")
include("changelog.jl")
include("repo.jl")
include("gitlab.jl")
include("main.jl")
include("precompile.jl")

# Export main types and functions
export Repo, Git, Changelog
export Abort, InvalidProject, RepoConfig, SemVer
export main, new_versions, create_release, is_registered
export configure_ssh, configure_gpg
export get_tag_prefix, get_version_tag

# Internal utilities (not exported but accessible via TagBot.X)
# slug is in changelog.jl

end # module
