#!/usr/bin/env bash

set -e

PEM="$(pwd)/tag-bot.pem"
GPG="$(pwd)/gnupg"

if [ ! -f  "$PEM" ]; then
    echo "File $PEM does not exist"
    exit 1
fi
if [ ! -d  "$GPG" ]; then
    echo "Directory $GPG does not exist"
    exit 1
fi

(
  cd github
  rm -rf bin
  mkdir bin
  chmod 644 "$PEM"
  rm -f "$GPG/S.gpg-agent"
  find "$GPG" -type d -exec chmod 700 {} \;
  find "$GPG" -type f -exec chmod 600 {} \;
  tar -cf bin/resources.tar "$GPG" "$PEM" 2> /dev/null
  env GOOS="linux" go build -ldflags="-s -w" -o bin/github
)

(
  cd changelog
  rvm 2.5 do bundle install --quiet --path ../vendor/bundle 2> /dev/null
)
