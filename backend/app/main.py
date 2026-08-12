from __future__ import annotations

import asyncio
import logging
import re
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

# Request ids are echoed into every log line and returned in a header, so an
# unvalidated client-supplied value is a log-injection vector (newlines and
# control characters forging log entries) and an unbounded string.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _metric_path(request: Request) -> str:
    """The route *template*, never the concrete URL.

    Prometheus labels must be low-cardinality. Using `request.url.path`
    created a new time series for every document and conversation UUID that
    was ever requested — unbounded series growth that degrades the Prometheus
    server rather than this one, so nothing here would ever surface it.
    Unmatched paths (404s, scans) collapse to a single bucket for the same
    reason.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if path:
        return path
    return "__unmatched__"


def _safe_request_id(raw: str | None) -> str:
    if raw and _REQUEST_ID_RE.match(raw):
        return raw
    return str(uuid.uuid4())


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

    # Warm the LLM router *in the background*. `litellm` is a ~9s import
    # (see services/llm_router.py for why it's no longer imported at module
    # scope), so doing it inline here would just move the startup stall
    # rather than remove it. Off the critical path, /health, auth and the
    # document endpoints are servable in ~3s while this finishes, and a
    # chat arriving after that finds the router already built.
    async def _warm_llm_router() -> None:
        try:
            from app.services.llm_router import get_router

            await asyncio.to_thread(get_router)
            logger.info("LLM router warm")
        except Exception:
            logger.warning("LLM router warm-up failed; will build on first chat", exc_info=True)

    warm_task = asyncio.create_task(_warm_llm_router())

    # The semantic cache marks entries with `expires_at` and filters expired
    # ones out of lookups, but nothing ever deleted them — the collection grew
    # by one vector plus a full answer body per distinct question, forever.
    # This is that missing sweep.
    async def _evict_cache_periodically() -> None:
        from app.services import semantic_cache

        while True:
            try:
                await asyncio.sleep(settings.SEMANTIC_CACHE_SWEEP_SECONDS)
                await semantic_cache.evict_expired()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Semantic cache sweep failed; will retry", exc_info=True)

    sweep_task = asyncio.create_task(_evict_cache_periodically())

    yield

    # Don't let a half-finished import or a sweep outlive the app.
    for task in (warm_task, sweep_task):
        if not task.done():
            task.cancel()
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
        # Only believe an inbound request id when something trustworthy set
        # it, and only if it is well-formed: the value lands in structured
        # logs, where an unvalidated string can forge log entries.
        inbound = request.headers.get("X-Request-ID") if settings.TRUSTED_PROXY_HEADERS else None
        req_id = _safe_request_id(inbound)
        token = request_id_ctx.set(req_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # `request.scope["route"]` is only populated once routing has run,
            # which it has by the time an endpoint raises.
            REQUEST_COUNT.labels(request.method, _metric_path(request), "500").inc()
            raise
        finally:
            request_id_ctx.reset(token)
        duration = time.perf_counter() - start
        route_path = _metric_path(request)
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
