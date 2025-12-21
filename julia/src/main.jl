"""
Main entry point for TagBot.
"""

# ============================================================================
# Input Parsing
# ============================================================================

# Global inputs cache
const INPUTS = Ref{Union{Dict{String,Any},Nothing}}(nothing)

const CRON_WARNING = """
Your TagBot workflow should be updated to use issue comment triggers instead of cron.
See this Discourse thread for more information: https://discourse.julialang.org/t/ann-required-updates-to-tagbot-yml/49249
"""

"""
    get_input(key::String; default::String="")

Get an input from the environment, or from a workflow input if it's set.
"""
function get_input(key::String; default::String="")
    env_key = "INPUT_" * uppercase(replace(key, "-" => "_"))
    default_val = get(ENV, env_key, default)
    
    if INPUTS[] === nothing
        event_path = get(ENV, "GITHUB_EVENT_PATH", nothing)
        event_path === nothing && return default_val
        
        !isfile(event_path) && return default_val
        
        event = try
            JSON3.read(read(event_path, String))
        catch
            INPUTS[] = Dict{String,Any}()
            return default_val
        end
        
        INPUTS[] = get(event, :inputs, Dict{String,Any}())
    end
    
    inputs = INPUTS[]
    lkey = lowercase(key)
    
    if haskey(inputs, Symbol(lkey))
        val = inputs[Symbol(lkey)]
        return val === nothing || isempty(val) ? default_val : string(val)
    end
    
    return default_val
end

"""
    parse_bool(s::String)

Parse a string as a boolean.
"""
function parse_bool(s::String)
    lowercase(s) in ["true", "yes", "1"]
end

# ============================================================================
# SSH/GPG Configuration
# ============================================================================

"""
    maybe_decode_private_key(key::String)

Return a decoded value if it is Base64-encoded, or the original value.
"""
function maybe_decode_private_key(key::String)
    key = strip(key)
    occursin("PRIVATE KEY", key) && return key
    
    try
        return String(Base64.base64decode(key))
    catch e
        throw(ArgumentError(
            "SSH key does not appear to be a valid private key. " *
            "Expected either a PEM-formatted key (starting with " *
            "'-----BEGIN ... PRIVATE KEY-----') or a valid Base64-encoded key. " *
            "Decoding error: $e"
        ))
    end
end

"""
    validate_ssh_key(key::String)

Warn if the SSH key appears to be invalid.
"""
function validate_ssh_key(key::String)
    key = strip(key)
    isempty(key) && (@warn "SSH key is empty"; return)
    
    valid_markers = [
        "-----BEGIN OPENSSH PRIVATE KEY-----",
        "-----BEGIN RSA PRIVATE KEY-----",
        "-----BEGIN DSA PRIVATE KEY-----",
        "-----BEGIN EC PRIVATE KEY-----",
        "-----BEGIN PRIVATE KEY-----",
    ]
    
    if !any(m -> occursin(m, key), valid_markers)
        @warn "SSH key does not appear to be a valid private key. " *
              "Expected a key starting with '-----BEGIN ... PRIVATE KEY-----'. " *
              "Make sure you're using the private key, not the public key."
    end
end

"""
    configure_ssh(repo::Repo, key::String, password::Union{String,Nothing}; registry_repo::String="")

Configure the repo to use an SSH key for authentication.
"""
function configure_ssh(repo::Repo, key::String, password::Union{String,Nothing}; 
                      registry_repo::String="")
    decoded_key = maybe_decode_private_key(key)
    validate_ssh_key(decoded_key)
    
    if isempty(registry_repo)
        # Get SSH URL for the repo using GitHub.jl
        gh_repo_obj = get_gh_repo(repo)
        ssh_url = gh_repo_obj.ssh_url
        set_remote_url(repo.git, ssh_url)
    end
    
    # Write key to temp file
    priv = tempname() * "_tagbot_key"
    write(priv, rstrip(decoded_key) * "\n")
    chmod(priv, 0o400)
    
    # Generate known_hosts
    gh_url = startswith(repo.config.github, "http") ? repo.config.github : "https://$(repo.config.github)"
    m = match(r"https?://([^/]+)", gh_url)
    host = m !== nothing ? m.captures[1] : repo.config.github
    
    hosts = tempname() * "_tagbot_hosts"
    run(pipeline(`ssh-keyscan -t rsa $host`, stdout=hosts, stderr=devnull))
    
    # Configure git to use SSH
    cmd = "ssh -i $priv -o UserKnownHostsFile=$hosts"
    @debug "SSH command: $cmd"
    
    target_repo = isempty(registry_repo) ? "" : registry_repo
    git_config(repo.git, "core.sshCommand", cmd; repo=target_repo)
    
    # Handle password-protected keys
    if password !== nothing && !isempty(password)
        # Start ssh-agent and add key
        agent_output = read(`ssh-agent`, String)
        
        for m in eachmatch(r"\s*(.+)=(.+?);", agent_output)
            k, v = m.captures
            ENV[k] = v
            @debug "Setting environment variable $k=$v"
        end
        
        # Use ssh-add with expect-like handling (simplified)
        # In practice, this requires pexpect or similar
        @warn "Password-protected SSH keys require interactive authentication"
    end
    
    @info "SSH key configured"
