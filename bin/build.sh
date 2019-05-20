#!/usr/bin/env bash

set -e

PEM="tag-bot.pem"
GPG="gnupg"

cd $(dirname "$0")/..

if [ ! -f  "$PEM" ]; then
    echo "File $PEM does not exist"
    exit 1
fi
if [ ! -d  "$GPG" ]; then
    echo "Directory $GPG does not exist"
    exit 1
fi

rm -rf github/bin
mkdir github/bin
chmod 644 "$PEM"
rm -f "$GPG/S.gpg-agent"
find "$GPG" -type d -exec chmod 700 {} \;
find "$GPG" -type f -exec chmod 600 {} \;
tar -cf github/bin/resources.tar "$GPG" "$PEM"
(
  cd github
  env GOOS="linux" go build -ldflags="-s -w" -o bin/github
)

(
  rm -rf vendor
  cd changelog
  rvm 2.5 do bundle install --quiet --path ../vendor/bundle
)
