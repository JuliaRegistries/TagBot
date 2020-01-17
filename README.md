# <img src="logo.png" width="60"> Julia TagBot

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

No further action is required.

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
  Use whatever you like as the name, such as `DEPLOY_KEY`.
  Use the private key contents as the value.
- Add the `ssh` input:

```yml
with:
  token: ${{ secrets.GITHUB_TOKEN }}
  ssh: ${{ secrets.DEPLOY_KEY }}
```

If you already have a deploy key and matching repository secret for Documenter, you can reuse it instead of creating a new one.

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
It also allows you to exclude issues and pull requests from the changelog by adding the `changelog-skip` label to them.

### Custom Registries

If you're using a custom registry, add the `registry` input:

```yml
with:
  token: ${{ secrets.GITHUB_TOKEN }}
  registry: MyOrg/MyRegistry
```

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
These actions will have 5 minutes to run.

The payload is an object mapping from version to commit SHA, which can contain multiple entries and looks like this:

```json
{
  "v1.2.3": "abcdef0123456789abcdef0123456789abcdef01"
}
```

To use this feature, you must provide your own personal access token.
For more details, see [Personal Accesss Tokens](#personal-access-tokens).
