FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive
ARG APP_UID=1000
ARG APP_GID=1000

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        curl \
        python3 \
        tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "${APP_GID}" accountmonitor \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" \
        --create-home --shell /usr/sbin/nologin accountmonitor

ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    CONFIG_PATH=/app/config/config.json \
    REPORT_TIME=13:00 \
    RUN_ON_START=true

WORKDIR /app

COPY --chown=accountmonitor:accountmonitor codex_daily_report.py /app/
COPY --chown=accountmonitor:accountmonitor tools/docker_runner.py /app/tools/

RUN mkdir --parents /app/config \
    && chown accountmonitor:accountmonitor /app/config

USER accountmonitor

ENTRYPOINT ["python3", "-u", "/app/tools/docker_runner.py"]
