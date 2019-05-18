#!/usr/bin/env bash

set -e

(
  cd github
  go test -v
)
