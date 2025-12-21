"""
Core Repo operations for TagBot, using GitHub.jl.
"""

# ============================================================================
# Constants
# ============================================================================

# Maximum number of PRs to check when looking for registry PR
const MAX_PRS_TO_CHECK = parse(Int, get(ENV, "TAGBOT_MAX_PRS_TO_CHECK", "300"))

# ============================================================================
# Repo Type
# ============================================================================

"""
    Repo

A Repo has access to its Git repository and registry metadata.
"""
mutable struct Repo
    config::RepoConfig
    git::Git
    changelog::Changelog
    
    # GitHub.jl client state
    _api::GitHubAPI
    _auth::GitHub.Authorization
    _gh_repo::Union{GHRepo,Nothing}
    _registry_repo::Union{GHRepo,Nothing}
    
    # Caches
    _tags_cache::Union{Dict{String,String},Nothing}
    _tree_to_commit_cache::Union{Dict{String,String},Nothing}
    _registry_prs_cache::Union{Dict{String,GitHubPullRequest},Nothing}
    _commit_datetimes::Dict{String,DateTime}
    _registry_path::Union{String,Nothing}
    _registry_url::Union{String,Nothing}
    _project::Union{Dict{String,Any},Nothing}
    _clone_registry::Bool
    _registry_clone_dir::Union{String,Nothing}
    _manual_intervention_issue_url::Union{String,Nothing}
end

function Repo(config::RepoConfig)
    # Create GitHub.jl API client
    api_url = startswith(config.github_api, "http") ? config.github_api : "https://$(config.github_api)"
    api = if api_url == "https://api.github.com"
        GitHub.DEFAULT_API
    else
        GitHubWebAPI(URIs.URI(api_url))
    end
    
    auth = @mock authenticate(config.token)
    
    # Normalize URLs for Git operations
    gh_url = startswith(config.github, "http") ? config.github : "https://$(config.github)"
    
    # Create Git helper
    git = Git(gh_url, config.repo, config.token, config.user, config.email)
    
    # Create Repo first with placeholder changelog
    repo = Repo(
        config,
        git,
        Changelog(nothing, "", String[]),  # Placeholder
        api,
        auth,
        nothing,  # _gh_repo (lazy loaded)
        nothing,  # _registry_repo (lazy loaded)
        nothing,  # _tags_cache
        nothing,  # _tree_to_commit_cache
        nothing,  # _registry_prs_cache
        Dict{String,DateTime}(),  # _commit_datetimes
        nothing,  # _registry_path
        nothing,  # _registry_url
        nothing,  # _project
        !isempty(config.registry_ssh),  # _clone_registry
        nothing,  # _registry_clone_dir
        nothing,  # _manual_intervention_issue_url
    )
    
    # Now create the real changelog with repo reference
    repo.changelog = Changelog(repo, config.changelog_template, config.changelog_ignore)
    
    return repo
end

# ============================================================================
# GitHub.jl Helpers
# ============================================================================

"""
Get the GitHub.jl Repo object for this repository.
"""
function get_gh_repo(repo::Repo)
    if repo._gh_repo === nothing
        METRICS.api_calls += 1
        repo._gh_repo = @mock gh_repo(repo._api, repo.config.repo; auth=repo._auth)
    end
    return repo._gh_repo
end

"""
Get the GitHub.jl Repo object for the registry.
"""
function get_registry_gh_repo(repo::Repo)
    if repo._registry_repo === nothing
        METRICS.api_calls += 1
        repo._registry_repo = @mock gh_repo(repo._api, repo.config.registry; auth=repo._auth)
    end
    return repo._registry_repo
end

# ============================================================================
# Project.toml Access
# ============================================================================

"""
    get_project_value(repo::Repo, key::String)

Get a value from the Project.toml.
"""
function get_project_value(repo::Repo, key::String)
    if repo._project !== nothing
        return string(repo._project[key])
    end
    
    # Try different project file names
    for fname in ["Project.toml", "JuliaProject.toml"]
        filepath = repo.config.subdir !== nothing ? 
            "$(repo.config.subdir)/$fname" : fname
        
        try
            content = get_file_content(repo, filepath)
            repo._project = TOML.parse(content)
            return string(repo._project[key])
        catch e
            e isa KeyError && rethrow(e)
            continue
        end
    end
    
    throw(InvalidProject("Project file was not found"))
