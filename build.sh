#!/usr/bin/env bash

FNS=("github")
PEM="tag-bot.pem"
GPG="gnupg"
RESOURCES="bin/resources.tar"

if [ ! -f  "$PEM" ]; then
    echo "File $PEM does not exist"
    exit 1
fi
if [ ! -d  "$GPG" ]; then
    echo "Directory $GPG does not exist"
    exit 1
fi

rm -rf bin
mkdir bin
chmod 644 "$PEM"
rm -f "$GPG/S.gpg-agent"
find "$GPG" -type d -exec chmod 700 {} \;
find "$GPG" -type f -exec chmod 600 {} \;
tar -cf "$RESOURCES" "$GPG" "$PEM"

for fn in "${FNS[@]}"; do
  (
    cd "$fn"
    env GOOS="linux" go build -ldflags="-s -w" -o "../bin/$fn"
  )
done
