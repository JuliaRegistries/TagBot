using Test
using Dates
using TagBot: Changelog, slug

@testset "Changelog" begin
    @testset "slug generation" begin
        @test slug("DUPLICATE") == "duplicate"
        @test slug("Won't Fix") == "wontfix"
        @test slug("Some_Label-Name") == "somelabelname"
        @test slug("changelog skip") == "changelogskip"
        @test slug("feature-request") == "featurerequest"
    end

    @testset "Custom release notes parsing - new format" begin
        # Test new format with fenced code block
        body = """
        This PR registers Package v1.0.0.
        
        <!-- BEGIN RELEASE NOTES -->
        `````
        ## What's New
        - Feature A
        - Feature B
        `````
        <!-- END RELEASE NOTES -->
        
        Other content.
        """
        
        m = match(r"(?s)<!-- BEGIN RELEASE NOTES -->\n`````(.*)`````\n<!-- END RELEASE NOTES -->"s, body)
        @test m !== nothing
        @test occursin("What's New", m.captures[1])
        @test occursin("Feature A", m.captures[1])
    end

    @testset "Custom release notes parsing - old format" begin
        # Test old format with blockquote
        body = """
        This PR registers Package v1.0.0.
        
        <!-- BEGIN RELEASE NOTES -->
        > ## What's New
        > - Feature A
        > - Feature B
        <!-- END RELEASE NOTES -->
        
        Other content.
        """
        
        m = match(r"(?s)<!-- BEGIN RELEASE NOTES -->(.*)<!-- END RELEASE NOTES -->"s, body)
        @test m !== nothing
        # Remove '> ' at the beginning of each line
        lines = split(m.captures[1], '\n')
        notes = strip(join((startswith(l, "> ") ? l[3:end] : l for l in lines), '\n'))
        @test occursin("What's New", notes)
        @test occursin("Feature A", notes)
    end

    @testset "Custom release notes missing" begin
        body = """
        This PR registers Package v1.0.0.
        No special release notes.
        """
        
        begin_marker = "<!-- BEGIN RELEASE NOTES -->"
        start_idx = findfirst(begin_marker, body)
        
        @test start_idx === nothing
    end

    @testset "Empty custom release notes" begin
        body = """
        <!-- BEGIN RELEASE NOTES -->
        `````
        `````
        <!-- END RELEASE NOTES -->
        """
        
        m = match(r"(?s)<!-- BEGIN RELEASE NOTES -->\n`````(.*)`````\n<!-- END RELEASE NOTES -->"s, body)
        @test m !== nothing
        @test strip(m.captures[1]) == ""
    end
end
