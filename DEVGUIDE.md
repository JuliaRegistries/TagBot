# TagBot

## Release a new version

1. Merge all desired PRs onto master
2. Go to https://github.com/JuliaRegistries/TagBot/actions/workflows/publish.yml
3. Invoke with the desired major/minor/patch bump
4. Review CI on the PR created & merge to release
5. Review the tag release and edit text appropriately

## Monitoring errors in the wild

TagBot automatically files error reports here for unexpected errors. Which errors are filed there
can be adjusted based on expectations.

https://github.com/JuliaRegistries/TagBotErrorReports
