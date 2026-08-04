"""LiteLLM Router: one alias ("lumen") backed by every configured model
as a separate deployment. This is litellm's documented pattern for
automatic failover — when the active deployment errors or times out, the
Router opens a cooldown on it and retries the request against the next
deployment in the list, all inside a single `acompletion` call. That's a
real fallback chain (e.g. Gemini -> GPT-4o -> Groq), not just a label.
"""

from __future__ import annotations

import logging

import litellm
from litellm import Router

from app.core.config import settings

logger = logging.getLogger(__name__)

litellm.drop_params = True  # ignore provider-unsupported kwargs instead of raising
litellm.suppress_debug_info = True

MODEL_ALIAS = "lumen"


def _api_key_for(model: str) -> str | None:
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
        api_key = _api_key_for(model)
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
        deployments.append({"model_name": MODEL_ALIAS, "litellm_params": {"model": settings.PRIMARY_MODEL}})
    return deployments


_router: Router | None = None


def get_router() -> Router:
    global _router
    if _router is None:
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
