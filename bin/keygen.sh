#!/usr/bin/env bash

set -e

if [ $# -ne 3 ]; then
  echo "Usage: $0 <name> <email> <output>"
  exit 1
fi

IMAGE="amazonlinux:2018.03"
NAME="$1"
EMAIL="$2"
OUTPUT="$3"

mkdir -p "$OUTPUT"
docker run --rm --mount "type=bind,source=$OUTPUT,destination=/root/.gnupg" "$IMAGE" bash -c "
      set -e
      echo 'Generating a GPG key, this might take a little while'
      echo '
        Key-Type: RSA
        Subkey-Type: RSA
        Name-Real: $NAME
        Name-Email: $EMAIL
        %commit
      ' > batch
      gpg --batch --gen-key batch
      gpg --list-keys
      echo 'Your public key is below:'
      echo
      gpg --export --armor
    "
