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
      - uses: actions/checkout@v1
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

### Signed Tags

If you want your tags to be signed with GPG, you must provide your own key.
First, export your private key with `gpg --export-secret-keys --armor <key-id>`.
Then, use the output to create a new repository secret called `GPG_KEY` as instructed [here](https://help.github.com/en/github/automating-your-workflow-with-github-actions/virtual-environments-for-github-actions#creating-and-using-secrets-encrypted-variables).
Finally, add the `gpg-key` input:

```yml
with:
  token: ${{ secrets.GITHUB_TOKEN }}
  gpg-key: ${{ secrets.GPG_KEY }}
```

The key must not be protected by a password.
