"""Application settings.

All configuration is environment-driven. Nothing here performs I/O, so the
module is safe to import from the API process, the Celery worker and Alembic
alike.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import PostgresDsn, RedisDsn, computed_field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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
    SECRET_KEY: str = "dev-only-insecure-key-change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    # Registration is open in local dev; lock it down elsewhere.
    ALLOW_OPEN_REGISTRATION: bool = True
    FIRST_SUPERUSER_EMAIL: str = "admin@enterprise.ai"
    FIRST_SUPERUSER_PASSWORD: str = "admin12345"
    FIRST_ORG_NAME: str = "Acme Corp"

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

    # ------------------------------------------------------------ limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_CHAT_PER_MINUTE: int = 30
    RATE_LIMIT_UPLOAD_PER_MINUTE: int = 20

    # ------------------------------------------------------ web search tool
    WEB_SEARCH_ENABLED: bool = False
    TAVILY_API_KEY: str | None = None

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
