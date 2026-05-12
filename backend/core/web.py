import re
from typing import List, Dict, Any

import httpx
from bs4 import BeautifulSoup
from readability import Document
from tavily import TavilyClient
from langchain_core.callbacks.manager import adispatch_custom_event

from core.state import ResearchState

_tavily = TavilyClient()


async def web_search(query: str, k: int = 5) -> List[Dict[str, Any]]:
    res = _tavily.search(query=query, max_results=k)
    hits = []
    for r in res.get("results", []):
        hits.append({
            "url": r.get("url"),
            "title": r.get("title"),
            "snippet": r.get("content"),
            "score": r.get("score", 0),
        })
    return hits


async def fetch_page(url: str, timeout: int = 15) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(
            timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}
        ) as client:
            response = await client.get(url, follow_redirects=True)
            html = response.text
            doc = Document(html)
            title = doc.short_title()
            cleaned = doc.summary(html_partial=True)
            soup = BeautifulSoup(cleaned, "html.parser")
            text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
            return {"url": url, "title": title, "text": text[:120000]}
    except Exception as e:
        return {"url": url, "title": "", "text": f"Error Fetching Page: {str(e)}"}


def dedupe_hits(hits: List[Dict[str, Any]], limit: int = 25) -> List[Dict[str, Any]]:
    seen = set()
    unique = []
    for h in sorted(hits, key=lambda x: x.get("score", 0), reverse=True):
        key = re.sub(r"#.*$", "", (h.get("url") or "").strip())
        if key and key not in seen:
            seen.add(key)
            unique.append(h)
        if len(unique) >= limit:
            break
    return unique


async def node_search(state: ResearchState) -> ResearchState:
    hits: List[Dict[str, Any]] = []

    await adispatch_custom_event(
        "research_update",
        {"message": f"Starting web search for {len(state['subqueries'])} queries..."},
    )

    for q in state["subqueries"]:
        await adispatch_custom_event("research_update", {"message": f"Searching: {q}"})
        try:
            res = await web_search(q, k=5)
            hits.extend(res)
        except Exception as e:
            pass

    hits = dedupe_hits(hits, limit=10)

    await adispatch_custom_event(
        "research_update",
        {"message": f"Search complete. Found {len(hits)} unique results."},
    )

    return {**state, "hits": hits}


async def node_fetch(state: ResearchState) -> ResearchState:
    urls = [h["url"] for h in state["hits"] if h.get("url")]
    pages: List[Dict[str, Any]] = []

    await adispatch_custom_event(
        "research_update", {"message": f"Fetching {len(urls)} pages..."}
    )

    for idx, url in enumerate(urls, start=1):
        await adispatch_custom_event(
            "research_update",
            {"message": f"Fetching {idx}/{len(urls)}: {url}", "url": url},
        )
        page = await fetch_page(url)
        pages.append(page)

    await adispatch_custom_event(
        "research_update", {"message": f"Fetch complete. Processed {len(pages)} pages."}
    )
    return {**state, "pages": pages}
