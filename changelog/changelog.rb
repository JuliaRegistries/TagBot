# Hacks because github_changelog_generator is a Git dependency.
paths = Dir.glob("**/github-changelog-generator-*/lib")
$LOAD_PATH.unshift(*paths)

require 'github_changelog_generator'
require 'json'
require 'octokit'
require 'tempfile'

$ack_regex = /\\\* \*this change log was automatically generated .*/i
$number_regex = /\[\\#(\d+)\]\(.+?\)/
$section_header_regex = /^## \[.*\]\(.*\) \(.*\)$/

def main(event:, context:)
  event['Records'].each do |r|
    body = JSON.parse(r['body'], symbolize_names: true)
    puts body

    client = Octokit::Client.new(:access_token => body[:auth])

    # If we don't have read permissions for issues, the generator will fail.
    # The GitHub App only requested these permissions recently
    # and requires confirmation from each user, so we can't guarantee anything.
    begin
      client.issues("#{body[:user]}/#{body[:repo]}")
    rescue Octokit::Forbidden
      puts 'Insufficient permissions to list issues'
      next
    end

    begin
      changelog = get_changelog(body)
      update_release(client, changelog, body) unless changelog.nil?
    rescue => e
      log(e)
      next
    end
  end
end

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

  begin
    GitHubChangelogGenerator::ChangelogGenerator.new.run
  rescue => e
    log(e, 'Changelog generator failed')
    return nil
  end

  file = begin
           File.read(path)
         rescue => e
           log(e, 'Changelog file could not be read')
           return nil
         end

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

  if start.nil?
    puts 'Start of section was not found'
    return nil
  end

  return lines[start...stop]
           .join("\n")
           .gsub($number_regex, '(#\\1)')
           .sub($ack_regex, '')
           .strip
end

def update_release(client, changelog, user:, repo:, tag:, auth:)
  releases = begin
               client.releases("#{user}/#{repo}")
             rescue => e
               log(e, 'Listing releases failed')
               return
             end

  release = releases.find { |r| r.tag_name == tag }
  if release.nil?
    puts 'Release was not found'
    return
  elsif !release.body.nil? && !release.body.empty?
    puts 'Release already has a body'
    return
  end

  begin
    client.update_release(release.url, body: changelog)
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

String.class_eval {
  def permutations
    s = self.split.map(&:capitalize).join(' ')
    hyphens = s.tr(' ', '-')
    underscores = s.tr(' ', '_')
    compressed = s.tr(' ', '')
    all = [s, hyphens, underscores, compressed]
    return [all, *all.map(&:downcase)].uniq
  end
}
