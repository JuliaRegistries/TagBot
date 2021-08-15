using Test

function check_readme(repository_root::AbstractString)
    readme_path = joinpath(repository_root, "README.md")
    example_path = joinpath(repository_root, "example.yml")
    readme_contents = read(readme_path, String)
    example_contents = string(
        "```yml\n",
        read(example_path, String),
        "```\n",
    )
    @testset "Check README" begin
        @test occursin(example_contents, readme_contents)
    end
    return nothing
end