end

"""
    get_file_content(repo::Repo, path::String)

Get file content from the repository.
"""
function get_file_content(repo::Repo, path::String)
    METRICS.api_calls += 1
    try
        content_obj = @mock file(repo._api, get_gh_repo(repo), path; auth=repo._auth)
        # Content is base64 encoded by GitHub API
        if content_obj.content !== nothing
            return String(Base64.base64decode(replace(content_obj.content, "\n" => "")))
        end
    catch e
        throw(InvalidProject("File not found: $path"))
    end
    throw(InvalidProject("File not found: $path"))
end

# ============================================================================
# Registry Access
# ============================================================================

"""
    registry_path(repo::Repo)

Get the package's path in the registry repo.
"""
function registry_path(repo::Repo)
    repo._registry_path !== nothing && return repo._registry_path
    
    uuid = lowercase(get_project_value(repo, "uuid"))
    
    # Get Registry.toml
    registry_content = if repo._clone_registry
        registry_dir = registry_clone_dir(repo)
        read(joinpath(registry_dir, "Registry.toml"), String)
    else
        get_registry_file_content(repo, "Registry.toml")
    end
    
    registry = try
        TOML.parse(registry_content)
    catch e
        @warn "Failed to parse Registry.toml: $e"
        return nothing
    end
    
    !haskey(registry, "packages") && return nothing
    
    if haskey(registry["packages"], uuid)
        repo._registry_path = registry["packages"][uuid]["path"]
        return repo._registry_path
    end
    
    return nothing
end

"""
    get_registry_file_content(repo::Repo, path::String)

Get file content from the registry repository.
"""
function get_registry_file_content(repo::Repo, path::String)
    METRICS.api_calls += 1
    try
        content_obj = @mock file(repo._api, get_registry_gh_repo(repo), path; auth=repo._auth)
        if content_obj.content !== nothing
            return String(Base64.base64decode(replace(content_obj.content, "\n" => "")))
        end
    catch e
        throw(InvalidProject("Registry file not found: $path"))
    end
    throw(InvalidProject("Registry file not found: $path"))
end

"""
    registry_clone_dir(repo::Repo)

Clone the registry repository via SSH and return the directory.
"""
function registry_clone_dir(repo::Repo)
    repo._registry_clone_dir !== nothing && return repo._registry_clone_dir
    
    dir = mktempdir(prefix="tagbot_registry_")
    git_command(repo.git, ["init", dir]; repo=nothing)
    
    # Configure SSH for registry access
    configure_ssh(repo, repo.config.registry_ssh, nothing; registry_repo=dir)
    
    # Get host from URL
    gh_url = startswith(repo.config.github, "http") ? repo.config.github : "https://$(repo.config.github)"
    m = match(r"https?://([^/]+)", gh_url)
    host = m !== nothing ? m.captures[1] : repo.config.github
    
    url = "git@$host:$(repo.config.registry).git"
    git_command(repo.git, ["remote", "add", "origin", url]; repo=dir)
    git_command(repo.git, ["fetch", "origin"]; repo=dir)
    git_command(repo.git, ["checkout", default_branch(repo.git; repo=dir)]; repo=dir)
    
    repo._registry_clone_dir = dir
    return dir
end

# ============================================================================
# Version Discovery
# ============================================================================

"""
    get_versions(repo::Repo)

Get all package versions from the registry.
"""
function get_versions(repo::Repo)
    if repo._clone_registry
        return get_versions_clone(repo)
    end
    
    root = registry_path(repo)
    root === nothing && return Dict{String,String}()
    
    try
        content = get_registry_file_content(repo, "$root/Versions.toml")
        versions = TOML.parse(content)
        return Dict(v => versions[v]["git-tree-sha1"] for v in keys(versions))
    catch e
        @debug "Versions.toml was not found: $e"
        return Dict{String,String}()
    end
end

"""
    get_versions_clone(repo::Repo)

Get versions from a cloned registry.
"""
function get_versions_clone(repo::Repo)
    registry_dir = registry_clone_dir(repo)
    root = registry_path(repo)
    root === nothing && return Dict{String,String}()
    
    path = joinpath(registry_dir, root, "Versions.toml")
    !isfile(path) && return Dict{String,String}()
    
    versions = TOML.parsefile(path)
    return Dict(v => versions[v]["git-tree-sha1"] for v in keys(versions))
