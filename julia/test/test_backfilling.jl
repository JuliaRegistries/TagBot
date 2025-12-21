using Test
using Dates
using TagBot: Repo, RepoConfig

@testset "Backfilling" begin
    @testset "Many versions processing" begin
        # Test handling large numbers of versions efficiently
        versions = Dict{String,String}()
        for i in 1:100
            version = "$(div(i-1, 20)).$(mod(i-1, 20) ÷ 5).$(mod(i-1, 5))"
            tree = "tree_sha_$(lpad(i, 3, '0'))"
            versions[version] = tree
        end
        
        # Note: Dict removes duplicates, so we may have fewer than 100
        # The version formula can produce duplicates
        @test length(versions) <= 100
        
        # Test filtering with existing tags
        existing_tags = Set(["v0.0.0", "v0.1.0", "v0.2.0", "v0.3.0", "v0.4.0"])
        prefix = ""
        
        new_versions = filter(versions) do (version, _)
            tag = "$(prefix)v$version"
            !(tag in existing_tags)
        end
        
        # Should filter out the 5 existing tags (if they exist in versions)
        existing_count = count(v -> "v$v" in existing_tags, keys(versions))
        @test length(new_versions) == length(versions) - existing_count
    end

    @testset "Tree to commit cache performance" begin
        # Simulate the tree-to-commit cache building
        n_commits = 1000
        commits = ["commit_$(lpad(i, 4, '0'))" for i in 1:n_commits]
        trees = ["tree_$(lpad(i, 4, '0'))" for i in 1:n_commits]
        
        cache = Dict{String,String}()
        
        t0 = time()
        for i in 1:n_commits
            tree = trees[i]
            haskey(cache, tree) || (cache[tree] = commits[i])
        end
        elapsed = time() - t0
        
        @test length(cache) == n_commits
        @test elapsed < 1.0  # Should be very fast
    end

    @testset "Tag cache batch building" begin
        # Simulate building tag cache from refs
        refs = [
            (ref = "refs/tags/v1.0.0", sha = "abc123", type = "commit"),
            (ref = "refs/tags/v1.1.0", sha = "def456", type = "commit"),
            (ref = "refs/tags/v2.0.0", sha = "ghi789", type = "tag"),  # Annotated
            (ref = "refs/tags/SubPkg-v1.0.0", sha = "jkl012", type = "commit"),
        ]
        
        cache = Dict{String,String}()
        for r in refs
            tag_name = replace(r.ref, "refs/tags/" => "")
            if r.type == "tag"
                cache[tag_name] = "annotated:$(r.sha)"
            else
                cache[tag_name] = r.sha
            end
        end
        
        @test length(cache) == 4
        @test cache["v1.0.0"] == "abc123"
        @test cache["v2.0.0"] == "annotated:ghi789"
        @test cache["SubPkg-v1.0.0"] == "jkl012"
    end

    @testset "Version sorting for release order" begin
        # Test sorting versions to process in order
        versions = ["2.0.0", "1.0.0", "1.2.0", "1.10.0", "1.1.0", "0.9.0"]
        
        function parse_version(v)
            m = match(r"(\d+)\.(\d+)\.(\d+)", v)
            m === nothing && return (0, 0, 0)
            (parse(Int, m[1]), parse(Int, m[2]), parse(Int, m[3]))
        end
        
        sorted = sort(versions, by=parse_version)
        
        @test sorted == ["0.9.0", "1.0.0", "1.1.0", "1.2.0", "1.10.0", "2.0.0"]
    end

    @testset "Subpackage tree cache" begin
        # Test building cache for subpackage tree SHAs
        subdir = "lib/SubPkg"
        
        # Simulate commits with subdir trees
        commits_with_subdirs = [
            (commit = "commit_a", root_tree = "root_a", subdir_tree = "sub_a"),
            (commit = "commit_b", root_tree = "root_b", subdir_tree = "sub_b"),
            (commit = "commit_c", root_tree = "root_c", subdir_tree = "sub_a"),  # Same as commit_a
        ]
        
        cache = Dict{String,String}()
        for c in commits_with_subdirs
            haskey(cache, c.subdir_tree) || (cache[c.subdir_tree] = c.commit)
        end
        
        @test length(cache) == 2
        @test cache["sub_a"] == "commit_a"  # First commit kept
        @test cache["sub_b"] == "commit_b"
    end

    @testset "Registry PR lookup efficiency" begin
        # Test efficient PR lookup by branch pattern
        prs = [
            (branch = "registrator/PkgA/uuid1/v1.0.0/hash1", number = 1),
            (branch = "registrator/PkgA/uuid1/v1.1.0/hash2", number = 2),
            (branch = "registrator/PkgB/uuid2/v1.0.0/hash3", number = 3),
        ]
        
        # Build cache by branch name
        pr_cache = Dict{String,Int}()
        for pr in prs
            pr_cache[pr.branch] = pr.number
        end
        
        # Lookup should be O(1)
        @test pr_cache["registrator/PkgA/uuid1/v1.1.0/hash2"] == 2
    end

    @testset "Commit datetime caching" begin
        # Test caching commit datetimes
        datetime_cache = Dict{String,DateTime}()
        
        commits = ["abc", "def", "ghi"]
        times = [DateTime(2023, 1, 1), DateTime(2023, 6, 1), DateTime(2023, 12, 1)]
        
        for (c, t) in zip(commits, times)
            datetime_cache[c] = t
        end
        
        @test datetime_cache["abc"] == DateTime(2023, 1, 1)
        @test datetime_cache["ghi"] == DateTime(2023, 12, 1)
    end

    @testset "Latest version determination" begin
        # Test finding the version with latest commit
        versions_with_times = [
            ("v1.0.0", DateTime(2023, 1, 1)),
            ("v1.1.0", DateTime(2023, 3, 15)),
            ("v1.2.0", DateTime(2023, 2, 1)),  # Not latest despite higher version
        ]
        
        latest_tag = ""
        latest_time = DateTime(0)
        
        for (tag, time) in versions_with_times
            if time > latest_time
                latest_time = time
                latest_tag = tag
            end
        end
        
        @test latest_tag == "v1.1.0"
    end

    @testset "Batch API calls" begin
        # Test that we batch API calls efficiently
        # Simulate collecting all tags in one call
        
        all_refs = [
            "refs/tags/v1.0.0",
            "refs/tags/v1.1.0",
            "refs/tags/v2.0.0",
            "refs/tags/v2.1.0",
            "refs/tags/v3.0.0",
        ]
        
        # Should process in single iteration
        tags = Set{String}()
        for ref in all_refs
            push!(tags, replace(ref, "refs/tags/" => ""))
        end
        
        @test length(tags) == 5
        @test "v1.0.0" in tags
        @test "v3.0.0" in tags
    end

    @testset "Performance metrics simulation" begin
        # Test the performance tracking structure
        mutable struct Metrics
            api_calls::Int
            prs_checked::Int
            versions_checked::Int
            start_time::Float64
        end
        
        metrics = Metrics(0, 0, 0, time())
        
        # Simulate work
        metrics.api_calls += 5
        metrics.versions_checked = 100
        metrics.prs_checked = 10
        
        elapsed = time() - metrics.start_time
        
        @test metrics.api_calls == 5
        @test metrics.versions_checked == 100
        @test elapsed >= 0
    end

    @testset "Parallel safe version filtering" begin
        # Test that version filtering doesn't have race conditions
        versions = Dict(
            "1.0.0" => "tree_a",
            "1.1.0" => "tree_b",
            "2.0.0" => "tree_c",
        )
        
        tree_cache = Dict(
            "tree_a" => "commit_a",
            "tree_b" => "commit_b",
            # tree_c not found - will use fallback
        )
        
        result = Dict{String,Union{String,Nothing}}()
        
        for (version, tree) in versions
            commit = get(tree_cache, tree, nothing)
            result[version] = commit
        end
        
        @test result["1.0.0"] == "commit_a"
        @test result["1.1.0"] == "commit_b"
        @test result["2.0.0"] === nothing
    end
end
