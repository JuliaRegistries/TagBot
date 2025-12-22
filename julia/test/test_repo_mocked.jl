"""
Comprehensive mocked tests for Repo functionality using Mocking.jl.
These tests mock GitHub API calls and Git operations to test integration paths.
"""

using Test
using Dates
using Base64: base64encode
using Mocking

Mocking.activate()

using TagBot
using TagBot: Repo, RepoConfig, Git, Changelog
using TagBot: InvalidProject, Abort

# Import internal functions we need to test (not exported)
import TagBot: get_gh_repo, get_registry_gh_repo, get_project_value, get_file_content
import TagBot: registry_path, get_versions, build_tags_cache!, commit_sha_of_tree
import TagBot: commit_sha_from_registry_pr, search_issues, check_rate_limit
import TagBot: version_with_latest_commit
import TagBot: filter_map_versions, build_tree_to_commit_cache!

import GitHub
import GitHub: GitHubAPI, GitHubWebAPI, OAuth2, Repo as GHRepo, PullRequest as GHPullRequest
import GitHub: Issue as GHIssue, Release as GHRelease, Commit as GHCommit, Branch as GHBranch
import GitHub: name, authenticate, repo as gh_repo, pull_requests, issues, releases
import GitHub: file, create_release as gh_create_release, create_issue as gh_create_issue
import GitHub: branch, branches
import HTTP

# ============================================================================
# Mock Helpers
# ============================================================================

"""
Create a mock OAuth2 authentication object.
"""
function mock_auth()
    return OAuth2("mock_token")
end

"""
Create a mock GitHub Repo object.
"""
function mock_gh_repo_obj(; name="Owner/TestPkg", default_branch="main", private=false)
    return GHRepo(Dict(
        "name" => split(name, "/")[2],
        "full_name" => name,
        "owner" => Dict("login" => split(name, "/")[1]),
        "default_branch" => default_branch,
        "private" => private,
        "url" => "https://api.github.com/repos/$name",
        "html_url" => "https://github.com/$name",
    ))
end

"""
Create a mock GitHub file content response.
"""
function mock_file_content(content::String)
    return GitHub.Content(Dict(
        "type" => "file",
        "encoding" => "base64",
        "size" => length(content),
        "name" => "test.toml",
        "path" => "test.toml",
        "content" => base64encode(content),
        "sha" => "abc123",
    ))
end

"""
Create a mock GitHub PullRequest.
"""
function mock_pull_request(; number=1, title="PR", state="open", merged=false, 
                            body="", head_ref="branch", created_at=now())
    return GHPullRequest(Dict(
        "number" => number,
        "title" => title,
        "state" => state,
        "merged" => merged,
        "body" => body,
        "head" => Dict("ref" => head_ref),
        "base" => Dict("ref" => "main"),
        "created_at" => Dates.format(created_at, "yyyy-mm-ddTHH:MM:SSZ"),
        "user" => Dict("login" => "testuser"),
        "html_url" => "https://github.com/Owner/Repo/pull/$number",
    ))
end

"""
Create a mock GitHub Release.
"""
function mock_release_obj(; tag_name="v1.0.0", name="v1.0.0", draft=false, prerelease=false,
                          target_commitish="abc123")
    return GHRelease(Dict(
        "tag_name" => tag_name,
        "name" => name,
        "draft" => draft,
        "prerelease" => prerelease,
        "target_commitish" => target_commitish,
        "html_url" => "https://github.com/Owner/Repo/releases/tag/$tag_name",
        "body" => "",
    ))
end

"""
Create a mock GitHub Issue.
"""
function mock_issue_obj(; number=1, title="Issue", state="open", body="", labels=[])
    return GHIssue(Dict(
        "number" => number,
        "title" => title,
        "state" => state,
        "body" => body,
        "labels" => [Dict("name" => l) for l in labels],
        "user" => Dict("login" => "testuser"),
        "html_url" => "https://github.com/Owner/Repo/issues/$number",
        "created_at" => Dates.format(now(), "yyyy-mm-ddTHH:MM:SSZ"),
        "closed_at" => nothing,
    ))
end

