#!/usr/bin/env bash

set -e

PEM="tagbot.pem"
GPG="gnupg"

cd $(dirname "$0")/..

if [ "$#" -eq 0 ] || [ "$1" = "tagbot" ]; then
  if [ ! -f  "$PEM" ]; then
    echo "File $PEM does not exist"
    exit 1
  fi
  if [ ! -d  "$GPG" ]; then
    echo "Directory $GPG does not exist"
    exit 1
  fi

  chmod 644 "$PEM"
  rm -f "$GPG/S.gpg-agent"
  find "$GPG" -type d -exec chmod 700 {} \;
  find "$GPG" -type f -exec chmod 600 {} \;
  tar -cf resources.tar "$GPG" "$PEM"
fi

if [ "$#" -eq 0 ] || [ "$1" = "changelog" ]; then
  (
    cd changelog
    rvm 2.5 do bundle install --quiet --path ../vendor/bundle --without test
  )
fi
