"""
Changelog support for TagBot.

Note: TagBot uses GitHub's auto-generated release notes for changelog content.
This module only handles custom release notes from registry PRs.
"""

# ============================================================================
# Changelog Type
# ============================================================================

"""
    Changelog

Handles custom release notes from registry PRs.
GitHub's auto-generated release notes are used for the main changelog.
"""
mutable struct Changelog
    repo  # Forward reference to Repo
end

function Changelog(repo, template::String, ignore::Vector{String})
    # Template and ignore are no longer used - GitHub generates release notes
    # Keep signature for backwards compatibility
    Changelog(repo)
end

"""
    slug(s::String)

Return a version of the string that's easy to compare.
"""
function slug(s::AbstractString)
    lowercase(replace(s, r"[\s_-]" => ""))
end

# ============================================================================
# Custom Release Notes
# ============================================================================

"""
    custom_release_notes(cl::Changelog, version_tag::String)

Look up a version's custom release notes from the registry PR.
These notes are prepended to GitHub's auto-generated release notes.
"""
function custom_release_notes(cl::Changelog, version_tag::String)
    @debug "Looking up custom release notes"

    tag_prefix = get_tag_prefix(cl.repo)
    i_start = length(tag_prefix) + 1
    package_version = version_tag[i_start:end]

    pr = registry_pr(cl.repo, package_version)
    if pr === nothing
        @debug "No registry pull request was found for this version"
        return nothing
    end

    # Try new format first (fenced code block)
    m = match(r"(?s)<!-- BEGIN RELEASE NOTES -->\n`````(.*)`````\n<!-- END RELEASE NOTES -->"s, pr.body)
    if m !== nothing
        return strip(m.captures[1])
    end

    # Try old format (blockquote)
    m = match(r"(?s)<!-- BEGIN RELEASE NOTES -->(.*)<!-- END RELEASE NOTES -->"s, pr.body)
    if m !== nothing
        # Remove '> ' at the beginning of each line
        lines = split(m.captures[1], '\n')
        return strip(join((startswith(l, "> ") ? l[3:end] : l for l in lines), '\n'))
    end

    @debug "No custom release notes were found"
    return nothing
end