"""
Create a mock GitHub Branch.
"""
function mock_branch_obj(; name="main", sha="abc123")
    return GHBranch(Dict(
        "name" => name,
        "commit" => Dict("sha" => sha),
    ))
end

"""
Create mock HTTP response.
"""
function mock_http_response(; status=200, body="{}")
    return HTTP.Response(status, [], Vector{UInt8}(body))
end

# ============================================================================
# Test Constants
# ============================================================================

const TEST_PROJECT_TOML = """
name = "TestPkg"
uuid = "12345678-1234-1234-1234-123456789012"
version = "1.0.0"
"""

const TEST_REGISTRY_TOML = """
name = "General"
uuid = "23338594-aafe-5451-b93e-139f81909106"
repo = "https://github.com/JuliaRegistries/General.git"

[packages]
12345678-1234-1234-1234-123456789012 = { name = "TestPkg", path = "T/TestPkg" }
"""

const TEST_VERSIONS_TOML = """
["1.0.0"]
git-tree-sha1 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

["1.1.0"]
git-tree-sha1 = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

["2.0.0"]
git-tree-sha1 = "cccccccccccccccccccccccccccccccccccccccc"
"""

const TEST_PACKAGE_TOML = """
name = "TestPkg"
uuid = "12345678-1234-1234-1234-123456789012"
repo = "https://github.com/Owner/TestPkg.jl.git"
"""

# ============================================================================
# Helper: Create a Repo with mocked authentication
# ============================================================================

"""
Create a test Repo instance with mocked GitHub authentication.
All GitHub API calls are mocked to avoid network requests.
"""
function create_test_repo(; repo_name="Owner/TestPkg", token="test_token",
                           registry="JuliaRegistries/General")
    # Create the authentication mock - this is the key one
    auth_patch = @patch authenticate(token) = mock_auth()
    
    local repo
    apply(auth_patch) do
        config = RepoConfig(repo=repo_name, token=token, registry=registry)
        repo = Repo(config)
    end
    return repo
end

# ============================================================================
# Tests
# ============================================================================