end

"""
    configure_gpg(repo::Repo, key::String, password::Union{String,Nothing})

Configure the repo to sign tags with GPG.
"""
function configure_gpg(repo::Repo, key::String, password::Union{String,Nothing})
    # Create temp GNUPGHOME
    home = mktempdir(prefix="tagbot_gpg_")
    chmod(home, 0o700)
    ENV["GNUPGHOME"] = home
    @debug "Set GNUPGHOME to $home"
    
    decoded_key = maybe_decode_private_key(key)
    
    # Import key using gpg command
    key_file = tempname()
    write(key_file, decoded_key)
    
    try
        import_output = read(`gpg --batch --import $key_file`, String)
        
        # Extract key ID
        m = match(r"key ([A-F0-9]+):", import_output)
        if m === nothing
            # Try alternative pattern
            list_output = read(`gpg --list-secret-keys --keyid-format LONG`, String)
            m = match(r"sec\s+\w+/([A-F0-9]+)", list_output)
        end
        
        m === nothing && throw(Abort("Could not determine GPG key ID"))
        key_id = m.captures[1]
        @debug "GPG key ID: $key_id"
        
        # Configure git
        repo.git.gpgsign = true
        git_config(repo.git, "tag.gpgSign", "true")
        git_config(repo.git, "user.signingKey", key_id)
        
        @info "GPG key configured"
    finally
        rm(key_file, force=true)
    end
end

# ============================================================================
# Version Selection
# ============================================================================

"""
    version_with_latest_commit(repo::Repo, versions::Dict{String,String})

Find the version with the most recent commit datetime.
"""
function version_with_latest_commit(repo::Repo, versions::Dict{String,String})
    isempty(versions) && return nothing
    
    # Check if any existing tag has a higher version
    tags_cache = build_tags_cache!(repo)
    prefix = get_tag_prefix(repo)
    
    highest_existing = nothing
    for tag_name in keys(tags_cache)
        !startswith(tag_name, prefix) && continue
        version_str = tag_name[length(prefix)+1:end]
        ver = try
            SemVer(version_str)
        catch
            continue
        end
        (ver.prerelease !== nothing || ver.build !== nothing) && continue
        
        if highest_existing === nothing || ver > highest_existing
            highest_existing = ver
        end
    end
    
    if highest_existing !== nothing
        # Find highest new version
        highest_new = nothing
        for version in keys(versions)
            v_str = startswith(version, "v") ? version[2:end] : version
            ver = try
                SemVer(v_str)
            catch
                continue
            end
            if highest_new === nothing || ver > highest_new
                highest_new = ver
            end
        end
        
        if highest_new !== nothing && highest_existing > highest_new
            @info "Existing tag v$highest_existing is newer than all new versions; " *
                  "no new release will be marked as latest"
            return nothing
        end
    end
    
    # Get commit datetimes
    shas = collect(values(versions))
    datetimes = get_all_commit_datetimes(repo.git, shas)
    
    # Also update repo's cache
    merge!(repo._commit_datetimes, datetimes)
    
    # Find latest
    latest_version = nothing
    latest_datetime = nothing
    
    for (version, sha) in versions
        dt = get(datetimes, sha, nothing)
        dt === nothing && continue
        
        if latest_datetime === nothing || dt > latest_datetime
            latest_datetime = dt
            latest_version = version
        end
    end
    
    return latest_version
end

# ============================================================================
# Error Handling  
# ============================================================================

"""
    report_error(repo::Repo, trace::String)

Report an error to the TagBot web service.
"""
function report_error(repo::Repo, trace::String)
    # Check if repo is private using GitHub.jl
    is_private = try
        gh_repo_obj = get_gh_repo(repo)
        gh_repo_obj.private
    catch
        @debug "Could not determine repository privacy; skipping error reporting"
        return
    end
    
    if is_private || get(ENV, "GITHUB_ACTIONS", "") != "true"
        @debug "Not reporting"
        return
    end
    
    @debug "Reporting error"
    
    # Get run URL
    run_url = "$(get_html_url(repo))/actions"
    run_id = get(ENV, "GITHUB_RUN_ID", nothing)
    run_id !== nothing && (run_url *= "/runs/$run_id")
    
    data = Dict(
        "image" => get(ENV, "HOSTNAME", "Unknown"),
        "repo" => repo.config.repo,
        "run" => run_url,
        "stacktrace" => trace,
        "version" => string(VERSION),
    )
    
    if repo._manual_intervention_issue_url !== nothing
        data["manual_intervention_url"] = repo._manual_intervention_issue_url
    end
    
    try
        resp = @mock HTTP.post("$TAGBOT_WEB/report", 
            ["Content-Type" => "application/json"],
            JSON3.write(data);
            status_exception=false
        )
        @info "Response ($(resp.status)): $(String(resp.body))"
    catch e
        @error "Error reporting failed: $e"
    end
end

