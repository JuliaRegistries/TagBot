require 'github_changelog_generator'
require 'json'
require 'tempfile'

$number_regex = /\[\\#(\d+)\]\(.+?\)/
$ack_regex = /\\\* \*this change log was automatically generated .*/i

def main(event:, context:)
  ARGV.clear

  params = event['queryStringParameters']
  ARGV.push '--user', params['user']
  ARGV.push '--project', params['repo']
  ARGV.push '--between-tags', params['tag']
  ARGV.push '--token', params['token']

  path = Tempfile.new.path
  ARGV.push '--output', path

  # TODO: Does this work? I want to disable these extra sections.
  ARGV.push '--header-label', ''
  ARGV.push '--bug-labels', ''
  ARGV.push '--enhancement-labels', ''

  return response(400, error: 'Missing parameter(s)') unless ARGV.all?

  begin
    GitHubChangelogGenerator::ChangelogGenerator.new.run
    changelog = File.read path
    changelog.gsub! $number_regex, '(#\\1)'
    changelog.sub! $ack_regex, ''
    changelog.strip!
  rescue StandardError => e
    puts e
    return response(500, error: 'Error running changelog generator')
  end

  return response(200, changelog: changelog)
end

def response(status, changelog: nil, error: nil)
  body = { changelog: changelog, error: error }
  json = JSON.generate body
  return { statusCode: status, body: json }
end
