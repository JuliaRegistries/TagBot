# Julia is far easier to install than Python and we need both.
FROM python:3.9-slim

# Note: We're installing our runtime binary dependencies with apt because it saves space.
RUN \
  apt-get update && \
  apt-get -y install build-essential curl git gnupg openssh-client && \
  mkdir /opt/julia && \
  curl https://julialang-s3.julialang.org/bin/linux/x64/1.6/julia-1.6.0-linux-x86_64.tar.gz | tar -zxC /opt/julia --strip-components=1 && \
  bash -c 'rm -rf /opt/julia/share/{appdata,applications,doc,man,julia/test}'

ENV PATH /opt/julia/bin:$PATH
ENV JULIA_PROJECT /opt/TagBot
WORKDIR $JULIA_PROJECT

# TODO: This will eventually need to be split up to cache better.
COPY bin bin
COPY src src
COPY test test
COPY Project.toml Manifest.toml action.yml ./
RUN \
  julia bin/docker_build.jl && \
  apt-get -y remove build-essential curl && \
  apt-get -y autoremove && \
  rm -rf /var/lib/apt/lists

CMD julia -e 'using TagBot; TagBot.main()'
