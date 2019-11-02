# <img src="logo.png" width="60"> Julia TagBot

[![travis-img]][travis-link]

## Setup

Create a file at `.github/workflows/TagBot.yml` with the following contents:

```yml
on:
  issue_comment:
    types: created
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

[travis-img]: https://travis-ci.com/JuliaRegistries/TagBot.svg?branch=master
[travis-link]: https://travis-ci.com/JuliaRegistries/TagBot
