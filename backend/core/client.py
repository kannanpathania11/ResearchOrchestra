"""
Tavily Search Client
====================
Async wrapper around the synchronous TavilyClient with:
  - Singleton-per-API-key (safe at asyncio event-loop level)
  - Exponential-backoff retry  (3 attempts, max 16 s wait)
  - Rate-limit detection and adaptive back-off
  - Normalised result schema  {title, url, content, score}
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from tavily import TavilyClient

logger = logging.getLogger(__name__)

_RATE_LIMIT_SIGNALS = frozenset({"429", "rate limit", "too many requests", "rate_limit"})


def _is_rate_limit(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(sig in msg for sig in _RATE_LIMIT_SIGNALS)


class TavilySearchClient:
    """
    Async Tavily client with retry and singleton caching.

    Usage
    -----
    client = TavilySearchClient()               # reads TAVILY_API_KEY from env
    results = await client.search("my query")   # List[Dict]
    """

    # Class-level cache keyed by resolved API key
    _instances: Dict[str, "TavilySearchClient"] = {}

    def __new__(cls, api_key: Optional[str] = None) -> "TavilySearchClient":
        resolved = api_key or os.getenv("TAVILY_API_KEY", "")
        if not resolved:
            raise ValueError(
                "Tavily API key not found. "
                "Set TAVILY_API_KEY in your environment or pass api_key= explicitly."
            )
        if resolved not in cls._instances:
            instance = super().__new__(cls)
            instance._api_key = resolved
            instance._sync_client = TavilyClient(api_key=resolved)
            cls._instances[resolved] = instance
        return cls._instances[resolved]

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        search_depth: str = "advanced",
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute a web search and return normalised results.

        Returns
        -------
        List of dicts with keys: title, url, content, score.
        Returns an empty list on total failure — never raises to callers.
        """
        kwargs: Dict[str, Any] = {
            "query": query,
            "max_results": max(1, min(max_results, 20)),
            "search_depth": search_depth,
        }
        if include_domains:
            kwargs["include_domains"] = include_domains
        if exclude_domains:
            kwargs["exclude_domains"] = exclude_domains

        raw = await self._search_with_retry(**kwargs)
        return self._normalise(raw)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    async def _search_with_retry(self, **kwargs: Any) -> Dict[str, Any]:
        """Run search with exponential-backoff retry (3 attempts)."""
        for attempt in range(1, 4):
            try:
                return await asyncio.to_thread(self._sync_client.search, **kwargs)
            except Exception as exc:
                is_rate = _is_rate_limit(exc)
                if attempt == 3:
                    logger.error("Tavily search failed after 3 attempts: %s", exc)
                    return {"results": []}

                wait = min(2 ** attempt * (3 if is_rate else 1), 16)
                logger.warning(
                    "Tavily search attempt %d/3 failed (%s). Retrying in %ds…",
                    attempt,
                    "rate limit" if is_rate else str(exc)[:80],
                    wait,
                )
                await asyncio.sleep(wait)

        return {"results": []}

    @staticmethod
    def _normalise(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            {
                "title":   r.get("title", ""),
                "url":     r.get("url", ""),
                "content": r.get("content") or r.get("snippet", ""),
                "score":   float(r.get("score", 0.0)),
            }
            for r in raw.get("results", [])
        ]
