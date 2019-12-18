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


### Release Notes

TagBot allows you to write your release notes in the same place that you trigger Registrator (see the [Registrator](https://github.com/JuliaRegistries/Registrator.jl) README for specifics), but you don't have to if you're feeling lazy.
When release notes are provided, they are copied into the GitHub release.
If you do not write any notes, a changelog is automatically generated from closed issues and merged pull requests.

When using the automatic changelog, you can ensure that certain issues or pull requests are not included.
These might include usage questions or typo fixes that aren't worth mentioning.
To exclude an issue or PR, add a label to it with one of the following values:

- `changelog skip`
- `duplicate`
- `exclude from changelog`
- `invalid`
- `no changelog`
- `question`
- `wont fix`

You can spell these in a few different ways.
For example, `no changelog` could be `nochangelog`, `no-changelog`, `no_changelog`, `No Changelog`, `NoChangelog`, `No-Changelog`, or `No_Changelog`.

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

To use this feature, you must provide your own personal access token instead of the default `secrets.GITHUB_TOKEN`, because that token does not have permission to trigger events.
