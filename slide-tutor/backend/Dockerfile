# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && python -m pip install --requirement requirements.txt

RUN groupadd --system --gid 10001 slide-tutor \
    && useradd --system --uid 10001 --gid slide-tutor --home-dir /app slide-tutor


FROM base AS runtime

COPY alembic.ini .
COPY migrations ./migrations
COPY app ./app
COPY scripts ./scripts

RUN mkdir -p /app/data/uploads /app/data/qdrant-migrations \
    && chown -R slide-tutor:slide-tutor /app

USER slide-tutor

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


FROM runtime AS development

USER root
COPY requirements-dev.txt .
RUN python -m pip install --requirement requirements-dev.txt
COPY tests ./tests
USER slide-tutor

CMD ["pytest", "-q"]
