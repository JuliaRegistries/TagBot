# <img src="https://raw.githubusercontent.com/christopher-dG/tag-bot/master/logo.png" width="60"> Julia TagBot

[![app-img]][app-link]
[![travis-img]][travis-link]

TagBot creates tags and releases for your Julia packages when they're registered.
So your releases/tags on GitHub are kept in sync with what releases you have on julia package registry.

To install the app, click the badge above (enabling for all repositories is recommended).
Afterwards, releases for all of your packages registered with [Registrator] will be handled automatically.
TagBot does not handle manual registrations

### Usage:

 1. Install Tagbot and enable it for your package (if not already done before)
 2. Make a package release using [Registrator]
 3. TagBot will automatically tag a GitHub release, that matches the package release you just made.


For more information on what TagBot is and isn't, please see the [announcement].

[app-img]: https://img.shields.io/badge/GitHub%20App-install-blue.svg
[app-link]: https://github.com/apps/julia-tagbot
[travis-img]: https://travis-ci.com/christopher-dG/tag-bot.svg?branch=master
[travis-link]: https://travis-ci.com/christopher-dG/tag-bot
[registrator]: https://juliaregistrator.github.io
[announcement]: https://discourse.julialang.org/t/ann-tagbot-creates-tags-and-releases-for-your-julia-packages-when-theyre-registered/23084
