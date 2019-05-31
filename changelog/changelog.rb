# Hacks because github_changelog_generator is a Git dependency.
paths = Dir.glob("**/github-changelog-generator-*/lib")
$LOAD_PATH.unshift(*paths)

require 'aws-sdk-sns'
require 'github_changelog_generator'
require 'json'
require 'octokit'
require 'tempfile'

$ack_regex = /\\\* \*this changelog was automatically generated .*/i
$changelog_regex = /^\[full changelog\]\((.*)\/compare\/(.*)\.\.\.(.*)\)$/i
$number_regex = /\[\\#(\d+)\]\(.+?\)/
$section_header_regex = /^## \[.*\]\(.*\) \(.*\)$/
$wip_msg = ENV['CHANGELOG_WIP_MESSAGE']

def main(event:, **_args)
  event['Records'].each do |rec|
    params = JSON.parse(rec['Sns']['body'], symbolize_names: true)
    log('Starting', params)

    case params[:command]
    when nil then
      log('Missing command', params)
    when 'gen-changelog' then
      changelog = gen_changelog(params)
      notify('github', command: 'post-changelog', changelog: changelog)
    else
      log('Unknown command', params)
    end
  end
end

# Generates a changelog for a single release.
def gen_changelog(params)
  user, repo, tag, auth = %i[user repo tag auth].map { |k| params[k] }
  unless [user, repo, tag, auth].all?
    log('Missing parameters', params)
    return
  end

  client = Octokit::Client.new(access_token: auth)
  slug = "#{user}/#{repo}"

  # If we don't have read permissions for issues, the generator will fail.
  # The GitHub App only requested these permissions recently
  # and requires confirmation from each user, so we can't guarantee anything.
  begin
    client.issues(slug)
  rescue Octokit::Forbidden
    log('Insufficient permissions to list issues', params)
    return
  rescue Octokit::Unauthorized
    log('Unauthorized (this token is probably expired)', params)
    return
  end

  releases = client.releases(slug)
  release = releases.find { |r| r.tag_name == tag }

  # It could be the case that the previous function has not yet finished
  # and the release will exist soon, so we can retry later.
  raise 'Release was not found' if release.nil?

  unless release.body.nil? || release.body.empty? || release.body == $wip_msg
    # Don't overwrite an existing release that has a custom body.
    log('Release already has a body', params)
    return
  end

  changelog = run_generator(params)
  find_section(changelog, tag)
end

# Generate a changelog for a repository tag.
def run_generator(user:, repo:, auth:, **_args)
  ARGV.clear

  ARGV.push('--user', user)
  ARGV.push('--project', repo)
  ARGV.push('--token', auth)

  path = Tempfile.new.path
  ARGV.push('--output', path)

  excludes = [
    'changelog skip',
    'duplicate',
    'exclude from changelog',
    'invalid',
    'no changelog',
    'question',
    'wont fix',
  ].map(&:permutations).flatten.join(',')
  ARGV.push('--exclude-labels', excludes)

  ARGV.push('--header-label', '')
  ARGV.push('--breaking-labels', '')
  ARGV.push('--bug-labels', '')
  ARGV.push('--deprecated-labels', '')
  ARGV.push('--enhancement-labels', '')
  ARGV.push('--removed-labels', '')
  ARGV.push('--security-labels', '')
  ARGV.push('--summary-labels', '')

  log('Running generator', params)
  GitHubChangelogGenerator::ChangelogGenerator.new.run
  log('Generator finished', params)

  File.read(path)
end

# Grab just the section for one tag.
def find_section(changelog, tag)
  # The generator doesn't support generating only one section.
  # We find the line numbers of the section start and stop.
  lines = changelog.split("\n")
  start = nil
  stop = lines.length
  in_section = false
  lines.each_with_index do |line, i|
    if $section_header_regex.match?(line)
      if in_section
        stop = i
        break
      elsif /\[#{tag}\]/.match?(line)
        start = i
        in_section = true
      end
    end
  end

  raise 'Start of section was not found' if start.nil?

  # Join the slice together and process the text a bit.
  lines[start...stop]
    .join("\n")
    .gsub($number_regex, '(#\1)')
    .sub($ack_regex, '')
    .sub($changelog_regex, '[Diff since \2](\1/compare/\2...\3)')
    .strip
end

# Send a message to an SNS topic.
def notify(topic, body)
  topic_arn = ENV['SNS_PREFIX'] + topic
  message = body.to_json
  log('Sending message to topic', length: message.length, topic: topic)
  Aws::SNS::Client.new.publish(topic_arn: topic_arn, message: message)
  log('Sent message to topic', topic: topic)
end

# Log a message with some metadata.
def log(msg, meta = {})
  puts "#{msg} --- #{meta}"
end

String.class_eval {
  # Return a bunch mostly-equivalent verions of a label.
  def permutations
    s = split.map(&:capitalize).join(' ')
    hyphens = s.tr(' ', '-')
    underscores = s.tr(' ', '_')
    compressed = s.tr(' ', '')
    all = [s, hyphens, underscores, compressed]
    [*all, *all.map(&:downcase)].uniq
  end
}
