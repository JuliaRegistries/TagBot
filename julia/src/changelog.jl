"""
Changelog generation for TagBot.
"""

# ============================================================================
# Changelog Type
# ============================================================================

"""
    Changelog

A Changelog produces release notes for a single release.
"""
mutable struct Changelog
    repo  # Forward reference to Repo
    template::String
    ignore::Set{String}
    _range::Union{Tuple{DateTime,DateTime},Nothing}
    _issues_and_pulls::Union{Vector{Any},Nothing}
end

function Changelog(repo, template::String, ignore::Vector{String})
    # Normalize ignore labels for comparison
    ignore_set = Set(slug(s) for s in ignore)
    Changelog(repo, template, ignore_set, nothing, nothing)
end

"""
    slug(s::String)

Return a version of the string that's easy to compare.
"""
function slug(s::AbstractString)
    lowercase(replace(s, r"[\s_-]" => ""))
end

# ============================================================================
# Release Discovery
# ============================================================================

"""
    previous_release(cl::Changelog, version_tag::String)

Get the release previous to the current one (according to SemVer).
"""
function previous_release(cl::Changelog, version_tag::String)
    tag_prefix = get_tag_prefix(cl.repo)
    i_start = length(tag_prefix) + 1

    cur_ver = try
        SemVer(version_tag[i_start:end])
    catch
        return nothing
    end

    prev_ver = SemVer(0, 0, 0, nothing, nothing)
    prev_rel = nothing

    for rel in get_releases(cl.repo)
        !startswith(rel.tag_name, tag_prefix) && continue

        ver = try
            SemVer(rel.tag_name[i_start:end])
        catch
            continue
        end

        # Skip prereleases and builds
        (ver.prerelease !== nothing || ver.build !== nothing) && continue

        # Get the highest version that is not greater than the current one
        if ver < cur_ver && ver > prev_ver
            prev_rel = rel
            prev_ver = ver
        end
    end

    return prev_rel
end

"""
    is_backport(cl::Changelog, version::String; tags=nothing)

Determine whether or not the version is a backport.
"""
function is_backport(cl::Changelog, version::String; tags=nothing)
    try
        version_pattern = r"^(.*?)[-v]?(\d+\.\d+\.\d+(?:\.\d+)*)(?:[-+].+)?$"

        if tags === nothing
            tags = [rel.tag_name for rel in get_releases(cl.repo)]
        end

        # Extract package name prefix and version
        m = match(version_pattern, version)
        m === nothing && throw(ArgumentError("Invalid version format: $version"))

        package_name = m.captures[1]
        cur_ver = SemVer(m.captures[2])

        for tag in tags
            tag_match = match(version_pattern, tag)
            tag_match === nothing && continue

            tag_package_name = tag_match.captures[1]
            tag_package_name != package_name && continue

            tag_ver = try
                SemVer(tag_match.captures[2])
            catch
                continue
            end

            # Skip prereleases and builds
            (tag_ver.prerelease !== nothing || tag_ver.build !== nothing) && continue

            # Check if version is a backport
            tag_ver > cur_ver && return true
        end

        return false
    catch e
        @error "Checking if backport failed. Assuming false: $e"
        return false
    end
end

# ============================================================================
# Issues and PRs
# ============================================================================

"""
    issues_and_pulls(cl::Changelog, start_time::DateTime, end_time::DateTime)

Collect issues and pull requests that were closed in the interval.
"""
function issues_and_pulls(cl::Changelog, start_time::DateTime, end_time::DateTime)
    # Return cached results if interval is the same
    if cl._issues_and_pulls !== nothing && cl._range == (start_time, end_time)
        return cl._issues_and_pulls
    end

    results = Any[]

    # Use search API for efficiency
    repo_name = get_full_name(cl.repo)
    start_str = Dates.format(start_time, dateformat"yyyy-mm-ddTHH:MM:SS")
    end_str = Dates.format(end_time, dateformat"yyyy-mm-ddTHH:MM:SS")
    query = "repo:$repo_name is:closed closed:$start_str..$end_str"

    @debug "Searching issues/PRs with query: $query"

    try
        for item in search_issues(cl.repo, query)
            # Verify closed_at is within range
            item.closed_at === nothing && continue
            item.closed_at <= start_time && continue
            item.closed_at > end_time && continue

            # Check for ignored labels
            any(slug(l) in cl.ignore for l in item.labels) && continue

            push!(results, item)
        end
    catch e
        @warn "Search API failed, falling back to issues API: $e"
        return issues_and_pulls_fallback(cl, start_time, end_time)
    end

    cl._range = (start_time, end_time)
    cl._issues_and_pulls = results
    return results
end

"""
    issues_and_pulls_fallback(cl::Changelog, start_time::DateTime, end_time::DateTime)

Fallback method using the issues API (slower but more reliable).
"""
function issues_and_pulls_fallback(cl::Changelog, start_time::DateTime, end_time::DateTime)
    results = Any[]

    for item in get_issues(cl.repo; state="closed", since=start_time)
        item.closed_at === nothing && continue
        item.closed_at <= start_time && continue
        item.closed_at > end_time && continue

        any(slug(l) in cl.ignore for l in item.labels) && continue

        push!(results, item)
    end

    reverse!(results)  # Sort in chronological order

    cl._range = (start_time, end_time)
    cl._issues_and_pulls = results
    return results
