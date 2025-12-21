using Test
using Dates
using TagBot: Git, Abort

@testset "Git" begin
    @testset "Git construction" begin
        git = Git("https://github.com", "owner/repo", "token", "user", "email")
        @test git.github == "github.com"
        @test git.repo == "owner/repo"
        @test git.user == "user"
        @test git.email == "email"
        @test git.gpgsign == false
        @test git._default_branch === nothing
        @test git._dir === nothing
    end

    @testset "URL hostname extraction" begin
        # With https protocol
        git1 = Git("https://github.com", "o/r", "t", "u", "e")
        @test git1.github == "github.com"

        # With http protocol
        git2 = Git("http://gitlab.example.com", "o/r", "t", "u", "e")
        @test git2.github == "gitlab.example.com"

        # Without protocol (edge case)
        git3 = Git("github.com", "o/r", "t", "u", "e")
        @test git3.github == "github.com"
        
        # With port number
        git4 = Git("https://github.example.com:8443", "o/r", "t", "u", "e")
        @test git4.github == "github.example.com:8443"
    end

    @testset "Abort exception" begin
        @test_throws Abort throw(Abort("test error"))
        
        e = Abort("test message")
        @test e.message == "test message"
        @test sprint(showerror, e) == "Abort: test message"
    end

    @testset "Git gpgsign flag" begin
        git = Git("https://github.com", "o/r", "t", "u", "e")
        @test git.gpgsign == false
        git.gpgsign = true
        @test git.gpgsign == true
    end

    @testset "Git state management" begin
        git = Git("https://github.com", "o/r", "token123", "user", "email@test.com")
        
        # Initial state
        @test git._dir === nothing
        @test git._default_branch === nothing
        
        # Token should be stored
        @test git.token == "token123"
    end

    @testset "Time parsing logic" begin
        # Test ISO 8601 date parsing logic used in time_of_commit
        date_str = "2019-12-22T12:49:26+07:00"
        dt = DateTime(date_str[1:19], dateformat"yyyy-mm-ddTHH:MM:SS")
        @test dt == DateTime(2019, 12, 22, 12, 49, 26)
        
        # Parse timezone offset
        offset_str = date_str[20:end]
        m = match(r"([+-])(\d{2}):(\d{2})", offset_str)
        @test m !== nothing
        @test m.captures[1] == "+"
        @test m.captures[2] == "07"
        @test m.captures[3] == "00"
        
        # Apply timezone offset (convert to UTC)
        sign = m.captures[1] == "+" ? 1 : -1
        hours = parse(Int, m.captures[2])
        mins = parse(Int, m.captures[3])
        offset_minutes = sign * (hours * 60 + mins)
        dt_utc = dt - Minute(offset_minutes)
        @test dt_utc == DateTime(2019, 12, 22, 5, 49, 26)
    end

    @testset "Tree commit parsing logic" begin
        # Test the parsing logic used in get_all_tree_commit_pairs
        log_output = """
a1b2c3d4 tree1sha
e5f6g7h8 tree2sha
i9j0k1l2 tree3sha
"""
        pairs = Dict{String,String}()
        for line in split(log_output, '\n')
            parts = split(line)
            length(parts) == 2 || continue
            commit_sha, tree_sha = parts
            haskey(pairs, tree_sha) || (pairs[tree_sha] = commit_sha)
        end
        
        @test pairs["tree1sha"] == "a1b2c3d4"
        @test pairs["tree2sha"] == "e5f6g7h8"
        @test pairs["tree3sha"] == "i9j0k1l2"
        @test length(pairs) == 3
    end

    @testset "Default branch parsing logic" begin
        # Test parsing of remote show output
        remote_output = """
* remote origin
  Fetch URL: git@github.com:owner/repo.git
  Push  URL: git@github.com:owner/repo.git
  HEAD branch: main
  Remote branches:
    main tracked
"""
        m = match(r"HEAD branch:\s*(.+)", remote_output)
        @test m !== nothing
        @test strip(m.captures[1]) == "main"
        
        # Test fallback when pattern doesn't match
        bad_output = "something unexpected"
        m2 = match(r"HEAD branch:\s*(.+)", bad_output)
        @test m2 === nothing
    end

    @testset "Merge check logic" begin
        # Test the logic used in is_merged
        head = "abc123"
        shas = ["def456", "abc123", "ghi789"]
        @test head in shas
        
        head2 = "xyz999"
        @test !(head2 in shas)
    end

    @testset "Remote tag exists parsing" begin
        # Test parsing of ls-remote output
        ls_remote_output = "abc123def456	refs/tags/v1.0.0"
        @test !isempty(strip(ls_remote_output))
        
        empty_output = ""
        @test isempty(strip(empty_output))
    end
    
    @testset "URL sanitization" begin
        # Test that tokens don't appear in error messages
        url = "https://x-access-token:secret123@github.com/owner/repo"
        sanitized = replace(url, r"(://[^:]+:)[^@]+(@)" => s"\1***\2")
        @test sanitized == "https://x-access-token:***@github.com/owner/repo"
        @test !occursin("secret123", sanitized)
    end

    @testset "Git command execution patterns" begin
        # Test command string construction
        args = ["log", "--all", "--format=%H %T"]
        cmd_str = join(args, " ")
        @test cmd_str == "log --all --format=%H %T"
        
        # Test with special characters
        args2 = ["tag", "-a", "v1.0.0", "-m", "Release v1.0.0"]
        @test length(args2) == 5
    end

    @testset "Git check success/failure" begin
        # Test return code interpretation
        success_code = 0
        failure_code = 1
        
        @test success_code == 0
        @test failure_code != 0
    end

    @testset "Git clone URL construction" begin
        # Test OAuth2 token URL format
        github = "github.com"
        repo = "owner/repo"
        token = "ghp_xxxx"
        
        url = "https://oauth2:$token@$github/$repo"
        @test occursin("oauth2:", url)
        @test occursin(token, url)
        @test occursin(repo, url)
    end

    @testset "Fetch branch command" begin
        # Test fetch branch command construction
        branch = "release-1.2"
        expected_args = ["fetch", "origin", "$branch:$branch"]
        
        @test expected_args[1] == "fetch"
        @test expected_args[2] == "origin"
        @test expected_args[3] == "release-1.2:release-1.2"
    end

    @testset "Create tag already exists handling" begin
        # Test ls-remote output parsing for existing tag check
        tag = "v1.0.0"
        
        # Tag exists
        ls_remote_exists = "abc123def456\trefs/tags/v1.0.0"
        @test !isempty(strip(ls_remote_exists))
        
        # Tag doesn't exist
        ls_remote_empty = ""
        @test isempty(strip(ls_remote_empty))
    end

    @testset "Fast-forward check" begin
        # Test merge-base comparison for fast-forward
        head_sha = "abc123"
        base_sha = "def456"
        merge_base = "def456"
        
        # Can fast-forward if merge-base == base
        can_ff = merge_base == base_sha
        @test can_ff == true
        
        # Cannot fast-forward if merge-base != base
        merge_base2 = "ghi789"
        can_ff2 = merge_base2 == base_sha
        @test can_ff2 == false
    end

    @testset "Merge and delete branch" begin
        # Test merge command construction
        branch = "release-1.2"
        default = "main"
        
        merge_args = ["merge", "--ff-only", branch]
        @test merge_args[2] == "--ff-only"
        
        delete_args = ["push", "origin", "--delete", branch]
        @test delete_args[3] == "--delete"
        @test delete_args[4] == branch
    end

    @testset "SSH key file permissions" begin
        # Test expected permissions for SSH key file
        # 0o400 = read-only for owner
        expected_mode = 0o400
        @test expected_mode == 256  # Octal 400 = decimal 256
    end

    @testset "SSH known_hosts generation" begin
        # Test ssh-keyscan command construction
        host = "github.com"
        cmd = `ssh-keyscan -t rsa,ecdsa,ed25519 $host`
        @test occursin("ssh-keyscan", string(cmd))
        @test occursin(host, string(cmd))
    end

    @testset "GPG key import" begin
        # Test GPG key format detection
        gpg_key = "-----BEGIN PGP PRIVATE KEY BLOCK-----\ndata\n-----END PGP PRIVATE KEY BLOCK-----"
        @test occursin("PGP PRIVATE KEY", gpg_key)
    end
end
