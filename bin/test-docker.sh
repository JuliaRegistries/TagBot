#!/usr/bin/env sh

cd $(dirname "$0")/..

docker build -t tagbot:test .
docker run --rm --mount type=bind,source=$(pwd),target=/repo tagbot:test sh -c '
  apk add gcc libffi-dev make musl-dev openssl-dev
  pip install poetry
  cd /repo
  poetry install
  poetry run make test'
