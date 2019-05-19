# <img src="logo.png" width="60"> Julia TagBot

[![app-img]][app-link]
[![travis-img]][travis-link]

TagBot creates tags and releases for your Julia packages when they're registered, so that your Git tags and GitHub releases are kept in sync with releases you have made on the Julia package registry.

To install the app, click the badge above (enabling for all repositories is recommended).
Afterwards, releases for all of your packages registered with [Registrator] will be handled automatically.
TagBot does not handle manual registrations.

## Usage

1. Install TagBot and enable it for your package if not already done.
2. Make a package release using [Registrator].
3. TagBot will automatically tag a GitHub release that matches the package release you just made.

### Manually Triggering a Release

If you register a package before enabling TagBot, you can still have a release created retroactively.
To trigger the release, add a comment to your merged registry PR containing the text `TagBot tag`.
This is also useful when TagBot reports an error.
To include the tag command in a comment without actually triggering a release, include `TagBot ignore` in your comment.
This should be useful for registry maintainers who want to make recommendations without modifying another repository.

### Release Notes

TagBot allows you to write your release notes in the same place that you trigger Registrator, but you don't have to if you're feeling lazy.
When release notes are provided, they are copied into both the Git tag message and the GitHub release.
If you do not write any notes, a changelog is automatically generated from closed issues and merged pull requests.
This will appear in the GitHub release, and a link to that release will appear in the Git tag message.

---

For more information on what TagBot is and isn't, please see the [announcement].

[app-img]: https://img.shields.io/badge/GitHub%20App-install-blue.svg
[app-link]: https://github.com/apps/julia-tagbot
[travis-img]: https://travis-ci.com/JuliaRegistries/TagBot.svg?branch=master
[travis-link]: https://travis-ci.com/JuliaRegistries/TagBot
[registrator]: https://juliaregistrator.github.io
[announcement]: https://discourse.julialang.org/t/ann-tagbot-creates-tags-and-releases-for-your-julia-packages-when-theyre-registered/23084
