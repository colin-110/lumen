"""Optional web search fallback via the Tavily API.

Only used when a document search comes back empty/low-confidence and
`WEB_SEARCH_ENABLED` + `TAVILY_API_KEY` are set. We call a real search API
over HTTP rather than scraping a search engine's HTML (which is what the
original `duckduckgo-search` dependency did) — scraping breaks silently
whenever the target site changes markup, which is a bad failure mode for a
"production-grade" tool.
"""

from __future__ import annotations

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"


async def web_search(query: str, max_results: int = 4) -> list[dict[str, str]]:
    if not (settings.WEB_SEARCH_ENABLED and settings.TAVILY_API_KEY):
        return []
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.post(
                TAVILY_URL,
                json={
                    "api_key": settings.TAVILY_API_KEY,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", "")}
            for r in data.get("results", [])
        ]
    except Exception:
        logger.warning("Web search failed", exc_info=True)
        return []