@testset "Repo Mocked Tests" begin
    
    @testset "Repo construction with mocked auth" begin
        auth_patch = @patch authenticate(token) = mock_auth()
        
        apply(auth_patch) do
            config = RepoConfig(repo="Owner/TestPkg", token="test_token")
            repo = Repo(config)
            
            @test repo !== nothing
            @test repo.config.repo == "Owner/TestPkg"
            @test repo._gh_repo === nothing  # Lazy loaded
            @test repo._tags_cache === nothing  # Not built yet
        end
    end
    
    @testset "get_gh_repo caches result" begin
        auth_patch = @patch authenticate(token) = mock_auth()
        
        apply(auth_patch) do
            config = RepoConfig(repo="Owner/TestPkg", token="test_token")
            repo = Repo(config)
            
            mock_repo = mock_gh_repo_obj(name="Owner/TestPkg")
            gh_repo_patch = @patch gh_repo(api, repo_name; kwargs...) = mock_repo
            
            apply(gh_repo_patch) do
                # First call should invoke API
                result1 = get_gh_repo(repo)
                @test result1 !== nothing
                @test result1.full_name == "Owner/TestPkg"
                
                # Result should be cached
                @test repo._gh_repo !== nothing
            end
            
            # Second call should use cache (outside the gh_repo patch)
            result2 = get_gh_repo(repo)
            @test result2 !== nothing
            @test result2.full_name == "Owner/TestPkg"
        end
    end
    
    @testset "get_project_value reads Project.toml" begin
        auth_patch = @patch authenticate(token) = mock_auth()
        
        apply(auth_patch) do
            config = RepoConfig(repo="Owner/TestPkg", token="test_token")
            repo = Repo(config)
            
            mock_repo = mock_gh_repo_obj(name="Owner/TestPkg")
            mock_content = mock_file_content(TEST_PROJECT_TOML)
            
            gh_repo_patch = @patch gh_repo(api, repo_name; kwargs...) = mock_repo
            file_patch = @patch file(api, gh_repo, path; kwargs...) = mock_content
            
            apply([gh_repo_patch, file_patch]) do
                # Get name from Project.toml
                name = get_project_value(repo, "name")
                @test name == "TestPkg"
                
                # Get uuid
                uuid = get_project_value(repo, "uuid")
                @test uuid == "12345678-1234-1234-1234-123456789012"
                
                # Project should be cached now
                @test repo._project !== nothing
                
                # Getting another value should use cache
                version = get_project_value(repo, "version")
                @test version == "1.0.0"
            end
        end
    end
    
    @testset "registry_path finds package in registry" begin
        auth_patch = @patch authenticate(token) = mock_auth()
        
        apply(auth_patch) do
            config = RepoConfig(repo="Owner/TestPkg", token="test_token")
            repo = Repo(config)
            
            mock_pkg_repo = mock_gh_repo_obj(name="Owner/TestPkg")
            mock_registry_repo = mock_gh_repo_obj(name="JuliaRegistries/General")
            
            gh_repo_patch = @patch function gh_repo(api, repo_name; kwargs...)
                if repo_name == "Owner/TestPkg"
                    return mock_pkg_repo
                else
                    return mock_registry_repo
                end
            end
            
            file_patch = @patch function file(api, gh_repo, path; kwargs...)
                if path == "Project.toml"
                    return mock_file_content(TEST_PROJECT_TOML)
                elseif path == "Registry.toml"
                    return mock_file_content(TEST_REGISTRY_TOML)
                else
                    error("Unexpected file: $path")
                end
            end
            
            apply([gh_repo_patch, file_patch]) do
                path = registry_path(repo)
                @test path == "T/TestPkg"
                
                # Result should be cached
                @test repo._registry_path == "T/TestPkg"
            end
        end
    end
    
    @testset "get_versions parses Versions.toml" begin
        repo = create_test_repo()
        
        # Pre-set registry path to skip that lookup
        repo._registry_path = "T/TestPkg"
        
        mock_registry_repo = mock_gh_repo_obj(name="JuliaRegistries/General")
        
        gh_repo_patch = @patch gh_repo(api, repo_name; kwargs...) = mock_registry_repo
        file_patch = @patch file(api, gh_repo, path; kwargs...) = mock_file_content(TEST_VERSIONS_TOML)
        
        apply([gh_repo_patch, file_patch]) do
            versions = get_versions(repo)
            
            @test length(versions) == 3
            @test versions["1.0.0"] == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            @test versions["1.1.0"] == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            @test versions["2.0.0"] == "cccccccccccccccccccccccccccccccccccccccc"
        end
    end
    
    @testset "get existing tags with pre-populated cache" begin
        repo = create_test_repo()
        
        # Pre-populate cache to test cache logic
        repo._tags_cache = Dict(
            "v1.0.0" => "abc123",
            "v1.1.0" => "def456",
        )
        
        # Access through the repo's cache
        @test repo._tags_cache["v1.0.0"] == "abc123"
        @test repo._tags_cache["v1.1.0"] == "def456"
        @test length(repo._tags_cache) == 2
    end
    
    @testset "commit_sha_of_tree uses cache" begin
        repo = create_test_repo()
        
        # Pre-populate tree-to-commit cache
        repo._tree_to_commit_cache = Dict(
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" => "commit_aaa",
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" => "commit_bbb",
        )
        
        sha = commit_sha_of_tree(repo, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        @test sha == "commit_aaa"
        
        sha2 = commit_sha_of_tree(repo, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
        @test sha2 == "commit_bbb"
        
        # Unknown tree should return nothing
        sha3 = commit_sha_of_tree(repo, "unknown")
        @test sha3 === nothing
    end
    
    @testset "search_issues uses GitHub search API" begin
        repo = create_test_repo()
        repo._gh_repo = mock_gh_repo_obj(name="Owner/TestPkg")
        
        # Mock HTTP.get for search API
        # The call signature is: HTTP.get(url, headers; status_exception=false)
        search_response = """{
            "total_count": 2,
            "items": [
                {"number": 1, "title": "Issue 1", "state": "closed", "html_url": "https://github.com/Owner/TestPkg/issues/1", "user": {"login": "testuser"}, "labels": [], "pull_request": null, "created_at": "2024-01-01T00:00:00Z", "closed_at": "2024-01-02T00:00:00Z"},
                {"number": 2, "title": "PR 2", "state": "closed", "html_url": "https://github.com/Owner/TestPkg/pull/2", "user": {"login": "testuser"}, "labels": [], "pull_request": {"url": "https://api.github.com/repos/Owner/TestPkg/pulls/2"}, "created_at": "2024-01-01T00:00:00Z", "closed_at": "2024-01-02T00:00:00Z"}
            ]
        }"""
        
        # Match the exact call signature: HTTP.get(url::String, headers::Vector; kwargs...)
        http_patch = @patch HTTP.get(url::AbstractString, headers::AbstractVector; kwargs...) = mock_http_response(body=search_response)
        
        apply(http_patch) do
            # search_issues takes a query string, not date range
            query = "repo:Owner/TestPkg is:closed"
            items = search_issues(repo, query)
            
            @test length(items) == 2
            @test items[1].number == 1
            @test items[1].title == "Issue 1"
            @test items[2].is_pull_request == true  # Has pull_request field
        end
    end
    
    @testset "check_rate_limit handles responses" begin
        repo = create_test_repo()
        
        rate_response = """{
            "resources": {
                "core": {
                    "limit": 5000,
                    "remaining": 4999,
                    "reset": 1609459200
                }
            }
        }"""
        
        http_patch = @patch HTTP.get(url; kwargs...) = mock_http_response(body=rate_response)
        
        apply(http_patch) do
            # check_rate_limit doesn't return anything, just logs
            # We just test it doesn't throw
            check_rate_limit(repo)
            @test true  # If we get here, it worked
        end
    end
    
end

@testset "Error Handling Mocked Tests" begin
    
    @testset "get_project_value with missing key throws KeyError" begin
        repo = create_test_repo()
        
        mock_repo = mock_gh_repo_obj(name="Owner/TestPkg")
        mock_content = mock_file_content(TEST_PROJECT_TOML)
        
        gh_repo_patch = @patch gh_repo(api, repo_name; kwargs...) = mock_repo
        file_patch = @patch file(api, gh_repo, path; kwargs...) = mock_content
        
        apply([gh_repo_patch, file_patch]) do
            # Existing key works
            name = get_project_value(repo, "name")
            @test name == "TestPkg"
            
            # Missing key throws KeyError
            @test_throws KeyError get_project_value(repo, "nonexistent")
        end
    end
    
    @testset "commit_sha_of_tree returns nothing for unknown tree" begin
        repo = create_test_repo()
        
        # Empty cache
        repo._tree_to_commit_cache = Dict{String,String}()
        
        sha = commit_sha_of_tree(repo, "unknown_tree_sha")
        @test sha === nothing
    end
    
end

@testset "Subpackage Mocked Tests" begin
    
    @testset "subdir handling in tag names" begin
        auth_patch = @patch authenticate(token) = mock_auth()
        
        apply(auth_patch) do
            config = RepoConfig(
                repo="Owner/MonoRepo", 
                token="test_token",
                subdir="SubPkg"
            )
            repo = Repo(config)
            
            @test repo.config.subdir == "SubPkg"
        end
    end
    
end

@testset "Git Operations Mocked Tests" begin
    
    @testset "Git helper construction" begin
        repo = create_test_repo()
        
        git = repo.git
        @test git !== nothing
        @test git.repo == "Owner/TestPkg"
    end
    
end

@testset "Changelog Mocked Tests" begin
    
    @testset "Changelog construction" begin
        repo = create_test_repo()
        
        changelog = repo.changelog
        @test changelog !== nothing
    end
    
end

@testset "HTTP Error Handling" begin
    
    @testset "check_rate_limit handles HTTP errors gracefully" begin
        repo = create_test_repo()
        
        http_patch = @patch HTTP.get(url; kwargs...) = throw(HTTP.RequestError(
            HTTP.Request("GET", "test"),
            ErrorException("Connection failed")
        ))
        
        apply(http_patch) do
            # check_rate_limit catches errors internally and logs @debug
            # It should not throw, just silently handle the error
            check_rate_limit(repo)
            @test true  # If we get here, it handled the error gracefully
        end
    end
    
end
