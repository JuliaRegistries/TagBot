"""
Git operations for TagBot.
"""

# ============================================================================
# Git Type
# ============================================================================

"""
    Git

Provides access to a local Git repository.
"""
mutable struct Git
    github::String
    repo::String
    token::String
    user::String
    email::String
    gpgsign::Bool
    _default_branch::Union{String,Nothing}
    _dir::Union{String,Nothing}
end

function Git(github::String, repo::String, token::String, user::String, email::String)
    # Extract hostname from URL if needed
    github_host = if startswith(github, "http")
        m = match(r"https?://([^/]+)", github)
        m === nothing ? github : m.captures[1]
    else
        github
    end
    Git(github_host, repo, token, user, email, false, nothing, nothing)
end

# ============================================================================
# Repository Access
# ============================================================================

"""
    repo_dir(git::Git)

Get the repository clone location (cloning if necessary).
"""
function repo_dir(git::Git)
    git._dir !== nothing && return git._dir
    
    url = "https://oauth2:$(git.token)@$(git.github)/$(git.repo)"
    dest = mktempdir(prefix="tagbot_repo_")
    
    git_command(git, ["clone", url, dest]; repo=nothing)
    git._dir = dest
    return dest
end

# ============================================================================
# Git Commands
# ============================================================================

"""
    git_command(git::Git, args::Vector{String}; repo::Union{String,Nothing}="")

Run a Git command and return stdout.
"""
function git_command(git::Git, args::Vector{String}; repo::Union{String,Nothing}="")
    cmd_args = ["git"]
    
    if repo !== nothing
        # Use specified repo or default to cloned dir
        dir = isempty(repo) ? repo_dir(git) : repo
        push!(cmd_args, "-C", dir)
    end
    
    append!(cmd_args, args)
    
    cmd_str = join(cmd_args, " ")
    sanitized_cmd = sanitize(cmd_str, git.token)
    @debug "Running '$sanitized_cmd'"
    
    output = IOBuffer()
    errors = IOBuffer()
    
    try
        proc = @mock run(pipeline(Cmd(cmd_args), stdout=output, stderr=errors))
        return strip(String(take!(output)))
    catch e
        out_str = String(take!(output))
        err_str = String(take!(errors))
        
        !isempty(out_str) && @info sanitize(out_str, git.token)
        !isempty(err_str) && @info sanitize(err_str, git.token)
        
        throw(Abort("Git command '$(sanitized_cmd)' failed"))
    end
end

"""
    git_check(git::Git, args::Vector{String}; repo::Union{String,Nothing}="")

Run a Git command and return whether it succeeded.
"""
function git_check(git::Git, args::Vector{String}; repo::Union{String,Nothing}="")
    try
        git_command(git, args; repo=repo)
        return true
    catch e
        e isa Abort || rethrow(e)
        return false
    end
end

# ============================================================================
# Git Operations
# ============================================================================

"""
    default_branch(git::Git; repo::String="")

Get the name of the default branch.
"""
function default_branch(git::Git; repo::String="")
    if isempty(repo) && git._default_branch !== nothing
        return git._default_branch
    end
    
    remote = git_command(git, ["remote", "show", "origin"]; repo=repo)
    m = match(r"HEAD branch:\s*(.+)", remote)
    
    branch = if m !== nothing
        strip(m.captures[1])
    else
        @warn "Looking up default branch name failed, assuming master"
        "master"
    end
    
    if isempty(repo)
        git._default_branch = branch
    end
    
    return branch
end

"""
    set_remote_url(git::Git, url::String)

Update the origin remote URL.
"""
function set_remote_url(git::Git, url::String)
    git_command(git, ["remote", "set-url", "origin", url])
end

"""
    git_config(git::Git, key::String, val::String; repo::String="")

Configure the repository.
"""
function git_config(git::Git, key::String, val::String; repo::String="")
    git_command(git, ["config", key, val]; repo=repo)
end

"""
    remote_tag_exists(git::Git, version::String)

Check if a tag exists on the remote.
"""
function remote_tag_exists(git::Git, version::String)
    try
        output = git_command(git, ["ls-remote", "--tags", "origin", version])
        return !isempty(strip(output))
    catch e
        e isa Abort || rethrow(e)
        return false
    end
end

"""
    create_tag(git::Git, version::String, sha::String, message::String)

Create and push a Git tag.
"""
function create_tag(git::Git, version::String, sha::String, message::String)
    git_config(git, "user.name", git.user)
    git_config(git, "user.email", git.email)
    
    # Check if tag already exists on remote
    if remote_tag_exists(git, version)
        @info "Tag $version already exists on remote, skipping tag creation"
        return
    end
    
    # Build tag command
    tag_args = ["tag"]
    git.gpgsign && push!(tag_args, "--sign")
    append!(tag_args, ["-m", message, version, sha])
    
    git_command(git, tag_args)
    
    try
        git_command(git, ["push", "origin", version])
    catch e
        @error "Failed to push tag $version. If this is due to workflow " *
               "file changes in the tagged commit, use an SSH deploy key " *
               "(see README) or manually run: " *
               "git tag -a $version $sha -m '$version' && " *
               "git push origin $version"
        rethrow(e)
    end
