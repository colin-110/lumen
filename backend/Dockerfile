# --- deps: turn the lock file into a pinned requirements list -----------
# A stage of its own, and not merely tidiness. Installing poetry alongside the
# application in one stage puts poetry's own dependencies (requests, urllib3,
# certifi, ...) into that stage's site-packages, and `pip install --prefix`
# then treats them as already satisfied and skips them — so they never land in
# /install, and the runtime image dies on `import requests` from inside
# fastembed. Poetry runs where nothing else is installed and only its output
# crosses over.
FROM python:3.12-slim AS deps

WORKDIR /app
RUN pip install --no-cache-dir poetry==1.8.5 poetry-plugin-export
COPY pyproject.toml poetry.lock ./
RUN poetry export --format requirements.txt --without-hashes --only main \
    --output /requirements.txt


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

# Dependencies come from poetry.lock, not from pyproject's version ranges.
# `pip install .` resolved the carets fresh on every build, so two builds of
# the same commit could ship different versions of litellm, fastembed or
# qdrant-client — and a green CI run said nothing about what production would
# actually get.
COPY --from=deps /requirements.txt /tmp/requirements.txt
RUN pip install --prefix=/install -r /tmp/requirements.txt

# The application itself, without dependency resolution: everything it needs
# is pinned and installed above.
COPY pyproject.toml ./
COPY app ./app
RUN pip install --prefix=/install --no-deps .

# Prune transitive dependencies that inference never loads.
#
# These arrive via onnxruntime/fastembed and none appear in sys.modules
# after importing the app and exercising the dense embedder, the sparse
# embedder and the cross-encoder reranker — the only three things that
# touch ONNX at runtime. onnxruntime loads a .onnx file through its own
# C++ loader; the `onnx` Python package, and the sympy/mpmath/ml_dtypes
# stack behind its shape-inference tooling, is a model-*authoring*
# dependency. Verified by wiping the model cache and re-running warm_up()
# plus all three models end to end with these removed.
#
# Pruned here in the builder, before /install is copied into the runtime
# stage — deleting them in a later layer would not shrink the image, since
# earlier layers keep the bytes regardless.
#
# Deliberately NOT pruned despite looking unused in a runtime import trace:
#   hf_xet         - fastembed's HuggingFace download path requires it and
#                    hard-fails without it (its "falling back to other
#                    sources" retry also fails). Invisible at runtime only
#                    because the models are already cached by then; removing
#                    it breaks the warm_up step below on a cold cache.
#   uvloop         - uvicorn selects it via its own loop setup, not an import
#                    from our code, so it never shows up in sys.modules here.
#   psycopg_binary - backs the sync `postgresql+psycopg` URL alembic uses
#                    for migrations (see core/config.py); only asyncpg is
#                    exercised by the request path.
ARG SITE=/install/lib/python3.12/site-packages
RUN rm -rf $SITE/sympy $SITE/mpmath $SITE/ml_dtypes $SITE/onnx \
    # Bundled test suites in packages we *do* ship. numpy alone carries ~9MB.
    && rm -rf $SITE/numpy/_core/tests $SITE/numpy/lib/tests $SITE/numpy/f2py/tests \
              $SITE/sqlalchemy/testing \
    # Type stubs are consumed by type checkers, never by the interpreter.
    && find $SITE -name '*.pyi' -delete

# --- runtime: slim, no compilers, just the installed packages + app ------
FROM python:3.12-slim AS runtime

WORKDIR /app

# curl: container healthcheck. libpq5: the *runtime* Postgres client lib
# that psycopg's compiled bindings dynamically link against — libpq-dev's
# headers (needed only to build it) stay behind in the builder stage.
# tesseract-ocr: OCR fallback for scanned/image-only PDF pages (see
# app/services/document_parser.py) — a real binary, not a pip package.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    tesseract-ocr \
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
