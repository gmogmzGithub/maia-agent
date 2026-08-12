FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir --upgrade pip==26.2.1

COPY pyproject.toml README.md ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./

# The local image includes test dependencies so verification also stays inside
# Docker: `docker compose exec product pytest`.
RUN python -m pip install --no-cache-dir ".[dev]"

COPY plugin ./plugin
COPY tests ./tests

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn realestate.app:app --host 0.0.0.0 --port 8080"]
