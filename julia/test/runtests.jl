using Test
using TagBot

@testset "TagBot.jl" begin
    include("test_types.jl")
    include("test_git.jl")
    include("test_changelog.jl")
    include("test_repo.jl")
    include("test_backfilling.jl")
    include("test_gitlab.jl")
    include("test_repo_mocked.jl")
end
