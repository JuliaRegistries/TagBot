FROM python:3.14-slim as builder

RUN pip install --no-cache-dir poetry poetry-plugin-export

COPY pyproject.toml .
COPY poetry.lock .
RUN poetry export --format requirements.txt --output /root/requirements.txt

FROM python:3.14-slim
LABEL org.opencontainers.image.source https://github.com/JuliaRegistries/TagBot
RUN apt-get update && apt-get install -y git gnupg make openssh-client
COPY --from=builder /root/requirements.txt /root/requirements.txt
RUN pip install --no-cache-dir --requirement /root/requirements.txt
COPY pyproject.toml /root/pyproject.toml
COPY action.yml /root/action.yml
COPY tagbot /root/tagbot
RUN pip install --no-cache-dir --no-deps /root
CMD python -m tagbot.action
