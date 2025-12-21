"""
Type definitions for TagBot.
"""

# ============================================================================
# Exception Types
# ============================================================================

"""
    Abort <: Exception

Exception raised when TagBot encounters an expected failure condition.
This is used for characterized failures like git command failures.
"""
struct Abort <: Exception
    message::String
end

Base.showerror(io::IO, e::Abort) = print(io, "Abort: ", e.message)

"""
    InvalidProject <: Exception

Exception raised when the Project.toml is invalid or missing required fields.
"""
struct InvalidProject <: Exception
    message::String
end

Base.showerror(io::IO, e::InvalidProject) = print(io, "InvalidProject: ", e.message)

# ============================================================================
# Configuration Types
# ============================================================================

"""
    RepoConfig

Configuration for a TagBot Repo instance.
"""
Base.@kwdef struct RepoConfig
    repo::String
    registry::String = "JuliaRegistries/General"
    github::String = "github.com"
    github_api::String = "api.github.com"
    token::String
    changelog_template::String = DEFAULT_CHANGELOG_TEMPLATE
    changelog_ignore::Vector{String} = copy(DEFAULT_CHANGELOG_IGNORE)
    ssh::Bool = false
    gpg::Bool = false
    draft::Bool = false
    registry_ssh::String = ""
    user::String = "github-actions[bot]"
    email::String = "41898282+github-actions[bot]@users.noreply.github.com"
    branch::Union{String,Nothing} = nothing
    subdir::Union{String,Nothing} = nothing
    tag_prefix::Union{String,Nothing} = nothing
end

# Default changelog template (Mustache syntax)
const DEFAULT_CHANGELOG_TEMPLATE = """
## {{ package }} {{ version }}

{{#previous_release}}
[Diff since {{ previous_release }}]({{ compare_url }})
{{/previous_release}}

{{#custom}}
{{ custom }}
{{/custom}}

{{#backport}}
This release has been identified as a backport.
Automated changelogs for backports tend to be wildly incorrect.
Therefore, the list of issues and pull requests is hidden.
<!--
{{/backport}}

{{#pulls}}
**Merged pull requests:**
{{#pulls}}
- {{ title }} (#{{ number }}) (@{{ author_username }})
{{/pulls}}
{{/pulls}}

{{#issues}}
**Closed issues:**
{{#issues}}
- {{ title }} (#{{ number }})
{{/issues}}
{{/issues}}

{{#backport}}
-->
{{/backport}}
"""

# Default labels to ignore in changelog
const DEFAULT_CHANGELOG_IGNORE = [
    "changelog skip",
    "duplicate",
    "exclude from changelog",
    "invalid",
    "no changelog",
    "question",
    "skip changelog",
    "wont fix",
]

# ============================================================================
# SemVer Type
# ============================================================================

"""
    SemVer

A semantic version number.
"""
struct SemVer
    major::Int
    minor::Int
    patch::Int
    prerelease::Union{String,Nothing}
    build::Union{String,Nothing}
end

function SemVer(s::AbstractString)
    # Remove leading 'v' if present
    s = lstrip(s, 'v')

    # Split on + for build metadata
    parts = split(s, '+', limit=2)
    build = length(parts) > 1 ? String(parts[2]) : nothing
    main = parts[1]

    # Split on - for prerelease
    parts = split(main, '-', limit=2)
    prerelease = length(parts) > 1 ? String(parts[2]) : nothing
    version_str = parts[1]

    # Parse major.minor.patch
    nums = split(version_str, '.')
    if length(nums) < 2
        throw(ArgumentError("Invalid version: $s"))
    end

    major = parse(Int, nums[1])
    minor = parse(Int, nums[2])
    patch = length(nums) >= 3 ? parse(Int, nums[3]) : 0

    SemVer(major, minor, patch, prerelease, build)
end

Base.isless(a::SemVer, b::SemVer) = begin
    a.major != b.major && return a.major < b.major
    a.minor != b.minor && return a.minor < b.minor
    a.patch != b.patch && return a.patch < b.patch
    # Prerelease versions are less than release versions
    if a.prerelease !== nothing && b.prerelease === nothing
        return true
    elseif a.prerelease === nothing && b.prerelease !== nothing
        return false
    elseif a.prerelease !== nothing && b.prerelease !== nothing
        return a.prerelease < b.prerelease
    end
    return false
end

Base.:(==)(a::SemVer, b::SemVer) =
    a.major == b.major && a.minor == b.minor && a.patch == b.patch &&
    a.prerelease == b.prerelease

Base.string(v::SemVer) = begin
    s = "$(v.major).$(v.minor).$(v.patch)"
    v.prerelease !== nothing && (s *= "-$(v.prerelease)")
    v.build !== nothing && (s *= "+$(v.build)")
    s
end

Base.show(io::IO, v::SemVer) = print(io, "v", string(v))

# ============================================================================
# Performance Metrics
# ============================================================================

"""
    PerformanceMetrics

Track performance metrics for API calls and processing.
"""
mutable struct PerformanceMetrics
    api_calls::Int
    prs_checked::Int
    versions_checked::Int
    start_time::Float64
end

PerformanceMetrics() = PerformanceMetrics(0, 0, 0, time())

function reset!(m::PerformanceMetrics)
    m.api_calls = 0
    m.prs_checked = 0
    m.versions_checked = 0
    m.start_time = time()
end

function log_summary(m::PerformanceMetrics)
    elapsed = time() - m.start_time
    @info "Performance: $(m.api_calls) API calls, $(m.prs_checked) PRs checked, " *
          "$(m.versions_checked) versions processed, $(round(elapsed, digits=2))s elapsed"
end

# Global metrics instance
const METRICS = PerformanceMetrics()

# ============================================================================
# GitHub API Types
# ============================================================================

"""
    GitHubRelease

Represents a GitHub release.
"""
struct GitHubRelease
    tag_name::String
    created_at::DateTime
    html_url::String
end

"""
    GitHubPullRequest

Represents a GitHub pull request.
"""
struct GitHubPullRequest
    number::Int
    title::String
    body::String
    merged::Bool
    merged_at::Union{DateTime,Nothing}
    head_ref::String
    html_url::String
    user_login::String
    labels::Vector{String}
end

"""
    GitHubIssue

Represents a GitHub issue.
"""
struct GitHubIssue
    number::Int
    title::String
    body::String
    closed_at::Union{DateTime,Nothing}
    html_url::String
    user_login::String
    labels::Vector{String}
    is_pull_request::Bool
end

"""
    GitHubCommit

Represents a GitHub commit.
"""
struct GitHubCommit
    sha::String
    tree_sha::String
    author_date::DateTime
end

"""
    GitHubRef

Represents a GitHub git reference (tag/branch).
"""
struct GitHubRef
    ref::String
    sha::String
    type::String  # "commit" or "tag"
end