end

# ============================================================================
# Tag Management
# ============================================================================

"""
    get_tag_prefix(repo::Repo)

Return the package's tag prefix.
"""
function get_tag_prefix(repo::Repo)
    if repo.config.tag_prefix == "NO_PREFIX"
        return "v"
    elseif repo.config.tag_prefix !== nothing
        return "$(repo.config.tag_prefix)-v"
    elseif repo.config.subdir !== nothing
        return "$(get_project_value(repo, "name"))-v"
    else
        return "v"
    end
end

"""
    get_version_tag(repo::Repo, package_version::String)

Return the prefixed version tag.
"""
function get_version_tag(repo::Repo, package_version::String)
    # Remove leading 'v' if present
    version = lstrip(package_version, 'v')
    return get_tag_prefix(repo) * version
end

"""
    build_tags_cache!(repo::Repo; retries::Int=3)

Build a cache of all existing tags mapped to their commit SHAs.
"""
function build_tags_cache!(repo::Repo; retries::Int=3)
    repo._tags_cache !== nothing && return repo._tags_cache
    
    @debug "Building tags cache (fetching all tags)"
    cache = Dict{String,String}()
    last_error = nothing
    
    for attempt in 1:retries
        try
            METRICS.api_calls += 1
            # Use GitHub.jl's tags function
            tags_list, _ = GitHub.tags(repo._api, get_gh_repo(repo); auth=repo._auth)
            
            for tag in tags_list
                tag_name = name(tag)
                # Tag object has sha field
                if tag.object !== nothing
                    obj_type = get(tag.object, "type", "commit")
                    if obj_type == "commit"
                        cache[tag_name] = tag.object["sha"]
                    elseif obj_type == "tag"
                        # Annotated tag - mark for lazy resolution
                        cache[tag_name] = "annotated:$(tag.object["sha"])"
                    end
                elseif tag.sha !== nothing
                    cache[tag_name] = tag.sha
                end
            end
            
            last_error = nothing
            break
        catch e
            last_error = e
            if attempt < retries
                wait_time = 2^(attempt - 1)
                @warn "Failed to fetch tags (attempt $attempt/$retries): $e. Retrying in $(wait_time)s..."
                sleep(wait_time)
            end
        end
    end
    
    if last_error !== nothing
        @error "Could not build tags cache after $retries attempts: $last_error"
    end
    
    @debug "Tags cache built with $(length(cache)) tags"
    repo._tags_cache = cache
    return cache
end

"""
    commit_sha_of_tag(repo::Repo, version_tag::String)

Look up the commit SHA of a given tag.
"""
function commit_sha_of_tag(repo::Repo, version_tag::String)
    tags_cache = build_tags_cache!(repo)
    !haskey(tags_cache, version_tag) && return nothing
    
    sha = tags_cache[version_tag]
    if startswith(sha, "annotated:")
        # Resolve annotated tag to commit SHA via git tag API
        tag_sha = sha[11:end]
        METRICS.api_calls += 1
        
        try
            tag_obj = GitHub.tag(repo._api, get_gh_repo(repo), tag_sha; auth=repo._auth)
            if tag_obj.object !== nothing && haskey(tag_obj.object, "sha")
                resolved_sha = tag_obj.object["sha"]
                tags_cache[version_tag] = resolved_sha
                return resolved_sha
            end
        catch
            return nothing
        end
    end
    
    return sha
end

# ============================================================================
# Tree to Commit Resolution
# ============================================================================

"""
    build_tree_to_commit_cache!(repo::Repo)

Build a cache mapping tree SHAs to commit SHAs.
"""
function build_tree_to_commit_cache!(repo::Repo)
    repo._tree_to_commit_cache !== nothing && return repo._tree_to_commit_cache
    
    @debug "Building tree→commit cache"
    
    if repo.config.subdir === nothing
        # Simple case: use git log
        cache = get_all_tree_commit_pairs(repo.git)
    else
        # Subdir case: need to check subdirectory tree hashes
        cache = Dict{String,String}()
        output = git_command(repo.git, ["log", "--all", "--format=%H"])
        for commit in split(output, '\n')
            isempty(commit) && continue
            subdir_tree = subdir_tree_hash(repo.git, commit, repo.config.subdir; suppress_abort=true)
            if subdir_tree !== nothing && !haskey(cache, subdir_tree)
                cache[subdir_tree] = commit
            end
        end
    end
    
    @debug "Tree→commit cache built with $(length(cache)) entries"
    repo._tree_to_commit_cache = cache
    return cache
