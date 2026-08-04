FROM python:3.12-slim

WORKDIR /app

# curl: container healthcheck. build-essential/libpq-dev: fallback for any
# dependency without a prebuilt wheel on the target platform (psycopg/
# asyncpg ship wheels for the common ones, but this keeps arm64/exotic
# platforms from failing a from-source build).
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# pyproject.toml declares poetry-core as its PEP 517 build backend, so a
# plain `pip install .` builds and installs correctly without the poetry
# CLI itself — one fewer moving part, and a much smaller/faster image than
# installing poetry just to immediately disable its virtualenv.
COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts
RUN pip install .

# Pre-download the ONNX embedding/reranker models at build time so the
# first container start doesn't pay a cold-download tax (and so the app
# still boots offline once the image is built).
RUN python -c "from app.services import embeddings; embeddings.warm_up()"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
