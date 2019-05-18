require 'github_changelog_generator'
require 'json'
require 'tempfile'

def main(event:)
  resp = { statusCode: 200, body: { changelog: nil, error: nil } }

  # This is where the generated changelog will go.
  path = Tempfile.new.path

  ARGV.clear
  ARGV.push '-o', path
  # TODO: Set arguments from the query string parameters.

  begin
    GitHubChangelogGenerator::ChangelogGenerator.new.run
    resp[:body][:changelog] = File.read path
  rescue StandardError => e
    puts e
    resp[:statusCode] = 500
    resp[:body][:error] = "Error running changelog generator"
  end

  return JSON.generate resp
end
