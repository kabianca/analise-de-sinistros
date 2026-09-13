# syntax=docker/dockerfile:1

# One image for the generator, the loader, dbt and the tests. Postgres is a
# separate service in docker-compose.yaml; nothing here talks to it at build
# time, so the image builds offline once the wheels are cached.
ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim-trixie

# A fixed, non-root UID so files written into the bind-mounted ./data belong
# to the person running `make`, on the common case of a single-user machine.
RUN useradd --create-home --uid 1000 --shell /bin/bash estrato

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ESTRATO_DATA_DIR=/app/data \
    DBT_PROJECT_DIR=/app/dbt \
    DBT_PROFILES_DIR=/app/dbt \
    # dbt phones home by default; a portfolio image has no business doing so.
    DBT_SEND_ANONYMOUS_USAGE_STATS=false

WORKDIR /app

# Install dependencies from the manifest before copying the code, so editing a
# module does not re-download dbt. The stub package is only there because an
# editable install needs something to point at.
COPY pyproject.toml README.md ./
RUN mkdir -p estrato && touch estrato/__init__.py \
 && pip install --no-cache-dir --editable ".[dev]"

COPY estrato ./estrato
COPY dbt ./dbt

RUN mkdir -p /app/data /app/dbt/target /app/dbt/logs \
 && chown -R estrato:estrato /app

USER estrato

CMD ["python", "-m", "estrato", "--help"]
