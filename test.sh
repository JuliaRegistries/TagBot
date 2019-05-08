#!/usr/bin/env bash

FNS=("github")

for fn in "${FNS[@]}"; do
  cd "$fn"
  go test -v
done
