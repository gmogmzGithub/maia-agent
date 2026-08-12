FROM python:3.12-slim

# Pin the exact reviewed Hermes source. The runtime version is also checked by
# Maia at startup before it accepts conversation work.
ARG HERMES_REPOSITORY=https://github.com/NousResearch/hermes-agent.git
ARG HERMES_COMMIT=3e6a081d60e8d04a03d37008464f44555bc88832

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HERMES_HOME=/opt/hermes-home

WORKDIR /opt/maia

# The reviewed commit pins a cryptography release with published advisories.
RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates curl git \
    && rm -rf /var/lib/apt/lists/* \
    && git init /opt/hermes-agent \
    && git -C /opt/hermes-agent remote add origin "$HERMES_REPOSITORY" \
    && git -C /opt/hermes-agent fetch --depth 1 origin "$HERMES_COMMIT" \
    && git -C /opt/hermes-agent checkout --detach FETCH_HEAD \
    && sed -i 's/cryptography==48\.0\.1/cryptography==50.0.0/' /opt/hermes-agent/pyproject.toml \
    && python -m pip install --no-cache-dir --upgrade pip==26.2.1 \
    && python -m pip install --no-cache-dir -e /opt/hermes-agent \
    && rm -rf /opt/hermes-agent/.git \
    && apt-get purge --auto-remove -y git git-man

COPY plugin ./plugin
RUN python -m pip install --no-cache-dir ./plugin

COPY roles ./roles
COPY docker/hermes-entrypoint.sh /usr/local/bin/maia-hermes-entrypoint
RUN chmod +x /usr/local/bin/maia-hermes-entrypoint

ENTRYPOINT ["maia-hermes-entrypoint"]