end

"""
    fetch_branch(git::Git, branch::String)

Try to checkout a remote branch, and return whether or not it succeeded.
"""
function fetch_branch(git::Git, branch::String)
    if !git_check(git, ["checkout", branch])
        return false
    end
    git_command(git, ["checkout", default_branch(git)])
    return true
end

"""
    is_merged(git::Git, branch::String)

Determine if a branch has been merged.
"""
function is_merged(git::Git, branch::String)
    head = git_command(git, ["rev-parse", branch])
    shas = split(git_command(git, ["log", default_branch(git), "--format=%H"]), '\n')
    return head in shas
end

"""
    can_fast_forward(git::Git, branch::String)

Check whether the default branch can be fast-forwarded to branch.
"""
function can_fast_forward(git::Git, branch::String)
    return git_check(git, ["merge-base", "--is-ancestor", default_branch(git), branch])
end

"""
    merge_and_delete_branch(git::Git, branch::String)

Merge a branch into master and delete the branch.
"""
function merge_and_delete_branch(git::Git, branch::String)
    git_command(git, ["checkout", default_branch(git)])
    git_command(git, ["merge", branch])
    git_command(git, ["push", "origin", default_branch(git)])
    git_command(git, ["push", "-d", "origin", branch])
end

"""
    time_of_commit(git::Git, sha::String; repo::String="")

Get the time that a commit was made.
"""
function time_of_commit(git::Git, sha::String; repo::String="")
    # The format %cI is "committer date, strict ISO 8601 format"
    date_str = git_command(git, ["show", "-s", "--format=%cI", sha]; repo=repo)
    dt = DateTime(date_str[1:19], dateformat"yyyy-mm-ddTHH:MM:SS")
    
    # Handle timezone offset if present
    if length(date_str) > 19
        offset_str = date_str[20:end]
        m = match(r"([+-])(\d{2}):(\d{2})", offset_str)
        if m !== nothing
            sign = m.captures[1] == "+" ? 1 : -1
            hours = parse(Int, m.captures[2])
            mins = parse(Int, m.captures[3])
            offset = sign * (hours * 60 + mins)
            dt -= Minute(offset)  # Convert to UTC
        end
    end
    
    return dt
end

"""
    commit_sha_of_tree_git(git::Git, tree::String)

Get the commit SHA of a corresponding tree SHA.
"""
function commit_sha_of_tree_git(git::Git, tree::String)
    # We need --all in case the registered commit isn't on the default branch
    for line in split(git_command(git, ["log", "--all", "--format=%H %T"]), '\n')
        parts = split(line)
        length(parts) == 2 || continue
        commit, tree_sha = parts
        tree_sha == tree && return commit
    end
    return nothing
end

"""
    get_all_tree_commit_pairs(git::Git)

Get all (tree_sha, commit_sha) pairs from git log.
"""
function get_all_tree_commit_pairs(git::Git)
    pairs = Dict{String,String}()
    output = git_command(git, ["log", "--all", "--format=%H %T"])
    for line in split(output, '\n')
        parts = split(line)
        length(parts) == 2 || continue
        commit_sha, tree_sha = parts
        # Only keep first occurrence (most recent commit for that tree)
        haskey(pairs, tree_sha) || (pairs[tree_sha] = commit_sha)
    end
    return pairs
end

"""
    get_all_commit_datetimes(git::Git, shas::Vector{String})

Get datetimes for multiple commits in a single git log command.
"""
function get_all_commit_datetimes(git::Git, shas::Vector{String})
    result = Dict{String,DateTime}()
    sha_set = Set(shas)
    
    output = git_command(git, ["log", "--all", "--format=%H %aI"])
    for line in split(output, '\n')
        parts = split(line, limit=2)
        length(parts) == 2 || continue
        commit_sha, iso_date = parts
        
        if commit_sha in sha_set
            # Parse ISO 8601 date
            dt = DateTime(iso_date[1:19], dateformat"yyyy-mm-ddTHH:MM:SS")
            
            # Handle timezone offset
            if length(iso_date) > 19
                m = match(r"([+-])(\d{2}):(\d{2})", iso_date[20:end])
                if m !== nothing
                    sign = m.captures[1] == "+" ? 1 : -1
                    hours = parse(Int, m.captures[2])
                    mins = parse(Int, m.captures[3])
                    dt -= Minute(sign * (hours * 60 + mins))
                end
            end
            
            result[commit_sha] = dt
            length(result) >= length(shas) && break
        end
    end
    
    return result
end

"""
    subdir_tree_hash(git::Git, commit_sha::String, subdir::String; suppress_abort::Bool=false)

Return subdir tree hash for a commit.
"""
function subdir_tree_hash(git::Git, commit_sha::String, subdir::String; suppress_abort::Bool=false)
    arg = "$commit_sha:$subdir"
    try
        return git_command(git, ["rev-parse", arg])
    catch e
        if suppress_abort && e isa Abort
            @debug "rev-parse failed while inspecting $arg"
            return nothing
        end
        rethrow(e)
    end
end
