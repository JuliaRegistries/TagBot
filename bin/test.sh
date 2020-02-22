#!/usr/bin/env sh

exit=0

checked() {
  echo "$ $@"
  "$@"
  last="$?"
  if [ "$last" -ne 0 ]; then
    echo "$@: exit $last"
    exit=1
  fi
}

cd $(dirname "$0")/..

checked python -m pytest --cov tagbot --ignore node_modules
checked black --check stubs tagbot test
checked flake8 stubs tagbot test
# The test code monkey patches methods a lot, and mypy doesn't like that.
checked env MYPYPATH=stubs mypy --strict tagbot

exit "$exit"
