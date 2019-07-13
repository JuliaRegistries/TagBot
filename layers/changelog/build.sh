#!/usr/bin/env bash

set -e

GCG_REF="f73e689ef1d4b8726aa39c4dc5cc8671da0d45e2"
IMAGE="amazonlinux:2018.03"
RUBY_VER="2.6.3"

if [ "$1" = build ]; then
  yum -y update
  yum -y install bzip2 gcc git openssl-devel readline-devel which zlib-devel
  curl -L https://github.com/rbenv/ruby-build/archive/v20190615.tar.gz | tar zxf -
  RUBY_CONFIGURE_OPTS="--enable-shared" ./ruby-build-20190615/bin/ruby-build --verbose "$RUBY_VER" /opt
  rm -rf /opt/{include,share}
  /opt/bin/gem install specific_install
  /opt/bin/gem specific_install https://github.com/github-changelog-generator/github-changelog-generator --ref "$GCG_REF"
  /opt/bin/gem uninstall specific_install
else
  cd $(dirname "$0")
  if [ -d bin ]; then
    read -e -p "Layer '$(basename $(pwd))' appears to be already built. Rebuild? [y/N]> " confirm
    [[ "$confirm" != [Yy]* ]] && exit
  fi
  rm -rf bin lib
  script=$(basename "$0")
  docker run -t --rm --mount "type=bind,source=$(pwd),destination=/opt" "$IMAGE" "/opt/$script" build
fi
