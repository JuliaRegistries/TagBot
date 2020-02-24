FROM python:3.8-alpine
RUN apk add git gnupg openssh-client
COPY requirements.txt /root
RUN pip install -r /root/requirements.txt
COPY tagbot /root/tagbot
ENV PYTHONPATH /root
CMD python -m tagbot.action
