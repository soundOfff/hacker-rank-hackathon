# syntax=docker/dockerfile:1
#
# Image for the Multi-Modal Evidence Review solution. Brings the whole pipeline
# (code/ + dataset/) into one runnable container so `docker compose` can stand up
# the app alongside Redis (shared cache) and Postgres/pgvector (vector store).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first so the layer caches across code changes. The infra
# deps (redis / psycopg / pgvector) are needed for the shared cache + vector
# store; psycopg[binary] bundles libpq, so no apt packages are required.
COPY code/requirements.txt code/requirements-infra.txt /app/code/
RUN pip install -r /app/code/requirements.txt -r /app/code/requirements-infra.txt

# Application code and data.
COPY code/ /app/code/
COPY dataset/ /app/dataset/
COPY problem_statement.md AGENTS.md /app/

# Cost-first predictions by default; override the command for eval / indexing,
# e.g. `docker compose run --rm app python code/evaluation/main.py`.
CMD ["python", "code/main.py"]
