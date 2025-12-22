using Test
using TagBot
using TagBot: SemVer, Abort, InvalidProject

@testset "Types" begin
    @testset "SemVer" begin
        @testset "Basic parsing" begin
            v = SemVer("1.2.3")
            @test v.major == 1
            @test v.minor == 2
            @test v.patch == 3
            @test v.prerelease === nothing
            @test v.build === nothing
        end

        @testset "With leading v" begin
            v = SemVer("v1.2.3")
            @test v.major == 1
            @test v.minor == 2
            @test v.patch == 3
        end

        @testset "With prerelease" begin
            v = SemVer("1.2.3-alpha.1")
            @test v.major == 1
            @test v.minor == 2
            @test v.patch == 3
            @test v.prerelease == "alpha.1"
            @test v.build === nothing
        end

        @testset "With build metadata" begin
            v = SemVer("1.2.3+build.123")
            @test v.major == 1
            @test v.minor == 2
            @test v.patch == 3
            @test v.prerelease === nothing
            @test v.build == "build.123"
        end

        @testset "Full version" begin
            v = SemVer("1.2.3-beta.2+build.456")
            @test v.major == 1
            @test v.minor == 2
            @test v.patch == 3
            @test v.prerelease == "beta.2"
            @test v.build == "build.456"
        end

        @testset "Comparison" begin
            @test SemVer("1.0.0") < SemVer("2.0.0")
            @test SemVer("1.0.0") < SemVer("1.1.0")
            @test SemVer("1.0.0") < SemVer("1.0.1")
            @test SemVer("1.0.0-alpha") < SemVer("1.0.0")
            @test SemVer("1.0.0-alpha") < SemVer("1.0.0-beta")
            @test SemVer("1.0.0") == SemVer("1.0.0")
            @test !(SemVer("2.0.0") < SemVer("1.0.0"))
        end

        @testset "String conversion" begin
            @test string(SemVer("1.2.3")) == "1.2.3"
            @test string(SemVer("1.2.3-alpha")) == "1.2.3-alpha"
            @test string(SemVer("1.2.3+build")) == "1.2.3+build"
        end

        @testset "Invalid version" begin
            @test_throws ArgumentError SemVer("invalid")
            @test_throws ArgumentError SemVer("1")
        end
    end

    @testset "Exceptions" begin
        @testset "Abort" begin
            e = Abort("test message")
            @test e.message == "test message"
            @test sprint(showerror, e) == "Abort: test message"
        end

        @testset "InvalidProject" begin
            e = InvalidProject("missing field")
            @test e.message == "missing field"
            @test sprint(showerror, e) == "InvalidProject: missing field"
        end
    end

    @testset "Utility functions" begin
        # These functions are internal, not exported
    end
end
