# TagBot Deploy Guide

Deploying TagBot is not hard, but not trivial either.
This guide will walk you through the setup process step by step.

## Prerequisites

This guide assumes that you are running on a Unix-like operating system (MacOS, Linux, etc.).
You should have access to a [GitHub](https://github.com) account, and an [AWS](https://aws.amazon.com) account with credentials already configured.

## Creating a GitHub App

TagBot is a [GitHub App](https://developer.github.com/apps), so go [here](https://github.com/settings/apps/new) to create one.
Leave everything blank except:

- Use whatever you like as "GitHub App Name".
- Use "https://github.com/JuliaRegistries/TagBot" for "Homepage URL".
- Use "http://example.com" as "Webhook URL".
- Generate and save a secure secret, and use it for "Webhook secret".
- Set "Read & write" on "Repository contents" and "Pull requests" in the "Permissions" section.
- Select "Any account" for "Where can this GitHub App be installed?".

On the next page, take note of your App ID, and generate a private key.
Assuming that you have the TagBot repository cloned at `$ROOT`, save the private key to `$ROOT/tag-bot.pem`.

## Creating a GPG key

TagBot uses GPG to sign the tags it creates.

Before generating the key, you need to decide whether to use our own GitHub account for tagging, or a dedicated account.
If you want to use a dedicated account, create it now.

AWS Lambda runs a very old version of GnuPG, so we need to create our keyring with an equally old version.
The easiest way to do this is with [Docker](https://docker.com).
If you do not already have Docker installed, install it with the instructions [here](https://docs.docker.com/install).

Then, start a container with a mounted directory like so:

```sh
# $ROOT here is the same as before, i.e. the root of the TagBot repository.
$ mkdir $ROOT/gnupg
$ docker run -it --rm --mount type=bind,source=$ROOT/gnupg,destination=/root/.gnupg amazonlinux
```

This should get you into a running Amazon Linux container.
To generate a key, run this command:

```sh
$ gpg --gen-key
```

Follow the prompts, accepting the default values when you can.

- For "Real name", enter the name of your tagger account.
- For "Email address", enter the email address of your tagger.
- Leave "Comment" blank.
- Proceed without a password (yes, this is not ideal).

Once the key is created, export the public key with the following command:

```sh
$ gpg --export --armor
```

Use the output to add the key to your tagger's GitHub account according to the instructions [here](https://help.github.com/en/articles/adding-a-new-gpg-key-to-your-github-account).
Now you can exit the Docker container.
Outside of the container, the generated GPG data can be found at `$ROOT/gnupg`.

## Building the API

Once all these steps are complete, `$ROOT` should contain a file called `tag-bot.pem` and a directory called `gnupg`.
Run `build.sh` from `$ROOT` to build the API.
You will need the Go compiler installed, see [here](https://golang.org/doc/install) for instructions.

## Setting the Environment

TagBot relies on some environment variables as configuration.
The following variables must be set:

- `GITHUB_APP_ID`: Your GitHub App's ID.
- `GITHUB_WEBHOOK_SECRET`: The secret key that you generated.
- `GITHUB_CONTACT_USER`: The username of a GitHub user to ping when errors occur.
- `REGISTRY_BRANCH`:  The main branch of the target registry (usually "master").
- `REGISTRATOR_USERNAME`: The username of the user creating pull requests via [Registrator.jl](https://github.com/JuliaRegistries/Registrator.jl).
- `GIT_TAGGER_NAME`: The name you used when creating the GPG key.
- `GIT_TAGGER_EMAIL`: The email you used when creating the GPG key.

## Deploying the API

TagBot is deployed to [AWS Lambda](https://aws.amazon.com/lambda/) using the [Serverless Framework](https://serverless.com).
Install it with the following command:

```sh
$ npm install -g serverless
```

You will need to first install [`npm`](https://npmjs.com/get-npm) if you do not already have it installed.

Once this is done, you can use the Serverless Framework to deploy the API.
Use the following command:

```sh
$ serverless deploy --stage prod
```

You'll see a URL that ends with `/webhook/github`, this is your webhook endpoint.

## Setting Up the Webhook

Now that you know where your API can be called, set up a webhook in your registry repository.
Use the API's URL as the "Payload URL".
Be sure to enter your webhook secret as well.
Finally, when selecting events, choose "Issue comments" and "Pull requests".

After all this is done, TagBot should be running on the target registry!
To view API logs, use this command:

```sh
$ serverless logs --function github --stage prod
```
