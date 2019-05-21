#!/usr/bin/env bash

set -e

cd $(dirname "$0")/..

if [ $# -eq 0 ] || [ "$1" = "github" ]; then
  (
    cd github
    go test -v
  )
fi

if [ $# -eq 0 ] || [ "$1" = "changelog" ]; then
  (
    cd changelog
    rvm 2.5 do bundle install --quiet --deployment
    rvm 2.5 do ruby test.rb
  )
fi
