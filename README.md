# Deploying The Legacy GitHub App

The old GitHub App can be deployed as a plain old web server.
To run it through Docker, here's an example:

```sh
docker build -t tagbot:app .
docker run \
    --name tagbot \
    -d \
    --mount type=bind,source=$(pwd)/tagbot.pem,target=/app/tagbot.pem -e GITHUB_PEM=/app/tagbot.pem \
    -p 4000:4000 -e PORT=4000 \
    -e GITHUB_APP_ID=123 \
    -e GITHUB_WEBHOOK_SECRET=asdf \
    tagbot:app
```

This assumes that you already have a GitHub App set up, and have obtained its ID, webhook secret, and private key.
