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

checked pytest
checked black --check bin tagbot test
checked flake8 bin tagbot test
checked mypy bin tagbot test

exit $exit