end

"""
    commit_sha_of_tree(repo::Repo, tree::String)

Look up the commit SHA of a tree with the given SHA.
"""
function commit_sha_of_tree(repo::Repo, tree::String)
    cache = build_tree_to_commit_cache!(repo)
    return get(cache, tree, nothing)
end

# ============================================================================
# Registry PR Lookup
# ============================================================================

"""
    build_registry_prs_cache!(repo::Repo)

Build a cache of registry PRs indexed by head branch name.
"""
function build_registry_prs_cache!(repo::Repo)
    repo._registry_prs_cache !== nothing && return repo._registry_prs_cache
    repo._clone_registry && return Dict{String,GitHubPullRequest}()
    
    @debug "Building registry PR cache (fetching up to $MAX_PRS_TO_CHECK PRs)"
    cache = Dict{String,GitHubPullRequest}()
    
    prs_fetched = 0
    page = 1
    
    while prs_fetched < MAX_PRS_TO_CHECK
        METRICS.api_calls += 1
        prs, page_data = @mock pull_requests(repo._api, get_registry_gh_repo(repo);
            auth=repo._auth,
            params=Dict("state" => "closed", "sort" => "updated", "direction" => "desc",
                       "per_page" => "100", "page" => string(page)))
        
        isempty(prs) && break
        
        for pr in prs
            METRICS.prs_checked += 1
            prs_fetched += 1
            
            # Only cache merged PRs
            if pr.merged_at !== nothing
                pr_obj = GitHubPullRequest(
                    pr.number,
                    something(pr.title, ""),
                    something(pr.body, ""),
                    true,
                    pr.merged_at,
                    pr.head !== nothing ? name(pr.head) : "",
                    string(pr.html_url),
                    pr.user !== nothing ? name(pr.user) : "",
                    [l["name"] for l in something(pr.labels, [])]
                )
                cache[pr_obj.head_ref] = pr_obj
            end
            
            prs_fetched >= MAX_PRS_TO_CHECK && break
        end
        
        page += 1
    end
    
    @debug "PR cache built with $(length(cache)) merged PRs"
    repo._registry_prs_cache = cache
    return cache
end

"""
    registry_pr(repo::Repo, version::String)

Look up a merged registry pull request for this version.
"""
function registry_pr(repo::Repo, version::String)
    repo._clone_registry && return nothing
    
    pkg_name = get_project_value(repo, "name")
    uuid = lowercase(get_project_value(repo, "uuid"))
    
    url = registry_url(repo)
    url === nothing && return nothing
    
    url_hash = bytes2hex(sha256(url))[1:10]
    
    # Format used by Registrator/PkgDev
    head = "registrator-$(lowercase(pkg_name))-$(uuid[1:8])-$version-$url_hash"
    @debug "Looking for PR from branch $head"
    
    pr_cache = build_registry_prs_cache!(repo)
    if haskey(pr_cache, head)
        pr = pr_cache[head]
        @debug "Found registry PR #$(pr.number) in cache"
        return pr
    end
    
    @debug "Did not find registry PR for branch $head"
    return nothing
end

"""
    registry_url(repo::Repo)

Get the package's repo URL from the registry.
"""
function registry_url(repo::Repo)
    repo._registry_url !== nothing && return repo._registry_url
    
    root = registry_path(repo)
    root === nothing && return nothing
    
    content = if repo._clone_registry
        read(joinpath(registry_clone_dir(repo), root, "Package.toml"), String)
    else
        get_registry_file_content(repo, "$root/Package.toml")
    end
    
    package = TOML.parse(content)
    repo._registry_url = get(package, "repo", nothing)
    return repo._registry_url
end

