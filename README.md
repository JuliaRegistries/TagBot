# <img src="logo.png" width="60"> Julia TagBot

[![Build Status](https://travis-ci.com/JuliaRegistries/TagBot.svg?branch=master)](https://travis-ci.com/JuliaRegistries/TagBot)

[![travis-img]][travis-link]

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

### Custom Registries

If you're using a custom registry, add the following input:

```yml
with:
  token: ${{ secrets.GITHUB_TOKEN }}
  registry: https://github.com/MyOrg/MyRegistry
```

If your registry is private, you'll need to include authentication in the URL.
