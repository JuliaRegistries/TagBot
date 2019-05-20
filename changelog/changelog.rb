# Hacks because github_changelog_generator is a Git dependency.
paths = Dir.glob "**/github-changelog-generator-*/lib"
$LOAD_PATH.unshift *paths

require 'github_changelog_generator'
require 'json'
require 'octokit'
require 'tempfile'

$ack_regex = /\\\* \*this change log was automatically generated .*/i
$number_regex = /\[\\#(\d+)\]\(.+?\)/
$section_header_regex = /^## \[.*\]\(.*\) \(.*\)$/

def main(event:, context:)
  event['Records'].each do |r|
    body = JSON.parse r['body'], symbolize_names: true
    puts body

    begin
      changelog = get_changelog body
      update_release changelog, body unless changelog.nil?
    rescue => e
      log(e)
    end
  end
end

def get_changelog(user:, repo:, tag:, auth:)
  ARGV.clear

  ARGV.push '--user', user
  ARGV.push '--project', repo
  ARGV.push '--token', auth

  path = Tempfile.new.path
  ARGV.push '--output', path

  ARGV.push '--header-label', ''
  ARGV.push '--breaking-labels', ''
  ARGV.push '--bug-labels', ''
  ARGV.push '--deprecated-labels', ''
  ARGV.push '--enhancement-labels', ''
  ARGV.push '--removed-labels', ''
  ARGV.push '--security-labels', ''
  ARGV.push '--summary-labels', ''

  begin
    GitHubChangelogGenerator::ChangelogGenerator.new.run
  rescue => e
    log(e, 'Changelog generator failed')
    return nil
  end

  begin
    file = File.read path
  rescue => e
    log(e, 'Changelog file could not be read')
    return nil
  end

  lines = file.split "\n"
  start = nil
  stop = lines.length
  in_section = false
  lines.each_with_index do |line, i|
    if $section_header_regex.match? line
      if in_section
        stop = i
        break
      elsif /\[#{tag}\]/.match? line
        start = i
        in_section = true
      end
    end
  end

  if start.nil?
    puts 'Start of section was not found'
    return nil
  end

  changelog = lines[start...stop].join "\n"
  changelog.gsub! $number_regex, '(#\\1)'
  changelog.sub! $ack_regex, ''
  changelog.strip!

  return changelog
end

def update_release(changelog, user:, repo:, tag:, auth:)
  client = Octokit::Client.new(:access_token => auth)

  begin
    releases = client.releases "#{user}/#{repo}"
  rescue => e
    log(e, 'Listing releases failed')
    return
  end

  release = releases.find { |r| r.tag_name == tag }
  if release.nil?
    puts 'Release was not found'
    return
  elsif !release.body.empty?
    puts 'Release already has a body'
    return
  end

  begin
    client.update_release release.url, { body: changelog }
  rescue => e
    log(e, 'Updating release failed')
    return
  end

  puts 'Updated release'
end

def log(ex, msg = nil)
  puts msg unless msg.nil?
  puts ex
  puts ex.backtrace
end
