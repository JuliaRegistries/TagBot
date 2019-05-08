#!/usr/bin/env bash

FNS=("github")

rm -rf bin
mkdir bin
cp *.pem bin
chmod 644 bin/*.pem

for fn in "${FNS[@]}"; do
  cd "$fn"
  env GOOS="linux" go build -ldflags="-s -w" -o "../bin/$fn"
  cd - > /dev/null
done
