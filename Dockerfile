FROM python:3.8-alpine as builder
RUN apk add gcc libffi-dev musl-dev openssl-dev
RUN pip install poetry
COPY pyproject.toml .
RUN poetry export -f requirements.txt -o /root/requirements.txt

FROM python:3.8-alpine
ENV PYTHONPATH /root
RUN apk add git gnupg openssh-client
COPY --from=builder /root/requirements.txt /root/requirements.txt
RUN pip install -r /root/requirements.txt
COPY action.yml /root/action.yml
COPY tagbot /root/tagbot
CMD python -m tagbot.action
