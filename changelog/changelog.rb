# Hacks because github_changelog_generator is a Git dependency.
paths = Dir.glob("**/github-changelog-generator-*/lib")
$LOAD_PATH.unshift(*paths)

require 'github_changelog_generator'
require 'json'
require 'octokit'
require 'tempfile'

$ack_regex = /\\\* \*this changelog was automatically generated .*/i
$number_regex = /\[\\#(\d+)\]\(.+?\)/
$section_header_regex = /^## \[.*\]\(.*\) \(.*\)$/

def main(event:, context:)
  # Let the other Lambda function finish.
  # The only things left to do are API calls, so it should be quick.
  sleep 5

  event['Records'].each do |r|
    params = JSON.parse(r['body'], symbolize_names: true)
    puts params

    user, repo, tag, auth = %i[user repo tag auth].map { |k| params[k] }
    unless [user, repo, tag, auth].all?
      puts 'Missing parameters'
      next
    end

    client = Octokit::Client.new(:access_token => auth)
    slug = "#{user}/#{repo}"

    # If we don't have read permissions for issues, the generator will fail.
    # The GitHub App only requested these permissions recently
    # and requires confirmation from each user, so we can't guarantee anything.
    begin
      client.issues(slug)
    rescue Octokit::Forbidden
      puts 'Insufficient permissions to list issues'
      next
    rescue Octokit::Unauthorized
      puts 'Unauthorized (this token is probably expired)'
      next
    end

    releases = client.releases(slug)
    release = releases.find { |r| r.tag_name == tag }
    if release.nil?
      # It could be the case that the previous function has not yet finished
      # and the release will exist soon, so we can retry later.
      raise 'Release was not found'
    elsif !release.body.nil? && !release.body.empty?
      # Don't overwrite an existing release that has a custom body.
      puts 'Release already has a body'
      next
    end

    changelog = get_changelog(params)
    client.edit_release(release.url, body: changelog)

    puts 'Updated release'
  end
end

# Generate a changelog for a repository tag.
def get_changelog(user:, repo:, tag:, auth:)
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

  GitHubChangelogGenerator::ChangelogGenerator.new.run
  file = File.read(path)

  return get_section(file, tag)
end

# Grab just the section for one tag.
def find_section(file, tag)
  # The generator doesn't support generating only one section.
  # We find the line numbers of the section start and stop.
  lines = file.split("\n")
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
  return lines[start...stop]
           .join("\n")
           .gsub($number_regex, '(#\\1)')
           .sub($ack_regex, '')
           .strip
end

String.class_eval {
  # Return a bunch mostly-equivalent verions of a label.
  def permutations
    s = self.split.map(&:capitalize).join(' ')
    hyphens = s.tr(' ', '-')
    underscores = s.tr(' ', '_')
    compressed = s.tr(' ', '')
    all = [s, hyphens, underscores, compressed]
    return [all, *all.map(&:downcase)].uniq
  end
}