"""
    commit_sha_from_registry_pr(repo::Repo, version::String, tree::String)

Look up the commit SHA of version from its registry PR.
"""
function commit_sha_from_registry_pr(repo::Repo, version::String, tree::String)
    pr = registry_pr(repo, version)
    pr === nothing && return nothing
    
    m = match(r"- Commit: ([a-f0-9]{32,40})", pr.body)
    m === nothing && return nothing
    
    commit_sha = m.captures[1]
    
    # Verify tree SHA matches
    commit = get_commit(repo, commit_sha)
    commit === nothing && return nothing
    
    if repo.config.subdir !== nothing
        subdir_tree = subdir_tree_hash(repo.git, commit_sha, repo.config.subdir; suppress_abort=false)
        if subdir_tree == tree
            return commit_sha
        else
            @warn "Subdir tree SHA of commit from registry PR does not match"
            return nothing
        end
    end
    
    if commit.tree_sha == tree
        return commit_sha
    else
        @warn "Tree SHA of commit from registry PR does not match"
        return nothing
    end
end

# ============================================================================
# Version Filtering
# ============================================================================

"""
    filter_map_versions(repo::Repo, versions::Dict{String,String})

Filter out versions and convert tree SHA to commit SHA.
"""
function filter_map_versions(repo::Repo, versions::Dict{String,String})
    # Pre-build tags cache
    build_tags_cache!(repo)
    
    valid = Dict{String,String}()
    skipped_existing = 0
    
    for (version, tree) in versions
        version_str = "v$version"
        version_tag = get_version_tag(repo, version_str)
        
        # Fast path: check if tag already exists
        tags_cache = build_tags_cache!(repo)
        if haskey(tags_cache, version_tag)
            skipped_existing += 1
            continue
        end
        
        # Tag doesn't exist - find expected commit SHA
        expected = commit_sha_of_tree(repo, tree)
        if expected === nothing
            @debug "No matching tree for $version_str, falling back to registry PR"
            expected = commit_sha_from_registry_pr(repo, version_str, tree)
        end
        
        if expected === nothing
            @debug "Skipping $version_str: no matching tree or registry PR found"
            continue
        end
        
        valid[version_str] = expected
    end
    
    skipped_existing > 0 && @debug "Skipped $skipped_existing versions with existing tags"
    return valid
end

# ============================================================================
# Public API
# ============================================================================

"""
    is_registered(repo::Repo)

Check whether or not the repository belongs to a registered package.
"""
function is_registered(repo::Repo)
    root = try
        registry_path(repo)
    catch e
        e isa InvalidProject || rethrow(e)
        @debug e.message
        return false
    end
    
    root === nothing && return false
    
    # Verify repo URL matches
    content = if repo._clone_registry
        read(joinpath(registry_clone_dir(repo), root, "Package.toml"), String)
    else
        get_registry_file_content(repo, "$root/Package.toml")
    end
    
    package = TOML.parse(content)
    !haskey(package, "repo") && return false
    
    # Match repo URL
    gh_url = startswith(repo.config.github, "http") ? repo.config.github : "https://$(repo.config.github)"
    m = match(r"https?://([^/]+)", gh_url)
    gh_host = m !== nothing ? replace(m.captures[1], "." => "\\.") : repo.config.github
    
    pattern = if occursin("@", package["repo"])
        Regex("$gh_host:(.*?)(?:\\.git)?\$")
    else
        Regex("$gh_host/(.*?)(?:\\.git)?\$")
    end
    
    m = match(pattern, package["repo"])
    m === nothing && return false
    
    return lowercase(m.captures[1]) == lowercase(repo.config.repo)
end

"""
    new_versions(repo::Repo)

Get all new versions of the package.
"""
function new_versions(repo::Repo)
    start_time = time()
    current = get_versions(repo)
    @info "Found $(length(current)) total versions in registry"
    
    # Check all versions (allows backfilling)
    @debug "Checking all $(length(current)) versions"
    
    # Sort by SemVer
    versions = Dict{String,String}()
    for v in sort(collect(keys(current)), by=SemVer)
        versions[v] = current[v]
        METRICS.versions_checked += 1
    end
    
    result = filter_map_versions(repo, versions)
    elapsed = time() - start_time
    @info "Version check complete: $(length(result)) new versions found " *
          "(checked $(length(current)) total versions in $(round(elapsed, digits=2))s)"
    
    return result
end

