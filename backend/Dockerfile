# --- builder: compile/install into a self-contained prefix --------------
FROM python:3.12-slim AS builder

WORKDIR /app

# build-essential/libpq-dev: only needed to build any dependency without a
# prebuilt wheel for this platform. None of this ships in the final image.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# pyproject.toml declares poetry-core as its PEP 517 build backend, so a
# plain `pip install` builds and installs correctly without the poetry CLI
# itself — one fewer moving part, and a smaller/faster image than installing
# poetry just to immediately disable its virtualenv.
COPY pyproject.toml ./
COPY app ./app
RUN pip install --prefix=/install .

# --- runtime: slim, no compilers, just the installed packages + app ------
FROM python:3.12-slim AS runtime

WORKDIR /app

# curl: container healthcheck. libpq5: the *runtime* Postgres client lib
# that psycopg's compiled bindings dynamically link against — libpq-dev's
# headers (needed only to build it) stay behind in the builder stage.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UVICORN_WORKERS=1

COPY --from=builder /install /usr/local
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts

# Pre-download the ONNX embedding/reranker models at build time so the
# first container start doesn't pay a cold-download tax (and so the app
# still boots offline once the image is built).
RUN python -c "from app.services import embeddings; embeddings.warm_up()"

EXPOSE 8000

# One uvicorn worker by default: scale by adding container replicas, not
# in-process workers — each process loads its own copy of the embedding/
# reranker models, so extra in-process workers multiply RAM for no
# throughput win the ASGI event loop wasn't already providing. Override
# UVICORN_WORKERS for a box with RAM to spare.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS}"]
