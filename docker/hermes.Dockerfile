FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HERMES_HOME=/opt/hermes-home \
    HERMES_HOST=0.0.0.0 \
    HERMES_PORT=9119

WORKDIR /opt/realestate

RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# The paired workspace checkout is the build context's hermes-agent/ directory.
# Hermes remains an upstream checkout; only the Product plugin is installed into it.
COPY hermes-agent /opt/hermes-agent
COPY maia-agent/plugin /opt/realestate/plugin
COPY maia-agent/roles /opt/realestate/roles
COPY maia-agent/scripts/apply-models.sh /opt/realestate/scripts/apply-models.sh
COPY maia-agent/scripts/docker-hermes-entrypoint.sh /opt/realestate/scripts/docker-hermes-entrypoint.sh

RUN pip install --no-cache-dir -e /opt/hermes-agent \
    && pip install --no-cache-dir /opt/realestate/plugin \
    && chmod +x /opt/realestate/scripts/*.sh

EXPOSE 9119

ENTRYPOINT ["/opt/realestate/scripts/docker-hermes-entrypoint.sh"]
