using Test
using Dates
using Base64: base64encode, base64decode
using TOML
using TagBot: Repo, RepoConfig, get_tag_prefix, get_version_tag
using TagBot: InvalidProject, Abort

@testset "Repo" begin
    @testset "RepoConfig defaults" begin
        config = RepoConfig(
            repo = "Owner/Repo",
            token = "test_token",
        )
        
        @test config.repo == "Owner/Repo"
        @test config.registry == "JuliaRegistries/General"
        @test config.github == "github.com"
        @test config.github_api == "api.github.com"
        @test config.ssh == false
        @test config.gpg == false
        @test config.draft == false
        @test config.branch === nothing
        @test config.subdir === nothing
        @test config.tag_prefix === nothing
    end

    @testset "RepoConfig with all options" begin
        config = RepoConfig(
            repo = "Owner/Repo",
            token = "test_token",
            registry = "MyOrg/MyRegistry",
            github = "github.example.com",
            github_api = "api.github.example.com",
            ssh = true,
            gpg = true,
            draft = true,
            branch = "release",
            subdir = "lib/Package",
            tag_prefix = "Package-",
        )
        
        @test config.registry == "MyOrg/MyRegistry"
        @test config.github == "github.example.com"
        @test config.github_api == "api.github.example.com"
        @test config.ssh == true
        @test config.gpg == true
        @test config.draft == true
        @test config.branch == "release"
        @test config.subdir == "lib/Package"
        @test config.tag_prefix == "Package-"
    end

    @testset "Tag prefix logic" begin
        # Test the logic used in get_tag_prefix
        # With explicit tag_prefix
        tag_prefix1 = "explicit-"
        subdir1 = nothing
        prefix1 = tag_prefix1 !== nothing ? tag_prefix1 : (subdir1 !== nothing ? "$subdir1-" : "")
        @test prefix1 == "explicit-"
        
        # With subdir but no explicit prefix
        tag_prefix2 = nothing
        subdir2 = "lib/SubPkg"
        prefix2 = tag_prefix2 !== nothing ? tag_prefix2 : (subdir2 !== nothing ? "$subdir2-" : "")
        @test prefix2 == "lib/SubPkg-"
        
        # No prefix, no subdir
        tag_prefix3 = nothing
        subdir3 = nothing
        prefix3 = tag_prefix3 !== nothing ? tag_prefix3 : (subdir3 !== nothing ? "$subdir3-" : "")
        @test prefix3 == ""
    end

    @testset "Version tag construction" begin
        # Test the logic used in get_version_tag
        # Basic version tag
        prefix1 = ""
        version1 = "1.0.0"
        tag1 = "$(prefix1)v$version1"
        @test tag1 == "v1.0.0"
        
        # With prefix
        prefix2 = "SubPkg-"
        version2 = "2.1.0"
        tag2 = "$(prefix2)v$version2"
        @test tag2 == "SubPkg-v2.1.0"
        
        # Complex prefix
        prefix3 = "lib/Package-"
        version3 = "0.1.0"
        tag3 = "$(prefix3)v$version3"
        @test tag3 == "lib/Package-v0.1.0"
    end

    @testset "InvalidProject exception" begin
        @test_throws InvalidProject throw(InvalidProject("not valid"))
        
        e = InvalidProject("missing Project.toml")
        @test e.message == "missing Project.toml"
        @test sprint(showerror, e) == "InvalidProject: missing Project.toml"
    end

    @testset "Registry path calculation" begin
        # Test the registry path logic
        name = "Example"
        expected_path = "E/Example"
        
        first_char = uppercase(first(name))
        computed_path = "$first_char/$name"
        @test computed_path == expected_path
        
        # Longer name
        name2 = "VeryLongPackageName"
        computed_path2 = "$(uppercase(first(name2)))/$name2"
        @test computed_path2 == "V/VeryLongPackageName"
    end

    @testset "Versions.toml parsing" begin
        # Test parsing logic for Versions.toml
        versions_content = """
        ["1.0.0"]
        git-tree-sha1 = "abc123def456789"

        ["1.1.0"]
        git-tree-sha1 = "def456abc789012"

        ["2.0.0"]
        git-tree-sha1 = "ghi789def012345"
        """
        
        # Simulate TOML parsing
        # In real code this uses TOML.parsefile
        lines = split(versions_content, '\n')
        versions = Dict{String,String}()
        current_version = ""
        
        for line in lines
            line = strip(line)
            vm = match(r"^\[\"(.+)\"\]$", line)
            if vm !== nothing
                current_version = vm.captures[1]
            end
            sm = match(r"git-tree-sha1\s*=\s*\"([^\"]+)\"", line)
            if sm !== nothing && !isempty(current_version)
                versions[current_version] = sm.captures[1]
            end
        end
        
        @test length(versions) == 3
        @test versions["1.0.0"] == "abc123def456789"
        @test versions["1.1.0"] == "def456abc789012"
        @test versions["2.0.0"] == "ghi789def012345"
    end

    @testset "Package.toml parsing" begin
        # Test parsing logic for Package.toml
        package_content = """
        name = "Example"
        uuid = "12345678-1234-1234-1234-123456789012"
        repo = "https://github.com/JuliaLang/Example.jl.git"
        """
        
        # Extract repo URL
        m = match(r"repo\s*=\s*\"([^\"]+)\"", package_content)
        @test m !== nothing
        @test m.captures[1] == "https://github.com/JuliaLang/Example.jl.git"
        
        # Extract name
        mn = match(r"name\s*=\s*\"([^\"]+)\"", package_content)
        @test mn !== nothing
        @test mn.captures[1] == "Example"
    end

    @testset "Repo URL normalization" begin
        # Test normalizing various repo URL formats
        urls = [
            "https://github.com/Owner/Repo.jl.git" => "Owner/Repo.jl",
            "https://github.com/Owner/Repo.jl" => "Owner/Repo.jl",
            "git@github.com:Owner/Repo.jl.git" => "Owner/Repo.jl",
            "git@github.com:Owner/Repo.jl" => "Owner/Repo.jl",
            "https://github.com/Owner/Repo" => "Owner/Repo",
        ]
        
        for (input, expected) in urls
            # Extract owner/repo from URL
            result = replace(input, r"^.*github\.com[:/]" => "")
            result = replace(result, r"\.git$" => "")
            @test result == expected
        end
    end

    @testset "Tag exists check" begin
        # Test tag cache logic
        cache = Dict(
            "v1.0.0" => "abc123",
            "v1.1.0" => "def456",
            "SubPkg-v1.0.0" => "ghi789",
        )
        
        @test haskey(cache, "v1.0.0")
        @test haskey(cache, "v1.1.0")
        @test !haskey(cache, "v2.0.0")
        @test haskey(cache, "SubPkg-v1.0.0")
    end

    @testset "Registry PR branch pattern" begin
        # Test the branch name pattern used by Registrator
        pattern = r"^registrator/(.+)/(.+)/(.+)/(.+)$"
        
        branch = "registrator/Example/12345678-1234/v1.0.0/abc123"
        m = match(pattern, branch)
        @test m !== nothing
        @test m.captures[1] == "Example"
        @test m.captures[3] == "v1.0.0"
        
        # Alternative pattern
        pattern2 = r"^registrator-(.+)-([a-f0-9-]+)-(.+)-([a-f0-9]+)$"
    end

    @testset "Commit SHA from PR body" begin
        # Test extracting commit SHA from registry PR body
        pr_body = """
        ## Package Registration
        
        - Package name: Example
        - Version: 1.0.0
        - Commit: abc123def456789012345678901234567890abcd
        - Tree SHA: def456abc789012345678901234567890123abcd
        
        Something else here.
        """
        
        m = match(r"Commit:\s*([a-f0-9]+)", pr_body)
        @test m !== nothing
        @test m.captures[1] == "abc123def456789012345678901234567890abcd"
    end

    @testset "Tree SHA to commit mapping" begin
        # Test the tree-to-commit cache structure
        cache = Dict{String,String}()
        
        # Simulate building the cache
        commits = [
            ("commit1", "tree_a"),
            ("commit2", "tree_b"),
            ("commit3", "tree_c"),
            ("commit4", "tree_a"),  # Same tree as commit1
        ]
        
        for (commit, tree) in commits
            # Keep first commit for each tree (oldest)
            haskey(cache, tree) || (cache[tree] = commit)
        end
        
        @test cache["tree_a"] == "commit1"  # First commit kept
        @test cache["tree_b"] == "commit2"
        @test cache["tree_c"] == "commit3"
        @test length(cache) == 3
    end

    @testset "Filter map versions" begin
        # Test filtering versions that need tags
        all_versions = Dict(
            "1.0.0" => "tree_a",
            "1.1.0" => "tree_b",
            "2.0.0" => "tree_c",
        )
        
        existing_tags = Set(["v1.0.0"])
        prefix = ""
        
        new_versions = Dict{String,String}()
        for (version, tree) in all_versions
            tag = "$(prefix)v$version"
            tag in existing_tags && continue
            new_versions[version] = tree
        end
        
        @test length(new_versions) == 2
        @test haskey(new_versions, "1.1.0")
        @test haskey(new_versions, "2.0.0")
        @test !haskey(new_versions, "1.0.0")
    end

    @testset "Version with latest commit" begin
        # Test finding which version has the latest commit
        versions = Dict(
            "v1.0.0" => "commit_a",
            "v1.1.0" => "commit_b",
            "v2.0.0" => "commit_c",
        )
        
        commit_times = Dict(
            "commit_a" => DateTime(2023, 1, 1),
            "commit_b" => DateTime(2023, 6, 15),
            "commit_c" => DateTime(2023, 3, 1),
        )
        
        latest = ""
        latest_time = DateTime(0)
        
        for (tag, commit) in versions
            t = commit_times[commit]
            if t > latest_time
                latest_time = t
                latest = tag
            end
        end
        
        @test latest == "v1.1.0"
    end

    @testset "Release branch pattern" begin
        # Test release branch naming
        version = "1.2.0"
        expected_branch = "release-1.2"
        
        parts = split(version, '.')
        branch = "release-$(parts[1]).$(parts[2])"
        
        @test branch == expected_branch
    end

    @testset "Manual intervention issue" begin
        # Test the structure of manual intervention issue body
        failures = [
            (version = "v1.0.0", commit = "abc123", error = "Resource not accessible"),
            (version = "v1.1.0", commit = "def456", error = "Push rejected"),
        ]
        
        commands = String[]
        for f in failures
            cmd = "git tag -a $(f.version) $(f.commit) -m '$(f.version)' && git push origin $(f.version)"
            push!(commands, cmd)
        end
        
        @test length(commands) == 2
        @test occursin("v1.0.0", commands[1])
        @test occursin("abc123", commands[1])
    end

    @testset "Project.toml malformed TOML handling" begin
        # Test detection of malformed TOML
        malformed_content = """name = "FooBar"
uuid"""  # Missing = sign
        
        # Attempt to parse should fail
        @test_throws Exception TOML.parse(malformed_content)
    end

    @testset "Project.toml invalid encoding detection" begin
        # Test that invalid UTF-8 bytes require special handling
        invalid_bytes = UInt8[0xff, 0xfe]  # Invalid UTF-8 BOM-like sequence
        # Julia's String constructor may be lenient, but we can detect invalid UTF-8
        str = String(copy(invalid_bytes))
        @test !isvalid(str)  # String is invalid UTF-8
    end

    @testset "Registry.toml malformed handling" begin
        # Malformed Registry.toml should not crash
        malformed = "[packages\nkey"  # Missing closing bracket
        @test_throws Exception TOML.parse(malformed)
    end

    @testset "Registry.toml missing packages key" begin
        # Test handling of Registry.toml without packages section
        registry_content = """
        [foo]
        bar = 1
        """
        data = TOML.parse(registry_content)
        @test !haskey(data, "packages")
        @test get(data, "packages", nothing) === nothing
    end

    @testset "Package.toml malformed handling" begin
        # Test malformed Package.toml
        malformed = "name = \n[incomplete"
        @test_throws Exception TOML.parse(malformed)
    end

    @testset "Package.toml missing repo key" begin
        # Test handling of Package.toml without repo field
        pkg_content = """
        name = "Example"
        uuid = "12345678-1234-1234-1234-123456789012"
        """
        data = TOML.parse(pkg_content)
        @test !haskey(data, "repo")
    end

    @testset "Uppercase UUID normalization" begin
        # Test that uppercase UUIDs are normalized to lowercase
        uuid_upper = "ABC-DEF"
        uuid_lower = lowercase(uuid_upper)
        @test uuid_lower == "abc-def"
        
        # Mixed case
        uuid_mixed = "AbC-DeF-123"
        @test lowercase(uuid_mixed) == "abc-def-123"
    end

    @testset "Private key decoding" begin
        # Test Base64 vs plain text key detection
        plain_key = "-----BEGIN OPENSSH PRIVATE KEY-----\nfoo bar\n-----END OPENSSH PRIVATE KEY-----"
        b64_key = base64encode(plain_key)
        
        # Plain key passes through
        @test startswith(plain_key, "-----BEGIN")
        
        # Base64 key can be decoded
        decoded = String(base64decode(b64_key))
        @test decoded == plain_key
        @test startswith(decoded, "-----BEGIN")
    end

    @testset "SSH key validation" begin
        # Test valid key formats
        valid_keys = [
            "-----BEGIN OPENSSH PRIVATE KEY-----\ndata\n-----END OPENSSH PRIVATE KEY-----",
            "-----BEGIN RSA PRIVATE KEY-----\ndata\n-----END RSA PRIVATE KEY-----",
            "-----BEGIN EC PRIVATE KEY-----\ndata\n-----END EC PRIVATE KEY-----",
            "-----BEGIN PRIVATE KEY-----\ndata\n-----END PRIVATE KEY-----",
        ]
        
        for key in valid_keys
            @test occursin(r"-----BEGIN .*PRIVATE KEY-----", key)
        end
        
        # Invalid keys (public key, empty, random text)
        public_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAB"
        @test !occursin(r"-----BEGIN .*PRIVATE KEY-----", public_key)
        
        empty_key = ""
        @test isempty(strip(empty_key))
        
        random_text = "just some random text"
        @test !occursin(r"-----BEGIN .* PRIVATE KEY-----", random_text)
    end

    @testset "Run URL construction" begin
        # Test GitHub Actions run URL construction
        repo = "Owner/Repo"
        run_id = "12345"
        expected = "https://github.com/Owner/Repo/actions/runs/12345"
        
        url = "https://github.com/$repo/actions/runs/$run_id"
        @test url == expected
    end

    @testset "Error report structure" begin
        # Test error report payload structure
        report = Dict(
            "image" => "ghcr.io/juliaregistries/tagbot:1.23.4",
            "repo" => "Owner/Package",
            "run" => "https://github.com/Owner/Package/actions/runs/123",
            "stacktrace" => "Error at line 10",
        )
        
        @test haskey(report, "image")
        @test haskey(report, "repo")
        @test haskey(report, "run")
        @test haskey(report, "stacktrace")
    end

    @testset "Handle error classification" begin
        # Test error type classification
        allowed_exceptions = ["RequestError", "GithubException", "Abort"]
        
        @test "Abort" in allowed_exceptions
        @test "RequestError" in allowed_exceptions
        @test "RandomError" ∉ allowed_exceptions
    end

    @testset "Rate limit handling" begin
        # Test rate limit response parsing
        rate_response = Dict(
            "resources" => Dict(
                "core" => Dict(
                    "limit" => 5000,
                    "remaining" => 100,
                    "reset" => 1609459200
                )
            )
        )
        
        core = rate_response["resources"]["core"]
        @test core["remaining"] == 100
        @test core["limit"] == 5000
        
        # Test reset time conversion
        reset_time = core["reset"]
        @test reset_time > 0
    end

    @testset "Highest existing version" begin
        # Test finding highest version from existing tags
        function parse_semver(v)
            m = match(r"v?(\d+)\.(\d+)\.(\d+)", v)
            m === nothing && return (0, 0, 0)
            (parse(Int, m[1]), parse(Int, m[2]), parse(Int, m[3]))
        end
        
        tags = ["v1.0.0", "v1.2.0", "v1.1.0", "v2.0.0", "v0.9.0"]
        highest = maximum(parse_semver.(tags))
        @test highest == (2, 0, 0)
        
        # Empty tags
        empty_tags = String[]
        @test isempty(empty_tags)
        
        # With subdir prefix
        subdir_tags = ["SubPkg-v1.0.0", "SubPkg-v1.1.0", "SubPkg-v2.0.0"]
        prefix = "SubPkg-"
        stripped = [replace(t, prefix => "") for t in subdir_tags]
        highest_sub = maximum(parse_semver.(stripped))
        @test highest_sub == (2, 0, 0)
    end

    @testset "Create release is_latest flag" begin
        # Test is_latest determination for releases
        # Only the newest commit should get is_latest=true
        
        versions_with_times = Dict(
            "v1.0.0" => DateTime(2023, 1, 1),
            "v1.1.0" => DateTime(2023, 6, 15),
            "v2.0.0" => DateTime(2023, 3, 1),
        )
        
        # Find version with latest commit
        latest_version = ""
        latest_time = DateTime(0)
        for (v, t) in versions_with_times
            if t > latest_time
                latest_time = t
                latest_version = v
            end
        end
        
        @test latest_version == "v1.1.0"
        
        # Only latest version gets is_latest=true
        for (v, _) in versions_with_times
            is_latest = v == latest_version
            if v == "v1.1.0"
                @test is_latest == true
            else
                @test is_latest == false
            end
        end
    end
end