"""
    handle_error(repo::Repo, e::Exception; raise_abort::Bool=true)

Handle an unexpected error.
"""
function handle_error(repo::Repo, e::Exception; raise_abort::Bool=true)
    trace = sanitize(sprint(showerror, e, catch_backtrace()), repo.config.token)
    
    allowed = false
    internal = true
    
    if e isa Abort
        internal = false
        allowed = false
    elseif e isa HTTP.ExceptionRequest.StatusError
        status = e.status
        if 500 <= status < 600
            @warn "GitHub returned a 5xx error code"
            @info trace
            allowed = true
        elseif status == 403
            check_rate_limit(repo)
            @error "GitHub returned a 403 error. This may indicate rate limiting or insufficient permissions."
            internal = false
            allowed = false
        end
    end
    
    if !allowed
        internal && @error "TagBot experienced an unexpected internal failure"
        @info trace
        try
            report_error(repo, trace)
        catch
            @error "Issue reporting failed"
        end
        raise_abort && throw(Abort("Cannot continue due to internal failure"))
    end
end

# ============================================================================
# Main Entry Point
# ============================================================================

"""
    main()

Main entry point for TagBot action.
"""
function main()
    setup_logging()
    reset!(METRICS)
    
    try
        _main()
    catch e
        if e isa Abort
            @error e.message
        else
            rethrow(e)
        end
    finally
        log_summary(METRICS)
    end
end

function _main()
    # Check for cron trigger
    if get(ENV, "GITHUB_EVENT_NAME", "") == "schedule"
        @warn CRON_WARNING
    end
    
    # Get required token
    token = get_input("token")
    if isempty(token)
        @error "No GitHub API token supplied"
        exit(1)
    end
    
    # Parse SSH/GPG inputs
    ssh = get_input("ssh")
    gpg = get_input("gpg")
    
    # Parse changelog ignore
    changelog_ignore_str = get_input("changelog_ignore")
    changelog_ignore = if !isempty(changelog_ignore_str)
        String.(split(changelog_ignore_str, ","))
    else
        copy(DEFAULT_CHANGELOG_IGNORE)
    end
    
    # Create repo config
    config = RepoConfig(
        repo = get(ENV, "GITHUB_REPOSITORY", ""),
        registry = get_input("registry"; default="JuliaRegistries/General"),
        github = get_input("github"; default="github.com"),
        github_api = get_input("github_api"; default="api.github.com"),
        token = token,
        changelog_template = get_input("changelog"; default=DEFAULT_CHANGELOG_TEMPLATE),
        changelog_ignore = changelog_ignore,
        ssh = !isempty(ssh),
        gpg = !isempty(gpg),
        draft = parse_bool(get_input("draft"; default="false")),
        registry_ssh = get_input("registry_ssh"),
        user = get_input("user"; default="github-actions[bot]"),
        email = get_input("email"; default="41898282+github-actions[bot]@users.noreply.github.com"),
        branch = let b = get_input("branch"); isempty(b) ? nothing : b end,
        subdir = let s = get_input("subdir"); isempty(s) ? nothing : s end,
        tag_prefix = let t = get_input("tag_prefix"); isempty(t) ? nothing : t end,
    )
    
    repo = Repo(config)
    
    # Check if package is registered
    if !is_registered(repo)
        @info "This package is not registered, skipping"
        @info "If this repository is not going to be registered, then remove TagBot"
        return
    end
    
    # Get new versions
    versions = new_versions(repo)
    if isempty(versions)
        @info "No new versions to release"
        return
    end
    
    # Handle dispatch event
    if parse_bool(get_input("dispatch"; default="false"))
        minutes = parse(Int, get_input("dispatch_delay"; default="5"))
        # create_dispatch_event(repo, versions)  # TODO: Implement
        @info "Waiting $minutes minutes for any dispatch handlers"
        sleep(minutes * 60)
    end
    
    # Configure SSH/GPG
    !isempty(ssh) && configure_ssh(repo, ssh, get_input("ssh_password"))
    !isempty(gpg) && configure_gpg(repo, gpg, get_input("gpg_password"))
    
    # Determine latest version
    latest_version = version_with_latest_commit(repo, versions)
    if latest_version !== nothing
        @info "Version $latest_version has the most recent commit, will be marked as latest"
    end
    
    # Process versions
    errors = Tuple{String,String,String}[]
    successes = String[]
    
    for (version, sha) in versions
        try
            @info "Processing version $version ($sha)"
            
            if parse_bool(get_input("branches"; default="false"))
                # handle_release_branch(repo, version)  # TODO: Implement
            end
            
            is_latest = version == latest_version
            !is_latest && @info "Version $version will not be marked as latest release"
            
            create_release(repo, version, sha; is_latest=is_latest)
            push!(successes, version)
            @info "Successfully released $version"
        catch e
            @error "Failed to process version $version: $e"
            push!(errors, (version, sha, string(e)))
            handle_error(repo, e; raise_abort=false)
        end
    end
    
    if !isempty(successes)
        @info "Successfully released versions: $(join(successes, ", "))"
    end
    
    if !isempty(errors)
        failed = join([v for (v, _, _) in errors], ", ")
        @error "Failed to release versions: $failed"
        # TODO: Create issue for manual intervention
        exit(1)
    end
end
