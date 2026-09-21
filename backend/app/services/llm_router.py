"""LiteLLM Router: one alias ("lumen") backed by every configured model
as a separate deployment. This is litellm's documented pattern for
automatic failover — when the active deployment errors or times out, the
Router opens a cooldown on it and retries the request against the next
deployment in the list, all inside a single `acompletion` call.

That automatic failover only actually fires for 429s and 5xx, though -
litellm deliberately re-raises most 4xx (auth errors included) straight
through the streaming path without trying another deployment, on the
reasoning that a broken-credentials error on one deployment probably means
the same on the next. True for two deployments of the *same* provider;
false for our case, where the fallback is a different provider entirely
with independent credentials. agent.py's generation step handles that gap
itself with a manual retry loop across PRIMARY_MODEL + FALLBACK_MODELS,
calling litellm directly rather than through the Router for that hop -
see the comment there for how this was actually confirmed, not assumed.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from app.core.config import settings

if TYPE_CHECKING:  # import cost is real (see below); keep it out of runtime
    from litellm import Router

logger = logging.getLogger(__name__)

MODEL_ALIAS = "lumen"


def api_key_for(model: str) -> str | None:
    if model.startswith("gemini/"):
        return settings.GEMINI_API_KEY
    if model.startswith("groq/"):
        return settings.GROQ_API_KEY
    if model.startswith("claude") or model.startswith("anthropic/"):
        return settings.ANTHROPIC_API_KEY
    if model.startswith("ollama"):
        return None
    return settings.OPENAI_API_KEY  # gpt-*, and openai-compatible by default


def _build_model_list() -> list[dict]:
    candidates = [settings.PRIMARY_MODEL, *settings.FALLBACK_MODELS]
    deployments = []
    seen = set()
    for model in candidates:
        if not model or model in seen:
            continue
        seen.add(model)
        litellm_params: dict = {"model": model}
        api_key = api_key_for(model)
        if api_key:
            litellm_params["api_key"] = api_key
        elif model.startswith("ollama"):
            litellm_params["api_base"] = settings.OLLAMA_API_BASE or "http://localhost:11434"
        else:
            logger.warning("No API key configured for model %s; it will fail if selected", model)
        deployments.append({"model_name": MODEL_ALIAS, "litellm_params": litellm_params})

    if not deployments:
        # Always register something so failures are a clear "no API key" error
        # at call time rather than an empty-router crash at import time.
        deployments.append(
            {"model_name": MODEL_ALIAS, "litellm_params": {"model": settings.PRIMARY_MODEL}}
        )
    return deployments


_router: Router | None = None
# The app warms the router on a background thread at startup while requests
# are already being served, so two callers can reach the build concurrently.
# Same double-checked pattern the embedding models use in services/embeddings.py.
_lock = threading.Lock()


def get_router() -> Router:
    """Build (once) and return the shared Router.

    `litellm` is imported here rather than at module scope on purpose: it
    measured 8.9s and ~135MB RSS to import, which is ~70% of this app's
    total import time, and it pulls in `litellm.proxy._types` (1.5s by
    itself) for a proxy server this project doesn't run. Importing it
    eagerly meant every process paid that before serving anything — including
    `/health`, auth and document endpoints that never reach an LLM, and the
    Celery worker, which has no LLM path at all.

    Deferring it moves the cost to the first generation call, which is
    already network-bound and slow enough that ~9s of one-time import is
    not the dominant term. The module-level `litellm` settings moved in here
    for the same reason; they only need to be true before the first
    completion, and every completion goes through this function.
    """
    global _router
    if _router is None:
        with _lock:
            if _router is None:
                import litellm
                from litellm import Router

                litellm.drop_params = True  # ignore provider-unsupported kwargs instead of raising
                litellm.suppress_debug_info = True

                model_list = _build_model_list()
                logger.info(
                    "LLM router configured with %d deployment(s): %s",
                    len(model_list),
                    [d["litellm_params"]["model"] for d in model_list],
                )
                _router = Router(
                    model_list=model_list,
                    num_retries=settings.LLM_MAX_RETRIES,
                    timeout=settings.LLM_TIMEOUT,
                    allowed_fails=1,
                    cooldown_time=30,
                    retry_after=1,
                )
    return _router
