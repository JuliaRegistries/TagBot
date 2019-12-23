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

checked pytest --cov tagbot
checked black --check bin tagbot test
checked flake8 bin tagbot test
# The test code monkey patches methods a lot, and mypy doesn't like that.
checked mypy --strict bin tagbot

exit "$exit"
