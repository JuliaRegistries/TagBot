# Hacks because github_changelog_generator is a Git dependency.
paths = Dir.glob('**/github-changelog-generator-*/lib')
$LOAD_PATH.unshift(*paths)

require 'date'
require 'json'
require 'tempfile'

require 'aws-sdk-dynamodb'
require 'aws-sdk-lambda'
require 'github_changelog_generator'
require 'octokit'

# Generates changelogs.
class Handler
  @lambda = Aws::Lambda::Client.new
  @dynamodb = Aws::DynamoDB::Client.new

  @lambda_function_prefix = ENV['LAMBDA_FUNCTION_PREFIX']
  @dynamodb_table_name = ENV['DYNAMODB_TABLE_NAME']

  @stage_notify = 'notify'
  @stage_release = 'release'

  @re_ack = /\\\* \*this changelog was automatically generated .*/i
  @re_compare = %r{^\[full changelog\]\((.*)\/compare\/(.*)\.\.\.(.*)\)$}i
  @re_number = /\[\\#(\d+)\]\(.+?\)/
  @re_section_header = /^## \[.*\]\(.*\) \(.*\)$/

  def initialize(ctx)
    @ctx = ctx
    @auth = @ctx[:auth]
    @issue = ctx[:issue]
    @repo = @ctx[:repo]
    @version = @ctx[:version]
    @github = Octokit::Client.new(access_token: @auth)
  end

  def do
    changelog = from_ddb
    if changelog.nil?
      begin
        @ctx[:changelog] = gen_changelog
      rescue Unrecoverable => e
        @ctx[:notification] = %(
        I tried to generate a changelog but failed:
        ```
        #{e}
        ```
        You might want to manually update the release body.
        ).strip
        invoke(@stage_notify)
      else
        put_ddb(changelog)
      end
    else
      @ctx[:changelog] = changelog
    end
    invoke(@stage_release)
  end

  # Get a changelog from DynamoDB.
  def from_ddb
    resp = @dynamodb.get_item(
      table_name: @dynamodb_table_name,
      key: { id: @issue },
      attributes_to_get: ['changelog']
    )
    if resp.item.nil?
      nil
    else
      resp.item['changelog']
    end
  end

  # Store a changelog to DynamoDB.
  def put_ddb(changelog)
    ttl = (DateTime.now + 14).to_time.to_i
    @dynamodb.put_item(
      table_name: @dynamodb_table_name,
      item: { id: @issue, changelog: changelog, ttl: ttl }
    )
  end

  # Invoke a Lambda function.
  def invoke(function)
    @lambda.invoke(
      function_name: @lambda_function_prefix + function,
      payload: @ctx.to_json,
      invocation_type: 'Event'
    )
  end

  # Generate a changelog.
  def gen_changelog
    check_auth
    raw = run_generator
    section = find_section(raw)
    format_section(section)
  end

  # Check whether or not th GitHub client is authenticated.
  def check_auth
    @github.issues(@repo)
  rescue Octokit::Forbidden
    raise Unrecoverable, 'Insufficient permissions to list issues'
  rescue Octokit::Unauthorized
    raise Unrecoverable, 'Unauthorized (token is invalid or expired)'
  end

  # Run the generator CLI.
  def run_generator
    ARGV.clear

    user, project = repo.split('/')
    ARGV.push('--user', user)
    ARGV.push('--project', project)
    ARGV.push('--token', @auth)

    path = Tempfile.new.path
    ARGV.push('--output', path)

    ARGV.push('--future-release', version) unless tag_exists?

    excludes = [
      'changelog skip',
      'duplicate',
      'exclude from changelog',
      'invalid',
      'no changelog',
      'question',
      'wont fix'
    ].map(&:permutations).flatten.join(',')
    ARGV.push('--exclude-labels', excludes)

    GitHubChangelogGenerator::ChangelogGenerator.new.run
    File.read(path)
  end

  # Check whether or not a tag exists.
  def tag_exists?
    @github.ref(@repo, "tags/#{@version}")
    true
  rescue Octokit::NotFound
    false
  end

  # Extract the changelog section for the version we care about.
  def find_section(changelog)
    lines = changelog.split("\n")
    start = nil
    stop = lines.length
    in_section = false

    lines.each_with_index do |line, i|
      if @re_section_header.match?(line)
        if in_section
          stop = i
          break
        elsif /\[#{@version}\]/.match?(line)
          start = i
          in_section = true
        end
      end
    end

    raise Unrecoverable, 'Section start for release was not found' if start.nil?

    lines[start...stop].join("\n")
  end

  # Format the changelog section.
  def format_section(section)
    section
      .gsub(@re_number, '(#\1)')
      .sub(@re_ack, '')
      .sub(@re_compare, '[Diff since \2](\1/compare/\2...\3)')
      .strip
  end
end

# An error that cannot be fixed by retrying.
class Unrecoverable < StandardError; end

def handler(event:, **_args)
  Handler.new(event.symbolize).do
end

class String
  # Return a bunch of mostly-equivalent verions of a label.
  def permutations
    s = split.map(&:capitalize).join(' ')
    hyphens = s.tr(' ', '-')
    underscores = s.tr(' ', '_')
    compressed = s.tr(' ', '')
    all = [s, hyphens, underscores, compressed]
    [*all, *all.map(&:downcase)].uniq
  end
end

class Hash
  # Convert keys to symbols.
  def symbolize
    map { |k, v| [k.to_sym, v] }.to_h
  end
end
