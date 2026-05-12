import os
import asyncio
from typing import Dict, Any
from tavily import TavilyClient


class TavilyWebSearch:
    """Async wrapper around TavilyClient with normalized output."""

    def __init__(self, api_key: str = None, search_depth: str = "advanced"):
        self.api_key = api_key or os.getenv("TAVILY_API_KEY")
        if not self.api_key:
            raise ValueError("TAVILY_API_KEY must be set.")
        self.client = TavilyClient(api_key=self.api_key)
        self.search_depth = search_depth

    async def search(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        try:
            response = await asyncio.to_thread(
                self.client.search,
                query=query,
                max_results=max_results,
                search_depth=self.search_depth,
            )
            normalized = []
            for r in response.get("results", []):
                normalized.append({
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", r.get("snippet", "")),
                })
            return {"results": normalized}
        except Exception as e:
            return {"results": [], "error": str(e)}
