FROM ruby:2.6
COPY requirements.txt /root
RUN apt-get -y update && \
  apt-get -y upgrade && \
  apt-get -y install python3-pip && \
  pip3 install -r /root/requirements.txt && \
  gem install github_changelog_generator -v 1.15
COPY tagbot /root/tagbot
ENV PYTHONPATH /root
CMD python3 -m tagbot
