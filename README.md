# <img src="logo.png" width="60"> Julia TagBot

TagBot creates tags, releases, and changelogs for your Julia packages when they're registered.

When we talk about tags and releases, we mean *Git tags* and *GitHub releases*, and not releases in a registry that allow the Julia package manager to install your package.
TagBot does not register your package for you, see the documentation in [General](https://github.com/JuliaRegistries/General/blob/master/README.md) and [Registrator](https://github.com/JuliaRegistries/Registrator.jl/blob/master/README.md) for that.
Instead, it reacts to versions of your packages that have been registered, making TagBot a set-and-forget solution to keep your repository in sync with your package releases.
Tags and releases aren't at all necessary, but it's considered a good practice.

Other benefits of using TagBot include the ability for you and your users to browse package code at specific releases, and automatically-generated changelogs for each release that keep your users in the loop.

## Setup

Create a file at `.github/workflows/TagBot.yml` with the following contents:

```yml
name: TagBot
on:
  issue_comment:
    types:
      - created
  workflow_dispatch:
jobs:
  TagBot:
    if: github.event_name == 'workflow_dispatch' || github.actor == 'JuliaTagBot'
    runs-on: ubuntu-latest
    steps:
      - uses: JuliaRegistries/TagBot@v1
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
          ssh: ${{ secrets.DOCUMENTER_KEY }}
```

No further action is required on your part.
When you add a new release to a registry with Registrator, TagBot will create a GitHub release on your package's repository.

You may, however, want to customize the behaviour via the available configuration options.

For example, if you use GitHub Actions to build the documentation for your package, you will find that with the default TagBot configuration, your documentation build is not triggered when a new tag is created.
In this case, you will need to use [SSH Deploy Keys](#ssh-deploy-keys).

Read on for a full description of all of the available configuration options.

## Table of Contents

- Basic Configuration Options:
  - [SSH Deploy Keys](#ssh-deploy-keys)
  - [Changelogs](#changelogs)
  - [Custom Registries](#custom-registries)
- Advanced Configuration Options:
  - [Self-Hosted GitHub](#self-hosted-github)
  - [Git configuration](#git-configuration)
  - [GPG Signing](#gpg-signing)
  - [Lookback Period](#lookback-period)
  - [Personal Access Tokens (PATs)](#personal-access-tokens-pats)
  - [Pre-Release Hooks](#pre-release-hooks)
  - [Release Branch Selection](#release-branch-selection)
  - [Release Branch Management](#release-branch-management)
- [Local Usage](#local-usage)

## Basic Configuration Options

### SSH Deploy Keys

Sometimes, instead of using the default `secrets.GITHUB_TOKEN`, it is better to use an SSH deploy key.
The most notable reason is that the default token does not have permission to trigger events for other GitHub Actions, such as documentation builds for new tags.

To use an SSH deploy key:

- Create an SSH key and add it to your repository by following the instructions [here](https://developer.github.com/v3/guides/managing-deploy-keys/#setup-2).
  Make sure to give it write permissions.
- Create a repository secret by following the instructions [here](https://help.github.com/en/actions/automating-your-workflow-with-github-actions/creating-and-using-encrypted-secrets#creating-encrypted-secrets).
  Use whatever you like as the name, such as `SSH_KEY`.
  Use the private key contents as the value.
- Add the `ssh` input:

```yml
with:
  token: ${{ secrets.GITHUB_TOKEN }}
  ssh: ${{ secrets.SSH_KEY }}
```

If you already have a Base64-encoded deploy key and matching repository secret for Documenter, you can reuse it instead of creating a new one.

If your key is password-protected, you'll also need to include the password in another repository secret (not Base64-encoded):

```yml
with:
  token: ${{ secrets.GITHUB_TOKEN }}
  ssh: ${{ secrets.SSH_KEY }}
  ssh_password: ${{ secrets.SSH_PASSWORD }}
```

### Changelogs

TagBot creates a changelog for each release based on the issues that have been closed and the pull requests that have been merged.
Additionally, you can write custom release notes in the same place that you register your packages.
See [Registrator](https://github.com/JuliaRegistries/Registrator.jl/#release-notes) or [PkgDev](https://github.com/JuliaLang/PkgDev.jl) for specifics.

The changelog is completely customizable with the [Jinja](https://jinja.palletsprojects.com) templating engine.
To supply your own template, use the `changelog` input:

```yml
with:
  token: ${{ secrets.GITHUB_TOKEN }}
  changelog: |
    This is release {{ version }} of {{ package }}.
    {% if custom %}
    Here are my release notes!
    {{ custom }}
    {% endif %}
```

The data available to you looks like this:

```json
{
  "compare_url": "https://github.com/Owner/Repo/compare/previous_version...current_version (or null for first release)",
  "custom": "your custom release notes",
  "issues": [
    {
      "author": {
        "name": "Real Name",
        "url": "https://github.com/username",
        "username": "their login"
      },
      "body": "issue body",
      "labels": ["label1", "label2"],
      "closer": {"same format as": "issue author but sometimes null"},
      "number": 123,
      "title": "issue title",
      "url": "https://github.com/Owner/Repo/issues/123"
    }
  ],
  "package": "PackageName",
  "previous_release": "v1.1.2 (or null for first release)",
  "pulls": [
    {
      "author": {"same format as": "issue author"},
      "body": "pull request body",
      "labels": ["label1", "label2"],
      "merger": {"same format as": "issue author"},
      "number": 123,
      "title": "pull request title",
      "url": "https://github.com/Owner/Repo/pull/123"
    }
  ],
  "sha": "commit SHA",
  "version": "v1.2.3",
  "version_url": "https://github.com/Owner/Repo/tree/v1.2.3"
}
```

You can see the default template in [`action.yml`](action.yml).

Issues and pull requests with specified labels are not included in the changelog data.
By default, the following labels are ignored:

- changelog skip
- duplicate
- exclude from changelog
- invalid
- no changelog
- question
- wont fix

To supply your own labels, use the `changelog_ignore` input:

```yml
with:
  token: ${{ secrets.GITHUB_TOKEN }}
  changelog_ignore: ignore this label, ignore this label too
```

White-space, case, dashes, and underscores are ignored when comparing labels.

### Custom Registries

If you're using a custom registry, add the `registry` input:

```yml
with:
  token: ${{ secrets.GITHUB_TOKEN }}
  registry: MyOrg/MyRegistry
```

## Advanced Configuration Options

### Self-Hosted GitHub

If your company is running their own GitHub server, then you'll need to update the relevant GitHub URL inputs, `github` and `github_api`:

```yml
with:
  github: git.corp.com
  github_api: api.git.corp.com
```

### Git Configuration

By default, the Git tags that TagBot creates are authored by a user called `github-actions[bot]`, whose email is `41898282+github-actions[bot]@users.noreply.github.com`.
If you want to use your own Git author info, you can set the `user` and `email` inputs:

```yml
with:
  token: ${{ secrets.GITHUB_TOKEN }}
  user: My Name
  email: my.email@web.site
```

### GPG Signing

If you want to create signed tags, you can supply your own GPG private key.
Your key can be exported with `gpg --export-secret-keys --armor <ID>`, and optionally Base64-encoded.
Create the repository secret, then use the `gpg` input:

```yml
with:
  token: ${{ secrets.GITHUB_TOKEN }}
  gpg: ${{ secrets.GPG_KEY }}
```

If your key is password-protected, you'll also need to include the password in another repository secret (not Base64-encoded):

```yml
with:
  token: ${{ secrets.GITHUB_TOKEN }}
  gpg: ${{ secrets.GPG_KEY }}
  gpg_password: ${{ secrets.GPG_PASSWORD }}
```

It's also recommended to set your Git email address to one that is attached to the GPG key (see [Git Configuration](#git-configuration)).
If you fail to do so, your tags will be marked "Unverified" in the GitHub UI.

### Lookback Period

By default, TagBot checks for new releases that are at most 3 days old.
Therefore, if you only run TagBot every five days, it might miss some releases.
To fix this, you can specify a custom number of days to look back in time with the `lookback` input:

```yml
with:
  token: ${{ secrets.GITHUB_TOKEN }}
  lookback: 14
```

An extra hour is always added, so if you run TagBot every 5 days, you can safely set this input to `5`.

### Personal Access Tokens (PATs)

We highly recommend that you use an SSH deploy key instead of a personal access token (PAT).

Please keep in mind that there are security concerns with using a PAT.
For example, a PAT has access to all of your repositories.
To reduce the consequences of a secret being leaked, we recommend that you instead use an [SSH deploy key](#ssh-deploy-keys) that only has permissions for a single repository.


To use a PAT:

- Create a PAT by following the instructions [here](https://help.github.com/en/github/authenticating-to-github/creating-a-personal-access-token-for-the-command-line#creating-a-token).
  Make sure that it has the `repo` scope.
- Create a repository secret by following the instructions [here](https://help.github.com/en/actions/automating-your-workflow-with-github-actions/creating-and-using-encrypted-secrets#creating-encrypted-secrets).
  Use whatever you like as the name, such as `TAGBOT_PAT`.
  Use the new PAT as the value.
- Replace the `token` input's value with the name of your secret, like so:

```yml
with:
  token: ${{ secrets.TAGBOT_PAT }}
```

### Pre-Release Hooks

If you want to make something happen just before releases are created, you can do so with the `dispatch` input:

```yml
with:
  token: ${{ secrets.GITHUB_TOKEN }}
  dispatch: true
```

When you enable this option, a [repository dispatch event](https://developer.github.com/v3/activity/events/types/#repositorydispatchevent) is created before releases are created.
This means that you can set up your own actions that perform any necessary pre-release tasks.

The payload is an object mapping from version to commit SHA, which can contain multiple entries and looks like this:

```json
{
  "v1.2.3": "abcdef0123456789abcdef0123456789abcdef01"
}
```

These actions will have 5 minutes to run by default, but you can customize the number of minutes with the `dispatch_delay` input:

```yml
with:
  token: ${{ secrets.GITHUB_TOKEN }}
  dispatch: true
  dispatch_delay: 30
```

Avoid setting a delay longer than the interval between TagBot runs, since your dispatch event will probably be triggered multiple times and the same release will also be attempted more than once.

To use this feature, you must provide your own personal access token.
For more details, see [Personal Access Tokens (PATs)](#personal-access-tokens-pats).

### Release Branch Selection

If you use a non-standard Git workflow where your default branch is not the main development branch, you may want to set the `branch` input to the name of your preferred release branch:

```yml
with:
  token: ${{ secrets.GITHUB_TOKEN }}
  branch: release
```

The branch you set will be the first one searched for a commit to tag, and releases will be anchored to that branch when possible.

### Release Branch Management

If you're using [PkgDev](https://github.com/JuliaLang/PkgDev.jl) to release your packages, TagBot can manage the merging and deletion of the release branches that it creates.
To enable this feature, use the `branches` input:

```yml
with:
  token: ${{ secrets.GITHUB_TOKEN }}
  branches: true
```

## Local Usage

There are some scenarios in which you want to manually run TagBot.
Perhaps TagBot failed for some reason, or GitHub's service was down, or you just set up TagBot but would like to fill in tags for old releases.
The simplest way to run TagBot manually is through Docker and the `tagbot.local` module.

```sh
$ docker pull degraafc/tagbot
$ docker run --rm degraafc/tagbot python -m tagbot.local --help
Usage: __main__.py [OPTIONS]

Options:
  --repo TEXT        Repo to tag
  --version TEXT     Version to tag
  --token TEXT       GitHub API token
  --github TEXT      GitHub URL
  --github-api TEXT  GitHub API URL
  --changelog TEXT   Changelog template
  --registry TEXT    Registry to search
  --help             Show this message and exit.

$ docker run --rm degraafc/tagbot python -m tagbot.local \
    --repo Owner/Name \
    --token <TOKEN> \
    --version v1.2.3
```

Only the `repo`, `version`, and `token` options are required, and you will be prompted if you don't provide them.
For instructions on how to obtain a token, see [Personal Access Tokens (PATs)](#personal-access-tokens-pats).

You can also run the code outside of Docker, but you'll just need to install [Poetry](https://python-poetry.org) first, and ensure that you have Python 3.8.

```sh
$ git clone https://github.com/JuliaRegistries/TagBot  # Consider --branch vA.B.C
$ cd TagBot
$ poetry install
$ poetry run python -m tagbot.local --help
```
