FROM ruby:2.6
RUN apt-get -y update && \
  apt-get -y upgrade && \
  apt-get -y install python3-pip && \
  pip3 install PyGithub==1.44 toml==0.10 && \
  gem install github_changelog_generator -v 1.15
COPY action.py /root/action.py
CMD python3 /root/action.py
