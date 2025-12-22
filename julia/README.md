# TagBot.jl

Julia port of [TagBot](https://github.com/JuliaRegistries/TagBot) - automatically creates Git tags and GitHub releases for Julia packages when they are registered.

## Overview

This is a 1:1 port of the Python TagBot to Julia, providing:

- **Feature parity** with the original Python implementation
- **Fast startup** using PrecompileTools
- **Docker deployment** with precompiled package

## Usage

### As a GitHub Action

```yaml
name: TagBot
on:
  issue_comment:
    types:
      - created
  workflow_dispatch:
    inputs:
      lookback:
        default: "3"

jobs:
  TagBot:
    if: github.event_name == 'workflow_dispatch' || github.actor == 'JuliaTagBot'
    runs-on: ubuntu-latest
    steps:
      - uses: JuliaRegistries/TagBot@v1
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
          # See action.yml for all available inputs
```

### Local Development

```bash
# Install dependencies
julia --color=yes --project=. -e 'using Pkg; Pkg.instantiate()'

# Run tests
julia --color=yes --project=. -e 'using Pkg; Pkg.test()'

# Or use the helper script
./bin/test.sh
```

### Docker

```bash
# Build the image
./bin/build-docker.sh 1.23.4

# Run manually
docker run -e GITHUB_TOKEN=xxx ghcr.io/juliaregistries/tagbot-julia:1.23.4
```

## Features

- Automatic tag and release creation on package registration
- Changelog generation from closed issues and merged PRs
- Custom changelog templates (Mustache syntax)
- SSH deploy key support for pushing tags
- GPG signing of tags
- GitLab support
- Subpackage/monorepo support
- Release branches support
- Repository dispatch events

## Environment Variables

| Variable | Description |
|----------|-------------|
| `GITHUB_TOKEN` | GitHub API token (required) |
| `GITHUB_REPOSITORY` | Repository in `owner/repo` format |
| `GITHUB_EVENT_PATH` | Path to event JSON |
| `TAGBOT_MAX_PRS_TO_CHECK` | Maximum registry PRs to check (default: 300) |

## Development

See [JULIA_PORT_GUIDE.md](../docs/JULIA_PORT_GUIDE.md) for detailed porting notes and architecture documentation.

## License

MIT - same as the original TagBot.