end

"""
    get_issues_only(cl::Changelog, start_time::DateTime, end_time::DateTime)

Collect just issues in the interval.
"""
function get_issues_only(cl::Changelog, start_time::DateTime, end_time::DateTime)
    filter(x -> !x.is_pull_request, issues_and_pulls(cl, start_time, end_time))
end

"""
    get_pulls_only(cl::Changelog, start_time::DateTime, end_time::DateTime)

Collect just pull requests in the interval.
"""
function get_pulls_only(cl::Changelog, start_time::DateTime, end_time::DateTime)
    filter(x -> x.is_pull_request && x.merged, issues_and_pulls(cl, start_time, end_time))
end

# ============================================================================
# Custom Release Notes
# ============================================================================

"""
    custom_release_notes(cl::Changelog, version_tag::String)

Look up a version's custom release notes.
"""
function custom_release_notes(cl::Changelog, version_tag::String)
    @debug "Looking up custom release notes"

    tag_prefix = get_tag_prefix(cl.repo)
    i_start = length(tag_prefix)
    package_version = version_tag[i_start:end]

    pr = registry_pr(cl.repo, package_version)
    if pr === nothing
        @warn "No registry pull request was found for this version"
        return nothing
    end

    # Try new format first
    m = match(r"(?s)<!-- BEGIN RELEASE NOTES -->\n`````(.*)`````\n<!-- END RELEASE NOTES -->"s, pr.body)
    if m !== nothing
        return strip(m.captures[1])
    end

    # Try old format
    m = match(r"(?s)<!-- BEGIN RELEASE NOTES -->(.*)<!-- END RELEASE NOTES -->"s, pr.body)
    if m !== nothing
        # Remove '> ' at the beginning of each line
        lines = split(m.captures[1], '\n')
        return strip(join((startswith(l, "> ") ? l[3:end] : l for l in lines), '\n'))
    end

    @debug "No custom release notes were found"
    return nothing
end

# ============================================================================
# Changelog Generation
# ============================================================================

"""
    collect_changelog_data(cl::Changelog, version_tag::String, sha::String)

Collect data needed to create the changelog.
"""
function collect_changelog_data(cl::Changelog, version_tag::String, sha::String)
    prev = previous_release(cl, version_tag)

    start_time = DateTime(1970, 1, 1)
    prev_tag = nothing
    compare_url = nothing

    if prev !== nothing
        start_time = prev.created_at
        prev_tag = prev.tag_name
        html_url = get_html_url(cl.repo)
        compare_url = "$html_url/compare/$prev_tag...$version_tag"
    end

    # Get end time from commit
    commit = get_commit(cl.repo, sha)
    end_time = commit.author_date + Minute(1)

    @debug "Previous version: $prev_tag"
    @debug "Start date: $start_time"
    @debug "End date: $end_time"

    issues = get_issues_only(cl, start_time, end_time)
    pulls = get_pulls_only(cl, start_time, end_time)

    return Dict{String,Any}(
        "compare_url" => compare_url,
        "custom" => custom_release_notes(cl, version_tag),
        "backport" => is_backport(cl, version_tag),
        "issues" => [format_issue(i) for i in issues],
        "package" => get_project_value(cl.repo, "name"),
        "previous_release" => prev_tag,
        "pulls" => [format_pull(p) for p in pulls],
        "sha" => sha,
        "version" => version_tag,
        "version_url" => "$(get_html_url(cl.repo))/tree/$version_tag",
    )
end

"""
    format_issue(issue)

Format an issue for the template.
"""
function format_issue(issue)
    Dict{String,Any}(
        "author_username" => issue.user_login,
        "body" => issue.body,
        "labels" => issue.labels,
        "number" => issue.number,
        "title" => issue.title,
        "url" => issue.html_url,
    )
end

"""
    format_pull(pull)

Format a pull request for the template.
"""
function format_pull(pull)
    Dict{String,Any}(
        "author_username" => pull.user_login,
        "body" => pull.body,
        "labels" => pull.labels,
        "number" => pull.number,
        "title" => pull.title,
        "url" => pull.html_url,
    )
end

"""
    render_changelog(cl::Changelog, data::Dict)

Render the template.
"""
function render_changelog(cl::Changelog, data::Dict)
    strip(Mustache.render(cl.template, data))
end

"""
    get_changelog(cl::Changelog, version_tag::String, sha::String)

Get the changelog for a specific version.
"""
function get_changelog(cl::Changelog, version_tag::String, sha::String)
    @info "Generating changelog for version $version_tag ($sha)"
    data = collect_changelog_data(cl, version_tag, sha)
    @debug "Changelog data: $(JSON3.write(data))"
    return render_changelog(cl, data)
end
