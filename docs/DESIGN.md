# TagBot Design

TagBot, in a nutshell, responds to events sent by GitHub and uses the information to create a GitHub release for a newly registered package.
This document attemps to explain how it does so in a robust manner.

## The Job Context

The stages of the pipeline operate on a "job context".
This is just an associative object whose data accumulates as it moves through the pipeline.

It contains these fields:

- `id (str)`: The GitHub webhook delivery ID, a unique ID for the job.
  Information that is valid for this job only can be stored with this key (for example, the current stage).
- `repo (str)`: The repository slug, e.g. `owner/name`.
- `registry (str)`: The registry's repository slug.
- `version (str)`: The version being registered, e.g. `v1.2.3`.
- `commit (str)`: The Git commit SHA being registered.
- `target (str)`: The GitHub release target, which is either the commit SHA or the default branch name.
  The branch name is used when the commit SHA is the same as that of the default branch's head commit.
  Using the branch name allows for the "n commit to branch since this release" note on the release page (see #10).
- `issue (int)`: The registry pull request number.
  While this is not a unique job ID (jobs can be triggered multiple times for one pull request), it can be used as a key for data that does not change with each job.
  For example, generated changelogs can be indexed by this key.
- `comment_id (int)`: GitHub ID of a comment made by TagBot on the registry PR.
  This is used to avoid creating many new comments.
  Instead, one comment is created, its ID is stored, and it is edited many times to append each new message.
- `changelog (str | null)`: Release notes for the new version.

## The Pipeline

A job is represented as a pipeline with multiple stages.
Each stage is a separate Lambda function, and each stage invokes its succeeding stage directly.
Some state is stored in DynamoDB.

1. **Webhook Handler**

The webhook handler receives a payload from GitHub, indicating an event.
It doesn't do any error-prone computation with it, since it receives events via an HTTP endpoint and therefore cannot retry automatically.
It performs some basic validation and forwards the payload to the next stage.

2. **Context Preparation**

In this stage, the GitHub payload is validated and parsed to a context.
The criteria for validation is:

- Event type is "merge"
- PR base branch is the registry default branch
- PR was created by Registrator
- PR body contains "Repository", "Version", and "Commit" fields
- TagBot is installed for the repository whose package is being registered
  - If TagBot is installed for the user account but not for the repository, a comment is added saying so.
  - If TagBot is not installed for the user account, nothing happens.
  
After this stage, the context contains all non-nullable fields.
A notification is sent indicating that the process has begun.

If this stage fails, the pipeline halts.

3. **Git Tag Creation**

In this stage, a Git tag is created and pushed to the repository, and the context passes through unchanged.

If this stage fails, the pipeline continues, since creating a release with the GitHub API also creates a tag.
A warning notification is sent, however.

4. **Changelog Generation**

In this stage, a changelog is generated for the new release and added to the context.

The changelog is also stored to DynamoDB, indexed by the pull request number.
This means that if the job fails further down the line, the changelog will not need to be regenerated in the case of a job retry (via a comment command).

If this stage fails, the pipeline continues, but with an empty changelog.
A warning notification is sent in this case.

5. **GitHub Release Creation**

In this stage, a GitHub release is created with the changelog that was generated in the last stage.

If this stage fails, the pipeline halts, and an error notification is sent.

### "Special" Stages

Some stages don't quite fit into the linear pipeline.

#### Notification Sending

This stage is reached numerous times throughout the pipeline.
It comments on the registry pull request with some notification, whether it be informational or an error message.

#### Failure Handler

Each stage except the webhook handler is automatically tried up to 3 times (see [here](https://docs.aws.amazon.com/lambda/latest/dg/retries-on-errors.html) for details).
If all three attemps fail, the payload is forwarded to the this stage.

How it reacts depends on the failed stage:

2. **Context Preparation**: The pipeline halts.
3. **Git Tag Creation**: The next stage (changelog generation) is invoked.
   We can continue since creating a GitHub release will also create a Git tag automatically.
4. **Changelog Generation**: The next stage is invoked.
  The changelog is left empty, so the release body will be empty.
5. **GitHub Release Creation**: The pipeline halts.

In every case, a notification is sent containing the stage and error message.

The events are delivered to the failure handler via SNS topics.
There is one topic for each stage, and so the failed stage is determined by inspecting the source topic.

## Events

TagBot only handles a few event, namely pull request merge events and issue comment events.

### Pull Request Event

All pull request events are ignored expect those that indicate that a PR has just been merged.
These merge events cause TagBot to automatically create repository releases.
They are the standard event that the context preparation stage is built around.

### Issue Comment Event

Issue comment events are fired for both issues and pull requests, but Tagbot only reacts to creation events for pull request comments.
If the comment body contains a command, it is processed.
Otherwise, it is ignored.

## Commands

Commands all begin with `TagBot`, e.g. `TagBot <cmd>`.

### `tag`

This command indicates that TagBot should run a job on this pull request.
This is usually used to retry after an error, or after some correction has been made by the user, e.g. enabling TagBot for the repository being registered.

It works by simply creating a payload that looks like a pull request event, and processing it as such.

### `ignore`

This command indicates that any other command inside the comment body should be ignored.
It allows you to write other commands in plain text without triggering TagBot, e.g. if you're instructing someone on how to use commands.

You can hide the ignore command by using comment syntax: `<!-- TagBot ignore -->`.