"""
    create_release(repo::Repo, version::String, sha::String; is_latest::Bool=true)

Create a GitHub release.
"""
function create_release(repo::Repo, version::String, sha::String; is_latest::Bool=true)
    version_tag = get_version_tag(repo, version)
    target = sha
    
    # Check if we should use branch as target
    try
        branch_sha = commit_sha_of_release_branch(repo)
        if branch_sha == sha
            target = release_branch(repo)
        end
    catch
        # Ignore errors getting branch
    end
    
    @debug "Release $version_tag target: $target"
    
    # Generate changelog
    log = get_changelog(repo.changelog, version_tag, sha)
    
    # Create tag via git (unless draft mode)
    if !repo.config.draft
        create_tag(repo.git, version_tag, sha, log)
    end
    
    @info "Creating GitHub release $version_tag at $sha"
    
    # Create GitHub release using GitHub.jl
    METRICS.api_calls += 1
    @mock gh_create_release(repo._api, get_gh_repo(repo);
        auth=repo._auth,
        params=Dict(
            "tag_name" => version_tag,
            "name" => version_tag,
            "body" => log,
            "target_commitish" => target,
            "draft" => repo.config.draft,
            "make_latest" => is_latest ? "true" : "false",
        ))
    
    @info "GitHub release $version_tag created successfully"
end

"""
    release_branch(repo::Repo)

Get the name of the release branch.
"""
function release_branch(repo::Repo)
    repo.config.branch !== nothing ? repo.config.branch : default_branch(repo.git)
end

"""
    commit_sha_of_release_branch(repo::Repo)

Get the latest commit SHA of the release branch.
"""
function commit_sha_of_release_branch(repo::Repo)
    br = release_branch(repo)
    METRICS.api_calls += 1
    branch_obj = @mock branch(repo._api, get_gh_repo(repo), br; auth=repo._auth)
    branch_obj.commit === nothing && throw(Abort("Could not get release branch"))
    return branch_obj.commit.sha
end

# ============================================================================
# Additional Repo Helpers
# ============================================================================

"""
    get_releases(repo::Repo)

Get all releases for the repository.
"""
function get_releases(repo::Repo)
    result = GitHubRelease[]
    
    METRICS.api_calls += 1
    rels, _ = @mock releases(repo._api, get_gh_repo(repo); auth=repo._auth)
    
    for rel in rels
        push!(result, GitHubRelease(
            something(rel.tag_name, ""),
            rel.created_at !== nothing ? DateTime(rel.created_at[1:19], dateformat"yyyy-mm-ddTHH:MM:SS") : DateTime(0),
            string(rel.html_url)
        ))
    end
    
    return result
end

"""
    get_commit(repo::Repo, sha::String)

Get a commit by SHA.
"""
function get_commit(repo::Repo, sha::String)
    METRICS.api_calls += 1
    try
        c = GitHub.commit(repo._api, get_gh_repo(repo), sha; auth=repo._auth)
        tree_sha = c.commit !== nothing && c.commit.tree !== nothing ? c.commit.tree["sha"] : ""
        author_date = c.commit !== nothing && c.commit.author !== nothing ? 
            DateTime(c.commit.author["date"][1:19], dateformat"yyyy-mm-ddTHH:MM:SS") : DateTime(0)
        
        return GitHubCommit(sha, tree_sha, author_date)
    catch
        return nothing
    end
end

"""
    get_full_name(repo::Repo)

Get the full repository name (owner/repo).
"""
get_full_name(repo::Repo) = repo.config.repo

"""
    get_html_url(repo::Repo)

Get the HTML URL of the repository.
"""
function get_html_url(repo::Repo)
    gh_url = startswith(repo.config.github, "http") ? repo.config.github : "https://$(repo.config.github)"
    return "$gh_url/$(repo.config.repo)"
end

"""
    search_issues(repo::Repo, query::String)

Search issues/PRs using the GitHub search API.
"""
function search_issues(repo::Repo, query::String)
    results = GitHubIssue[]
    
    # GitHub.jl doesn't have search, use HTTP directly for this
    api_url = repo._api isa GitHubWebAPI ? string(repo._api.endpoint) : "https://api.github.com"
    
    page = 1
    while true
        METRICS.api_calls += 1
        url = "$api_url/search/issues?q=$(HTTP.URIs.escapeuri(query))&sort=created&order=asc&per_page=100&page=$page"
        
        resp = @mock HTTP.get(url, [
            "Authorization" => "Bearer $(repo.config.token)",
            "Accept" => "application/vnd.github+json",
        ]; status_exception=false)
        
        resp.status >= 400 && break
        
        data = JSON3.read(String(resp.body))
        items = get(data, :items, [])
        isempty(items) && break
        
        for item in items
            closed_at = if get(item, :closed_at, nothing) !== nothing
                DateTime(item[:closed_at][1:19], dateformat"yyyy-mm-ddTHH:MM:SS")
            else
                nothing
            end
            
            push!(results, GitHubIssue(
                item[:number],
                item[:title],
                something(get(item, :body, nothing), ""),
                closed_at,
                item[:html_url],
                item[:user][:login],
                [l[:name] for l in get(item, :labels, [])],
                get(item, :pull_request, nothing) !== nothing
            ))
        end
        
        # Check if there are more pages
        get(data, :total_count, 0) <= length(results) && break
        page += 1
    end
    
    return results
