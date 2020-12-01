FROM python:3.8-alpine as builder
RUN apk add gcc libffi-dev musl-dev openssl-dev
RUN pip install poetry
COPY pyproject.toml .
RUN poetry export --format requirements.txt --output /root/requirements.txt

FROM python:3.8-alpine
LABEL org.opencontainers.image.source https://github.com/JuliaRegistries/TagBot
ENV PYTHONPATH /root
RUN apk --no-cache add git gnupg openssh-client
COPY --from=builder /root/requirements.txt /root/requirements.txt
RUN pip install --no-cache-dir --requirement /root/requirements.txt
COPY action.yml /root/action.yml
COPY tagbot /root/tagbot
CMD python -m tagbot.action
