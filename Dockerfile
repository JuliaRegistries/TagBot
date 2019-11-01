FROM ruby:2.6
RUN gem install github_changelog_generator -v 1.15
COPY action.py /root/action.py
CMD python3 /root/action.py
