"""
Unit tests for the research pipeline nodes.

Strategy: mock the LLM and web calls so tests run without API keys or network.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agents.research_pipeline import (
    node_clarify,
    node_query_planner,
    node_reflect,
    _reflect_router,
    ClarificationResult,
    ReflectResult,
)
from core.state import ResearchState


def _base_state(**overrides) -> ResearchState:
    state: ResearchState = {
        "user_prompt": "Software Engineer at Google",
        "research_mode": "interview_intel",
        "prior_context": "",
        "clarification": {},
        "needs_clarification": False,
        "_questions": [],
        "subqueries": [],
        "hits": [],
        "pages": [],
        "reflect_pass": 0,
        "report_markdown": "",
    }
    state.update(overrides)
    return state


# ── node_clarify ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_clarify_no_clarification_needed():
    """When the prompt is specific enough, needs_clarification should be False."""
    result = ClarificationResult(needs=False, questions=[])
    with (
        patch("agents.research_pipeline._clarify_extractor") as mock_ext,
        patch("agents.research_pipeline.adispatch_custom_event", new_callable=AsyncMock),
    ):
        mock_ext.ainvoke = AsyncMock(return_value=result)
        state = await node_clarify(_base_state())

    assert state["needs_clarification"] is False
    assert state["_questions"] == []


@pytest.mark.asyncio
async def test_clarify_clarification_needed():
    """When the prompt is vague, clarification questions should be returned."""
    questions = ["What role are you applying for?"]
    result = ClarificationResult(needs=True, questions=questions)
    with (
        patch("agents.research_pipeline._clarify_extractor") as mock_ext,
        patch("agents.research_pipeline.adispatch_custom_event", new_callable=AsyncMock),
    ):
        mock_ext.ainvoke = AsyncMock(return_value=result)
        state = await node_clarify(_base_state(user_prompt="Tell me about Google"))

    assert state["needs_clarification"] is True
    assert state["_questions"] == questions


@pytest.mark.asyncio
async def test_clarify_ignores_clarification_when_prior_context_present():
    """
    If prior Q&A exists and the LLM still says needs=True (edge case),
    but questions list is empty, needs_clarification must be False.
    """
    result = ClarificationResult(needs=True, questions=[])  # contradictory but guarded
    with (
        patch("agents.research_pipeline._clarify_extractor") as mock_ext,
        patch("agents.research_pipeline.adispatch_custom_event", new_callable=AsyncMock),
    ):
        mock_ext.ainvoke = AsyncMock(return_value=result)
        state = await node_clarify(_base_state(prior_context="User: Google\nAssistant: What role?"))

    # needs=True but questions=[] → our guard forces needs_clarification=False
    assert state["needs_clarification"] is False


# ── node_query_planner ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_query_planner_returns_queries():
    """Query planner should split LLM output into a list of search queries."""
    fake_response = MagicMock()
    fake_response.content = "Google SWE interview questions 2025\nGoogle tech stack backend\nGoogle salary SWE entry level"

    with (
        patch("agents.research_pipeline.llm") as mock_llm,
        patch("agents.research_pipeline.adispatch_custom_event", new_callable=AsyncMock),
    ):
        mock_llm.ainvoke = AsyncMock(return_value=fake_response)
        state = await node_query_planner(_base_state())

    assert len(state["subqueries"]) == 3
    assert "Google SWE interview questions 2025" in state["subqueries"]


# ── node_reflect ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reflect_skips_when_enough_pages():
    """Reflection is skipped when 6+ pages are already fetched."""
    pages = [{"url": f"http://example.com/{i}", "title": f"Page {i}", "text": "..."} for i in range(6)]
    with patch("agents.research_pipeline.adispatch_custom_event", new_callable=AsyncMock):
        state = await node_reflect(_base_state(pages=pages))

    assert state.get("_needs_extra_search") is not True


@pytest.mark.asyncio
async def test_reflect_triggers_extra_search_when_coverage_insufficient():
    """Reflection should trigger extra searches when coverage is poor."""
    extra = ["Google SWE interview Reddit 2025", "Google hiring process Glassdoor"]
    result = ReflectResult(sufficient=False, extra_queries=extra)

    with (
        patch("agents.research_pipeline._reflect_extractor") as mock_ext,
        patch("agents.research_pipeline.adispatch_custom_event", new_callable=AsyncMock),
    ):
        mock_ext.ainvoke = AsyncMock(return_value=result)
        state = await node_reflect(_base_state(pages=[{"url": "http://x.com", "title": "x", "text": "x"}]))

    assert state["_needs_extra_search"] is True
    assert state["subqueries"] == extra


# ── _reflect_router ───────────────────────────────────────────────────────────

def test_reflect_router_goes_to_search_when_extra_needed():
    state = _base_state(_needs_extra_search=True)
    assert _reflect_router(state) == "search"


def test_reflect_router_goes_to_synthesize_by_default():
    state = _base_state()
    assert _reflect_router(state) == "synthesize"
