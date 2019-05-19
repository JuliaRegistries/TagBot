#!/usr/bin/env bash

set -e

cd $(dirname "$0")/..

(
  cd github
  go test -v
)
