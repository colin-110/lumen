from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.api import api_router
from app.core.config import settings
from app.core.logging import configure_logging, request_id_ctx
from app.services.qdrant_client import init_qdrant

configure_logging()
logger = logging.getLogger(__name__)

REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "path", "status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["method", "path"]
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Starting %s (env=%s, providers=%s)",
        settings.PROJECT_NAME,
        settings.ENVIRONMENT,
        settings.configured_providers or "NONE CONFIGURED",
    )
    try:
        init_qdrant()
    except Exception:
        logger.error("Qdrant initialization failed; retrieval will error until it recovers", exc_info=True)

    from app.services.storage import storage

    if not await storage.ensure_bucket():
        logger.error("Object storage bucket unavailable; uploads will fail until it recovers")

    # Warm the embedding/reranker models so the first real chat request
    # doesn't eat a multi-second model-load penalty.
    try:
        from app.services import embeddings

        embeddings.warm_up()
    except Exception:
        logger.error("Embedding model warm-up failed; will lazy-load on first use", exc_info=True)

    yield
    logger.info("Shutting down %s", settings.PROJECT_NAME)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        description="API for the Lumen document assistant platform.",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        req_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        token = request_id_ctx.set(req_id)
        start = time.perf_counter()
        route_path = request.url.path
        try:
            response = await call_next(request)
        except Exception:
            REQUEST_COUNT.labels(request.method, route_path, "500").inc()
            raise
        finally:
            request_id_ctx.reset(token)
        duration = time.perf_counter() - start
        REQUEST_COUNT.labels(request.method, route_path, response.status_code).inc()
        REQUEST_LATENCY.labels(request.method, route_path).observe(duration)
        response.headers["X-Request-ID"] = req_id
        response.headers["X-Process-Time-Ms"] = f"{duration * 1000:.1f}"
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        logger.warning("HTTP %s on %s: %s", exc.status_code, request.url.path, exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled error on %s: %s", request.url.path, exc, exc_info=True)
        return JSONResponse(status_code=500, content={"detail": "An unexpected error occurred."})

    if settings.BACKEND_CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[str(o) for o in settings.BACKEND_CORS_ORIGINS],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID", "X-Process-Time-Ms"],
        )

    app.include_router(api_router, prefix=settings.API_V1_STR)

    from app.api.v1.endpoints.metrics import metrics_app

    app.mount("/metrics", metrics_app)

    @app.get("/health", tags=["health"])
    async def health_check():
        return {"status": "ok", "version": settings.VERSION, "environment": settings.ENVIRONMENT}

    return app


app = create_app()
