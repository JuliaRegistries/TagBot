FROM python:3.12-slim as builder

RUN apt-get update && apt-get install -y curl

# Install Poetry (latest) using the official install script
RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="/root/.local/bin:$PATH"

COPY pyproject.toml .
COPY poetry.lock .
RUN poetry export --format requirements.txt --output /root/requirements.txt

FROM python:3.12-slim
LABEL org.opencontainers.image.source https://github.com/JuliaRegistries/TagBot
ENV PYTHONPATH /root
RUN apt-get update && apt-get install -y git gnupg openssh-client
COPY --from=builder /root/requirements.txt /root/requirements.txt
RUN pip install --no-cache-dir --requirement /root/requirements.txt
COPY action.yml /root/action.yml
COPY tagbot /root/tagbot
CMD python -m tagbot.action
