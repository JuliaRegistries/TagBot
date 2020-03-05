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
  schedule:
    - cron: 0 * * * *
jobs:
  TagBot:
    runs-on: ubuntu-latest
    steps:
      - uses: JuliaRegistries/TagBot@v1
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
```

No further action is required on your part.
When you add a new release to a registry with Registrator, TagBot will create a GitHub release on your package's repository.

You may, however, want to customize the behaviour via the available configuration options:

- [Personal Access Tokens](#personal-access-tokens)
- [SSH Deploy Keys](#ssh-deploy-keys)
- [Changelogs](#changelogs)
- [GPG Signing](#gpg-signing)
- [Custom Registries](#custom-registries)
- [Lookback Period](#lookback-period)
- [Release Branch Management](#release-branch-management)
- [Pre-Release Hooks](#pre-release-hooks)

### Personal Access Tokens

It's sometimes better to use a GitHub personal access token instead of the default `secrets.GITHUB_TOKEN`.
The most notable reason is that the default token does not have permission to trigger events for other GitHub Actions, such as documentation builds for new tags.
To use a personal access token:

- Create a token by following the instructions [here](https://help.github.com/en/github/authenticating-to-github/creating-a-personal-access-token-for-the-command-line#creating-a-token).
- Create a repository secret by following the instructions [here](https://help.github.com/en/actions/automating-your-workflow-with-github-actions/creating-and-using-encrypted-secrets#creating-encrypted-secrets).
  Use whatever you like as the name, such as `TAGBOT_PAT`.
  Use the new personal access token as the value.
- Replace the `token` input's value with the name of your secret, like so:

```yml
with:
  token: ${{ secrets.TAGBOT_PAT }}
```

### SSH Deploy Keys

Using personal access tokens works around the default token's limitations, but they have access to all of your repositories.
To reduce the consequences of a secret being leaked, you can instead use an SSH deploy key that only has permissions for a single repository.
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
        "username" "their login"
      },
      "body": "issue body",
      "labels": ["label1", "label2"],
      "merger": {"same format as": "issue author"},
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

### Custom Registries

If you're using a custom registry, add the `registry` input:

```yml
with:
  token: ${{ secrets.GITHUB_TOKEN }}
  registry: MyOrg/MyRegistry
```

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

### Release Branch Management

If you're using [PkgDev](https://github.com/JuliaLang/PkgDev.jl) to release your packages, TagBot can manage the merging and deletion of the release branches that it creates.
To enable this feature, use the `branches` input:

```yml
with:
  token: ${{ secrets.GITHUB_TOKEN }}
  branches: true
```

### Pre-Release Hooks

If you want to make something happen just before releases are created, for example creating annotated, GPG-signed tags, you can do so with the `dispatch` input:

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
For more details, see [Personal Access Tokens](#personal-access-tokens).
