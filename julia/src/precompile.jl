"""
PrecompileTools workload for TagBot.

This file contains representative workloads to precompile hot paths,
ensuring fast startup times in the Docker container.
"""

@setup_workload begin
    # Mock environment setup
    mock_token = "ghp_mock_token_for_precompilation"

    @compile_workload begin
        # Precompile type constructors
        config = RepoConfig(
            repo = "TestOwner/TestRepo",
            registry = "JuliaRegistries/General",
            token = mock_token,
        )

        # Precompile SemVer parsing
        v1 = SemVer("1.2.3")
        v2 = SemVer("1.2.4")
        v3 = SemVer("2.0.0-alpha")
        _ = v1 < v2
        _ = v2 < v3
        _ = string(v1)

        # Precompile string operations
        _ = slug("changelog skip")
        _ = sanitize("token: $mock_token", mock_token)

        # Precompile JSON operations (creates type inference)
        json_str = """{"key": "value", "number": 42}"""
        _ = JSON3.read(json_str)
        _ = JSON3.write(Dict("test" => "value"))

        # Precompile TOML operations
        toml_str = """
        [project]
        name = "TestPackage"
        uuid = "12345678-1234-1234-1234-123456789012"
        version = "1.0.0"
        """
        _ = TOML.parse(toml_str)

        # Precompile HTTP header construction
        headers = [
            "Authorization" => "Bearer $mock_token",
            "Accept" => "application/vnd.github+json",
        ]

        # Precompile datetime operations
        dt = DateTime(2024, 1, 1)
        _ = Dates.format(dt, dateformat"yyyy-mm-ddTHH:MM:SS")
        _ = dt + Minute(1)

        # Precompile Mustache template
        template = """
        ## {{ package }} {{ version }}
        {{#pulls}}
        - {{ title }} (#{{ number }})
        {{/pulls}}
        """
        data = Dict(
            "package" => "TestPackage",
            "version" => "v1.0.0",
            "pulls" => [
                Dict("title" => "Fix bug", "number" => 1),
            ]
        )
        _ = Mustache.render(template, data)

        # Precompile regex patterns used in parsing
        _ = match(r"HEAD branch:\s*(.+)", "HEAD branch: main")
        _ = match(r"- Commit: ([a-f0-9]{32,40})", "- Commit: abc123def456")
        _ = match(r"https?://([^/]+)", "https://github.com")

        # Precompile base64 operations
        encoded = Base64.base64encode("test content")
        _ = Base64.base64decode(encoded)

        # Precompile performance metrics
        metrics = PerformanceMetrics()
        reset!(metrics)

        # Don't actually log during precompilation
        # but ensure the code paths are compiled
    end
end
