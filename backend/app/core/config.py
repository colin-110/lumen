"""Application settings.

All configuration is environment-driven. Nothing here performs I/O, so the
module is safe to import from the API process, the Celery worker and Alembic
alike.
"""

from __future__ import annotations

import json
import sys
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import PostgresDsn, RedisDsn, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

INSECURE_SECRET_KEY = "dev-only-insecure-key-change-me"
# Shipped in .env.example; if it survives into a real deployment it is a
# default credential, not a configuration choice.
INSECURE_SUPERUSER_PASSWORD = "admin12345"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ------------------------------------------------------------------ app
    PROJECT_NAME: str = "Lumen"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True

    @computed_field
    @property
    def DEBUG(self) -> bool:
        return self.ENVIRONMENT == "local"

    # ------------------------------------------------------------- security
    SECRET_KEY: str = INSECURE_SECRET_KEY
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    # Registration is open in local dev; lock it down elsewhere.
    ALLOW_OPEN_REGISTRATION: bool = True
    FIRST_SUPERUSER_EMAIL: str = "admin@enterprise.ai"
    FIRST_SUPERUSER_PASSWORD: str = INSECURE_SUPERUSER_PASSWORD
    FIRST_ORG_NAME: str = "Acme Corp"

    # Scrape guard for /metrics. Unset means the endpoint is open, which is
    # only acceptable on a private network.
    METRICS_TOKEN: str | None = None

    # Promote every configuration warning to a startup failure. Off by
    # default so that adding a new check cannot turn an upgrade into an
    # outage; turn it on once a deployment's configuration has been reviewed.
    STRICT_PRODUCTION_CHECKS: bool = False

    # Auth endpoints are unauthenticated by definition, so they are limited by
    # client IP rather than by user id.
    RATE_LIMIT_LOGIN_PER_MINUTE: int = 10
    RATE_LIMIT_REGISTER_PER_MINUTE: int = 5

    # NoDecode: pydantic-settings would otherwise try to JSON-decode this env
    # var itself before our validator runs, and fail on a plain comma-separated
    # string (or even an empty string) — NoDecode hands the raw string to
    # _split_origins below instead.
    BACKEND_CORS_ORIGINS: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, v: Any) -> Any:
        """Accept a JSON array or a comma-separated string from the env."""
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                return json.loads(v)
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    # ------------------------------------------------------------- database
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "enterprise_ai"
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    DB_ECHO: bool = False

    @computed_field
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        """Async DSN used by the API and the worker."""
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD,
                host=self.POSTGRES_SERVER,
                port=self.POSTGRES_PORT,
                path=self.POSTGRES_DB,
            )
        )

    @computed_field
    @property
    def SYNC_DATABASE_URI(self) -> str:
        """Sync DSN, used by tooling that cannot drive asyncio."""
        return str(
            PostgresDsn.build(
                scheme="postgresql+psycopg",
                username=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD,
                host=self.POSTGRES_SERVER,
                port=self.POSTGRES_PORT,
                path=self.POSTGRES_DB,
            )
        )

    # ---------------------------------------------------------- redis/queue
    # Host-side default is 6380 (not the Redis standard 6379) to match this
    # repo's docker-compose.yml, which remaps it to avoid clashing with any
    # Redis already running on the host. Inside docker-compose, the backend
    # and worker services override this to redis://redis:6379/0 (the
    # container-to-container address) via environment variables.
    REDIS_URL: RedisDsn = "redis://localhost:6380/0"  # type: ignore[assignment]

    # Celery uses Redis (not RabbitMQ) as both broker and result backend —
    # one fewer service to run/monitor/pay memory for, and Redis is already
    # a hard dependency here for the semantic cache and rate limiting. A
    # separate DB index (1, vs. 0 for cache/rate-limit) just keeps the key
    # spaces apart; it's cosmetic, Redis doesn't isolate DBs from each other.
    CELERY_BROKER_URL: str = "redis://localhost:6380/1"

    # Run document ingestion inside the API process instead of dispatching to
    # a Celery worker. The worker is a second process that loads its own copy
    # of the dense + sparse ONNX models (~500MB measured), which is the single
    # largest line item when trying to fit this stack on a 1GB host such as an
    # AWS free-tier t3.micro — see docker-compose.free-tier.yml.
    #
    # The trade is real and you should not enable this under load: Celery gives
    # bounded concurrency, retries with backoff (acks_late), and durability if
    # the API restarts mid-ingest. Inline ingestion gives none of that; a crash
    # during processing leaves the document stuck in PROCESSING.
    INGEST_INLINE: bool = False

    @computed_field
    @property
    def CELERY_RESULT_BACKEND(self) -> str:
        return str(self.REDIS_URL)

    # --------------------------------------------------------------- qdrant
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str | None = None
    QDRANT_COLLECTION: str = "enterprise_documents"
    QDRANT_CACHE_COLLECTION: str = "semantic_cache"
    QDRANT_TIMEOUT: int = 30

    # ------------------------------------------------------------- storage
    # See the REDIS_URL comment above — 9005 matches this repo's MinIO port
    # remap in docker-compose.yml; the backend/worker containers override
    # this to http://minio:9000 (the container-to-container address).
    S3_ENDPOINT_URL: str | None = "http://localhost:9005"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET: str = "enterprise-docs"
    S3_REGION: str = "us-east-1"
    MAX_UPLOAD_BYTES: int = 50 * 1024 * 1024  # 50 MB

    # ----------------------------------------------------------- retrieval
    DENSE_MODEL: str = "BAAI/bge-small-en-v1.5"
    DENSE_DIM: int = 384
    SPARSE_MODEL: str = "Qdrant/bm25"
    RERANK_MODEL: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    EMBED_BATCH_SIZE: int = 64
    # Threads fastembed's ONNX runtime may use per worker process.
    ONNX_THREADS: int = 0  # 0 => let onnxruntime decide

    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 150
    RETRIEVE_CANDIDATES: int = 40  # pulled from Qdrant before reranking
    RERANK_TOP_K: int = 6  # handed to the LLM after reranking
    MIN_RERANK_SCORE: float = -6.0  # cross-encoder logit floor
    # Floor never trims below this. The cross-encoder scores anything that
    # isn't a direct answer steeply negative, so on broad questions the floor
    # alone would leave a single chunk and the model could only discuss one
    # document. See _search_sync in services/retrieval.py.
    MIN_CONTEXT_CHUNKS: int = 4

    # ------------------------------------------------------------------ ocr
    # Scanned/image-only PDF pages have no text layer for PyMuPDF to read.
    # Per-page fallback: if a page yields fewer than this many characters,
    # treat it as scanned and OCR it with Tesseract instead.
    OCR_ENABLED: bool = True
    OCR_MIN_CHARS_PER_PAGE: int = 20
    OCR_DPI: int = 200

    # ----------------------------------------------------------------- llm
    OPENAI_API_KEY: str | None = None
    ANTHROPIC_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None
    GROQ_API_KEY: str | None = None
    OLLAMA_API_BASE: str | None = None

    PRIMARY_MODEL: str = "gemini/gemini-flash-latest"
    FALLBACK_MODELS: Annotated[list[str], NoDecode] = []
    LLM_TIMEOUT: int = 90
    LLM_MAX_RETRIES: int = 2
    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_TOKENS: int = 2048
    MAX_TOOL_ITERATIONS: int = 4
    MAX_HISTORY_MESSAGES: int = 20

    # Reformulates a follow-up question ("what about the timeline?") into a
    # standalone search query before retrieval, using the last few turns of
    # history. Costs one extra small/fast LLM call per follow-up turn (first
    # message in a conversation skips it — nothing to rewrite from yet).
    QUERY_REWRITE_ENABLED: bool = True
    QUERY_REWRITE_MAX_TOKENS: int = 120
    QUERY_REWRITE_HISTORY_TURNS: int = 6

    @field_validator("FALLBACK_MODELS", mode="before")
    @classmethod
    def _split_models(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            if v.startswith("["):
                return json.loads(v)
            return [m.strip() for m in v.split(",") if m.strip()]
        return v

    # --------------------------------------------------------------- cache
    SEMANTIC_CACHE_ENABLED: bool = True
    SEMANTIC_CACHE_THRESHOLD: float = 0.97
    SEMANTIC_CACHE_TTL_SECONDS: int = 60 * 60 * 6
    # How often the app sweeps expired cache entries out of Qdrant. The TTL
    # is only a read filter; without this sweep nothing is ever deleted.
    SEMANTIC_CACHE_SWEEP_SECONDS: int = 15 * 60

    # ------------------------------------------------------------ limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_CHAT_PER_MINUTE: int = 30
    RATE_LIMIT_UPLOAD_PER_MINUTE: int = 20

    # Whether X-Forwarded-For/X-Request-ID may be believed. True only when
    # something trustworthy (an ALB, Caddy, nginx) sets them; otherwise a
    # client can forge both, which turns per-IP rate limiting into a no-op.
    TRUSTED_PROXY_HEADERS: bool = False

    # ------------------------------------------------------ web search tool
    WEB_SEARCH_ENABLED: bool = False
    TAVILY_API_KEY: str | None = None

    # ------------------------------------------------------- request limits
    # A prompt is built from the question plus retrieved context, so an
    # unbounded question is an unbounded bill and a guaranteed context-window
    # error. Bound it at the edge instead of discovering it at the provider.
    MAX_MESSAGE_CHARS: int = 8000
    MAX_PINNED_DOCUMENTS: int = 20
    # MAX_HISTORY_MESSAGES caps the number of turns; this caps their total
    # size, which is what actually determines the prompt cost.
    MAX_HISTORY_CHARS: int = 24000

    @model_validator(mode="after")
    def _check_production_credentials(self) -> Settings:
        """Guard development credentials outside `local`.

        Every one of these has a safe-looking default so that `pytest`, a
        fresh clone and `make setup` all work with no configuration. That
        convenience is exactly what makes them dangerous the moment the same
        file is deployed: nothing else in the system would ever notice that
        the JWT signing key is the one published in .env.example.

        Two severities, deliberately:

        *Fatal* is reserved for the signing key. A published or short
        SECRET_KEY means anyone can mint a token for any user including a
        superuser, so there is no configuration in which continuing to serve
        is better than stopping.

        Everything else *warns*. Those are real problems, but an operator can
        have compensating controls (a private subnet, a security group, a
        reverse proxy) and — more to the point — a check added in one release
        must not brick a deployment that was running fine in the last one.
        METRICS_TOKEN is the clearest case: it did not exist before this
        change, so no existing .env can possibly satisfy it, and hard-failing
        on it would turn an upgrade into an outage.

        Set STRICT_PRODUCTION_CHECKS=true to promote every warning to fatal.
        That is the recommended setting once a deployment's configuration has
        actually been reviewed.
        """
        if self.ENVIRONMENT == "local":
            return self

        fatal: list[str] = []
        if self.SECRET_KEY == INSECURE_SECRET_KEY:
            fatal.append(
                "SECRET_KEY is still the published development value — anyone can forge a JWT for "
                'any account. Generate one with: python -c "import secrets; '
                'print(secrets.token_urlsafe(48))"'
            )
        elif len(self.SECRET_KEY) < 32:
            fatal.append("SECRET_KEY must be at least 32 characters")

        warnings_: list[str] = []
        if self.FIRST_SUPERUSER_PASSWORD == INSECURE_SUPERUSER_PASSWORD:
            warnings_.append("FIRST_SUPERUSER_PASSWORD is still the published development value")
        if self.ALLOW_OPEN_REGISTRATION:
            warnings_.append(
                "ALLOW_OPEN_REGISTRATION=true lets anyone create an account (and an organization) "
                "on a public deployment; set it to false and provision users deliberately"
            )
        if self.POSTGRES_PASSWORD == "postgres":
            warnings_.append("POSTGRES_PASSWORD is still the default")
        if self.S3_SECRET_KEY == "minioadmin":
            warnings_.append("S3_SECRET_KEY is still the MinIO default")
        if not self.METRICS_TOKEN:
            warnings_.append(
                "METRICS_TOKEN is unset, which leaves /metrics publicly scrapable; set a random "
                "value and pass it to Prometheus as a bearer token"
            )

        if self.STRICT_PRODUCTION_CHECKS:
            fatal.extend(warnings_)
            warnings_ = []

        if fatal:
            raise ValueError(
                f"Refusing to start with ENVIRONMENT={self.ENVIRONMENT}:\n  - "
                + "\n  - ".join(fatal)
            )

        # Printed rather than logged: logging is configured after settings are
        # constructed, so a logger call here would go nowhere.
        for problem in warnings_:
            print(f"WARNING [config] {problem}", file=sys.stderr)  # noqa: T201

        return self

    @computed_field
    @property
    def configured_providers(self) -> list[str]:
        """Providers that have usable credentials, for /health and startup logs."""
        found = []
        if self.OPENAI_API_KEY:
            found.append("openai")
        if self.ANTHROPIC_API_KEY:
            found.append("anthropic")
        if self.GEMINI_API_KEY:
            found.append("gemini")
        if self.GROQ_API_KEY:
            found.append("groq")
        if self.OLLAMA_API_BASE:
            found.append("ollama")
        return found


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