end

"""
    get_issues(repo::Repo; state::String="all", since::Union{DateTime,Nothing}=nothing)

Get issues from the repository.
"""
function get_issues(repo::Repo; state::String="all", since::Union{DateTime,Nothing}=nothing)
    results = GitHubIssue[]
    
    params = Dict{String,String}("state" => state, "per_page" => "100")
    if since !== nothing
        params["since"] = Dates.format(since, dateformat"yyyy-mm-ddTHH:MM:SS") * "Z"
    end
    
    page = 1
    while true
        params["page"] = string(page)
        METRICS.api_calls += 1
        issue_list, _ = @mock issues(repo._api, get_gh_repo(repo); auth=repo._auth, params=params)
        
        isempty(issue_list) && break
        
        for item in issue_list
            closed_at = item.closed_at
            
            push!(results, GitHubIssue(
                item.number,
                something(item.title, ""),
                something(item.body, ""),
                closed_at,
                string(item.html_url),
                item.user !== nothing ? name(item.user) : "",
                [l["name"] for l in something(item.labels, [])],
                item.pull_request !== nothing
            ))
        end
        
        page += 1
    end
    
    return results
end

"""
    create_manual_intervention_issue(repo::Repo, failures::Vector)

Create an issue requesting manual intervention for failed releases.
"""
function create_manual_intervention_issue(repo::Repo, failures::Vector)
    isempty(failures) && return nothing
    
    # Build issue body
    body = """
    TagBot was unable to automatically create releases for the following versions:
    
    """
    
    for (version, sha, reason) in failures
        tag = get_version_tag(repo, version)
        body *= """
        ### $version
        - Commit: `$sha`
        - Reason: $reason
        
        To manually create this release, run:
        ```bash
        git tag -a $tag $sha -m '$tag'
        git push origin $tag
        gh release create $tag --generate-notes
        ```
        
        """
    end
    
    body *= """
    ---
    *This issue was created by TagBot. See the [TagBot documentation](https://github.com/JuliaRegistries/TagBot) for more information.*
    """
    
    METRICS.api_calls += 1
    issue = @mock gh_create_issue(repo._api, get_gh_repo(repo);
        auth=repo._auth,
        params=Dict(
            "title" => "TagBot: Manual intervention needed for releases",
            "body" => body,
            "labels" => ["tagbot-manual"],
        ))
    
    repo._manual_intervention_issue_url = string(issue.html_url)
    @info "Created manual intervention issue: $(repo._manual_intervention_issue_url)"
    
    return repo._manual_intervention_issue_url
end

"""
    check_rate_limit(repo::Repo)

Check and log the current GitHub API rate limit status.
"""
function check_rate_limit(repo::Repo)
    try
        # Get rate limit using the GitHub API
        api_url = repo._api isa GitHubWebAPI ? string(repo._api.endpoint) : "https://api.github.com"
        
        resp = @mock HTTP.get("$api_url/rate_limit", [
            "Authorization" => "Bearer $(repo.config.token)",
            "Accept" => "application/vnd.github+json",
        ]; status_exception=false)
        
        if resp.status == 200
            data = JSON3.read(String(resp.body))
            core = get(data, :resources, Dict())[:core]
            remaining = get(core, :remaining, 0)
            reset_time = get(core, :reset, 0)
            reset_datetime = Dates.unix2datetime(reset_time)
            
            @info "GitHub API rate limit: $remaining remaining, resets at $reset_datetime"
            
            if remaining == 0
                @warn "GitHub API rate limit exceeded. Please wait until $reset_datetime"
            end
        end
    catch e
        @debug "Could not check rate limit: $e"
    end
end
