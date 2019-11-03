# <img src="logo.png" width="60"> Julia TagBot

[![Build Status](https://travis-ci.com/JuliaRegistries/TagBot.svg?branch=master)](https://travis-ci.com/JuliaRegistries/TagBot)

## Setup

Create a file at `.github/workflows/TagBot.yml` with the following contents:

```yml
on:
  schedule:
    - cron: 0 * * * *
jobs:
  TagBot:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v1
      - uses: JuliaRegistries/TagBot@latest
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
```

No further action is required.


### Release Notes

TODO

### Custom Registries

If you're using a custom registry, add the `registry` input:

```yml
with:
  token: ${{ secrets.GITHUB_TOKEN }}
  registry: https://github.com/MyOrg/MyRegistry
```

If your registry is private, you'll need to include authentication in the URL.

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
