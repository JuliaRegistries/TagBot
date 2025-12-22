"""
GitLab support for TagBot (stub implementation).

This module provides GitLab API compatibility when using GitLab instead of GitHub.
"""

# ============================================================================
# GitLab Types
# ============================================================================

"""
    GitLabException <: Exception

Exception for GitLab API errors.
"""
struct GitLabException <: Exception
    message::String
    status::Int
end

Base.showerror(io::IO, e::GitLabException) = print(io, "GitLabException($(e.status)): ", e.message)

# ============================================================================
# GitLab API Client
# ============================================================================

"""
    is_gitlab(url::String)

Check if a URL points to a GitLab instance.
"""
function is_gitlab(url::String)
    host = try
        m = match(r"https?://([^/]+)", url)
        m !== nothing ? m.captures[1] : url
    catch
        url
    end
    return occursin("gitlab", lowercase(host))
end

"""
    gitlab_api_call(base_url::String, token::String, method::String, endpoint::String; kwargs...)

Make a GitLab API call.
"""
function gitlab_api_call(base_url::String, token::String, method::String, endpoint::String;
                         body=nothing, query=nothing)
    url = "$base_url/api/v4/$endpoint"

    headers = [
        "PRIVATE-TOKEN" => token,
        "Content-Type" => "application/json",
    ]

    if query !== nothing
        url *= "?" * HTTP.URIs.escapeuri(query)
    end

    try
        if method == "GET"
            resp = HTTP.get(url, headers; status_exception=false)
        elseif method == "POST"
            resp = HTTP.post(url, headers, JSON3.write(body); status_exception=false)
        else
            error("Unsupported method: $method")
        end

        if resp.status >= 400
            if resp.status == 404
                return nothing
            end
            error_body = String(resp.body)
            throw(GitLabException(error_body, resp.status))
        end

        isempty(resp.body) && return nothing
        return JSON3.read(String(resp.body))
    catch e
        e isa GitLabException && rethrow(e)
        @error "GitLab API request failed: $e"
        rethrow(e)
    end
end

# ============================================================================
# GitLab Repo Wrapper
# ============================================================================

"""
    GitLabRepo

Wrapper for GitLab project to provide similar interface to GitHub Repo.
"""
mutable struct GitLabRepo
    base_url::String
    token::String
    project_id::String
    _project::Union{Any,Nothing}
end

function GitLabRepo(base_url::String, token::String, repo::String)
    # URL-encode the project path
    project_id = HTTP.URIs.escapeuri(repo)
    GitLabRepo(base_url, token, project_id, nothing)
end

"""
    get_gitlab_file_content(repo::GitLabRepo, path::String)

Get file content from GitLab repository.
"""
function get_gitlab_file_content(repo::GitLabRepo, path::String)
    encoded_path = HTTP.URIs.escapeuri(path)
    endpoint = "projects/$(repo.project_id)/repository/files/$encoded_path"

    resp = gitlab_api_call(repo.base_url, repo.token, "GET", endpoint;
                          query=Dict("ref" => "HEAD"))

    resp === nothing && throw(InvalidProject("File not found: $path"))

    content_b64 = resp[:content]
    return String(Base64.base64decode(content_b64))
end

"""
    get_gitlab_releases(repo::GitLabRepo)

Get releases from GitLab project.
"""
function get_gitlab_releases(repo::GitLabRepo)
    endpoint = "projects/$(repo.project_id)/releases"

    releases = GitHubRelease[]  # Reuse the struct

    resp = gitlab_api_call(repo.base_url, repo.token, "GET", endpoint)
    resp === nothing && return releases

    for rel in resp
        created_at = if rel[:created_at] !== nothing
            DateTime(rel[:created_at][1:19], dateformat"yyyy-mm-ddTHH:MM:SS")
        else
            DateTime(1970, 1, 1)
        end

        push!(releases, GitHubRelease(
            rel[:tag_name],
            created_at,
            get(rel, :_links, Dict())[:self]
        ))
    end

    return releases
end

"""
    create_gitlab_release(repo::GitLabRepo, tag::String, name::String, body::String;
                         target_commitish::Union{String,Nothing}=nothing)

Create a GitLab release.
"""
function create_gitlab_release(repo::GitLabRepo, tag::String, name::String, body::String;
                              target_commitish::Union{String,Nothing}=nothing)
    endpoint = "projects/$(repo.project_id)/releases"

    data = Dict(
        "name" => name,
        "tag_name" => tag,
        "description" => body,
    )

    if target_commitish !== nothing
        data["ref"] = target_commitish
    end

    gitlab_api_call(repo.base_url, repo.token, "POST", endpoint; body=data)
end

# Note: Full GitLab support would require implementing all the methods
# from repo.jl with GitLab API equivalents. This is a minimal stub.
