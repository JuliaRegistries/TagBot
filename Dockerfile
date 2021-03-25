FROM python:3.8-slim as builder
RUN pip install poetry
COPY pyproject.toml .
COPY poetry.lock .
RUN poetry export --format requirements.txt --output /root/requirements.txt

FROM python:3.8-slim
LABEL org.opencontainers.image.source https://github.com/JuliaRegistries/TagBot
ENV PYTHONPATH /root
RUN apt-get update && apt-get install -y git gnupg openssh-client
COPY --from=builder /root/requirements.txt /root/requirements.txt
RUN pip install --no-cache-dir --requirement /root/requirements.txt
COPY action.yml /root/action.yml
COPY tagbot /root/tagbot
CMD python -m tagbot.action
