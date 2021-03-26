#!/usr/bin/env sh

cd $(dirname "$0")/..

docker build -t tagbot:test .
docker run --rm --mount type=bind,source=$(pwd),target=/repo tagbot:test sh -c '
  pip install poetry
  cd /repo
  poetry install
  poetry run ./bin/test.sh'
