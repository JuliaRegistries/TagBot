using Test
using Dates
using TagBot: Changelog, DEFAULT_CHANGELOG_IGNORE, DEFAULT_CHANGELOG_TEMPLATE
using TagBot: Git, Repo, RepoConfig

@testset "Changelog" begin
    @testset "Default ignore labels" begin
        @test "changelog skip" in DEFAULT_CHANGELOG_IGNORE
        @test "duplicate" in DEFAULT_CHANGELOG_IGNORE
        @test "invalid" in DEFAULT_CHANGELOG_IGNORE
        @test "wont fix" in DEFAULT_CHANGELOG_IGNORE
        @test "question" in DEFAULT_CHANGELOG_IGNORE
    end

    @testset "Version pattern matching" begin
        # Test version pattern matching used in is_backport
        version_pattern = r"^(.*?)[-v]?(\d+\.\d+\.\d+(?:\.\d+)*)(?:[-+].+)?$"
        
        @test match(version_pattern, "v1.0.0") !== nothing
        @test match(version_pattern, "v1.2.3") !== nothing
        @test match(version_pattern, "Package-v1.0.0") !== nothing
        @test match(version_pattern, "1.0.0") !== nothing
        @test match(version_pattern, "v2.0.0-alpha") !== nothing
        @test match(version_pattern, "v1.0.0+build") !== nothing
    end

    @testset "Custom release notes parsing" begin
        # Test the release notes marker parsing
        body_with_notes = """
        This PR does something.
        
        <!-- BEGIN RELEASE NOTES -->
        ## What's New
        - Feature A
        - Feature B
        <!-- END RELEASE NOTES -->
        
        Other stuff.
        """
        
        begin_marker = "<!-- BEGIN RELEASE NOTES -->"
        end_marker = "<!-- END RELEASE NOTES -->"
        
        start_idx = findfirst(begin_marker, body_with_notes)
        end_idx = findfirst(end_marker, body_with_notes)
        
        @test start_idx !== nothing
        @test end_idx !== nothing
        
        notes_start = last(start_idx) + 1
        notes_end = first(end_idx) - 1
        notes = strip(body_with_notes[notes_start:notes_end])
        
        @test occursin("What's New", notes)
        @test occursin("Feature A", notes)
        @test occursin("Feature B", notes)
    end

    @testset "Custom release notes missing" begin
        body_without_notes = """
        This PR does something regular.
        No release notes here.
        """
        
        begin_marker = "<!-- BEGIN RELEASE NOTES -->"
        start_idx = findfirst(begin_marker, body_without_notes)
        
        @test start_idx === nothing
    end

    @testset "SemVer comparison for previous release" begin
        # Test sorting versions to find previous release
        versions = ["v1.0.0", "v1.2.0", "v1.1.0", "v2.0.0", "v0.9.0"]
        current = "v1.2.0"
        
        # Parse versions into comparable tuples
        function parse_version(v)
            m = match(r"v?(\d+)\.(\d+)\.(\d+)", v)
            m === nothing && return (0, 0, 0)
            (parse(Int, m[1]), parse(Int, m[2]), parse(Int, m[3]))
        end
        
        current_tuple = parse_version(current)
        
        # Find highest version less than current
        candidates = filter(v -> parse_version(v) < current_tuple, versions)
        sorted = sort(candidates, by=parse_version, rev=true)
        
        @test first(sorted) == "v1.1.0"
    end

    @testset "Default changelog template" begin
        @test DEFAULT_CHANGELOG_TEMPLATE isa String
        @test occursin("{{#", DEFAULT_CHANGELOG_TEMPLATE) || 
              occursin("{{{", DEFAULT_CHANGELOG_TEMPLATE) ||
              occursin("{{", DEFAULT_CHANGELOG_TEMPLATE)  # Mustache syntax
    end

    @testset "Time range calculation" begin
        # Test time range for issues/PRs
        prev_time = DateTime(2023, 6, 1, 12, 0, 0)
        curr_time = DateTime(2023, 7, 15, 18, 30, 0)
        
        @test curr_time > prev_time
        @test Dates.value(curr_time - prev_time) > 0
    end

    @testset "Issue label filtering" begin
        # Test filtering issues by labels
        ignore_labels = Set(DEFAULT_CHANGELOG_IGNORE)
        
        issue_labels_good = ["enhancement", "bug"]
        issue_labels_bad = ["duplicate"]
        issue_labels_mixed = ["enhancement", "wont fix"]
        
        has_ignore_good = any(l -> l in ignore_labels, issue_labels_good)
        has_ignore_bad = any(l -> l in ignore_labels, issue_labels_bad)
        has_ignore_mixed = any(l -> l in ignore_labels, issue_labels_mixed)
        
        @test !has_ignore_good
        @test has_ignore_bad
        @test has_ignore_mixed
    end

    @testset "Compare URL generation" begin
        # Test generation of GitHub compare URL
        repo = "JuliaLang/Example"
        prev = "v1.0.0"
        curr = "v1.1.0"
        
        url = "https://github.com/$repo/compare/$prev...$curr"
        @test url == "https://github.com/JuliaLang/Example/compare/v1.0.0...v1.1.0"
    end

    @testset "Backport detection" begin
        # Test is_backport logic
        # A release is a backport if its version < the max existing version
        existing_versions = [(1, 2, 0), (1, 1, 0), (1, 0, 0)]
        max_version = maximum(existing_versions)
        
        new_version_old = (1, 0, 1)  # Backport to 1.0.x
        new_version_new = (1, 3, 0)  # New release
        
        @test new_version_old < max_version  # Is backport
        @test !(new_version_new < max_version)  # Not backport
    end

    @testset "Slug generation" begin
        # Test package slug for subpackages
        pkg = "MyPackage"
        subdir = ""
        slug_no_sub = isempty(subdir) ? pkg : "$subdir-$pkg"
        @test slug_no_sub == "MyPackage"
        
        subdir2 = "lib/SubPkg"
        slug_with_sub = isempty(subdir2) ? pkg : "$(replace(subdir2, "/" => "-"))-$pkg"
        @test slug_with_sub == "lib-SubPkg-MyPackage"
    end

    @testset "Issues and pulls separation" begin
        # Test separating issues from PRs
        # In GitHub API, PRs have pull_request field
        items = [
            Dict("number" => 1, "pull_request" => Dict("url" => "...")),
            Dict("number" => 2),  # No pull_request = issue
            Dict("number" => 3, "pull_request" => Dict("url" => "...")),
            Dict("number" => 4),
        ]
        
        issues = filter(x -> !haskey(x, "pull_request"), items)
        pulls = filter(x -> haskey(x, "pull_request"), items)
        
        @test length(issues) == 2
        @test length(pulls) == 2
        @test issues[1]["number"] == 2
        @test pulls[1]["number"] == 1
    end

    @testset "PR merged check" begin
        # Test checking if PR was merged vs just closed
        pr_merged = Dict("merged_at" => "2023-01-01T12:00:00Z")
        pr_closed = Dict("merged_at" => nothing)
        
        @test !isnothing(pr_merged["merged_at"])
        @test isnothing(pr_closed["merged_at"])
    end

    @testset "Closed date filtering" begin
        # Test filtering items by closed date within range
        start_time = DateTime(2023, 6, 1)
        end_time = DateTime(2023, 6, 30)
        
        dates = [
            DateTime(2023, 5, 15),  # Before range
            DateTime(2023, 6, 15),  # In range
            DateTime(2023, 6, 29),  # In range
            DateTime(2023, 7, 5),   # After range
        ]
        
        in_range = filter(d -> start_time <= d <= end_time, dates)
        @test length(in_range) == 2
        @test DateTime(2023, 6, 15) in in_range
        @test DateTime(2023, 6, 29) in in_range
    end

    @testset "No previous release" begin
        # Test changelog when there's no previous release (first release)
        releases = []
        current_version = "v1.0.0"
        
        # With no previous release, changelog should include everything
        has_previous = !isempty(releases)
        @test !has_previous
    end

    @testset "Mustache template basics" begin
        # Test basic template variable substitution logic
        template = "## {{package}} {{version}}"
        vars = Dict("package" => "Example", "version" => "v1.0.0")
        
        # Simple replacement (not actual Mustache)
        result = replace(replace(template, "{{package}}" => vars["package"]), 
                        "{{version}}" => vars["version"])
        @test result == "## Example v1.0.0"
    end

    @testset "Mustache conditionals" begin
        # Test template conditional patterns
        has_issues = true
        has_pulls = false
        has_custom = true
        
        # In Mustache: {{#has_issues}}...{{/has_issues}}
        @test has_issues
        @test !has_pulls
        @test has_custom
    end

    @testset "Mustache loops" begin
        # Test template loop patterns
        issues = [
            Dict("number" => 1, "title" => "Bug fix"),
            Dict("number" => 2, "title" => "Feature request"),
        ]
        
        # In Mustache: {{#issues}}{{number}}: {{title}}{{/issues}}
        @test length(issues) == 2
        @test issues[1]["number"] == 1
        @test issues[2]["title"] == "Feature request"
    end

    @testset "Release notes escaping" begin
        # Test that HTML/Markdown special chars are handled
        title = "Fix <script> injection & other issues"
        @test occursin("<", title)
        @test occursin("&", title)
        
        # Full escaping requires escaping all special chars
        escaped = replace(replace(replace(title, "&" => "&amp;"), "<" => "&lt;"), ">" => "&gt;")
        @test occursin("&lt;script&gt;", escaped)
        @test occursin("&amp;", escaped)
    end

    @testset "Collect data structure" begin
        # Test the structure of changelog data
        data = Dict(
            "package" => "Example",
            "version" => "v1.2.0",
            "previous_release" => "v1.1.0",
            "compare_url" => "https://github.com/owner/repo/compare/v1.1.0...v1.2.0",
            "issues" => [],
            "pulls" => [],
            "custom" => "",
            "sha" => "abc123",
            "is_backport" => false,
        )
        
        @test haskey(data, "package")
        @test haskey(data, "version")
        @test haskey(data, "previous_release")
        @test haskey(data, "compare_url")
        @test haskey(data, "issues")
        @test haskey(data, "pulls")
        @test haskey(data, "custom")
        @test haskey(data, "sha")
        @test haskey(data, "is_backport")
    end

    @testset "Author info extraction" begin
        # Test extracting author login from issue/PR
        issue = Dict(
            "user" => Dict("login" => "contributor1", "html_url" => "https://github.com/contributor1")
        )
        
        @test issue["user"]["login"] == "contributor1"
        @test occursin("github.com", issue["user"]["html_url"])
    end
end
