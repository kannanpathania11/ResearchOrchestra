"""
Supervisor graph nodes for ResearchOrchestra.

Routing logic
─────────────
research_pipeline_mode = False  (default / chat mode)
  orchestrator classifies → web_search | job_scenario | interview_intel | academic_help | chat

research_pipeline_mode = True   (UI Research Mode toggle ON)
  orchestrator classifies → research pipeline with the correct mode
"""

from __future__ import annotations

import logging
import os
import sys
import time
import uuid

from langchain_core.callbacks import adispatch_custom_event
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore
from langgraph.types import interrupt
from pydantic import BaseModel, Field
from typing import Literal, Optional

from .state import SupervisorState, MemoryDecision
from .prompts import MEMORY_PROMPT

# Add backend root to sys.path for cross-directory imports
# __file__ = backend/main_agent/nodes.py  →  2× dirname  →  backend/
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from core.llm import llm
from agents.prompts import ORCHESTRATOR_CHAT_PROMPT

logger = logging.getLogger(__name__)


def _format_conversation_history(messages, max_turns: int = 6) -> str:
    """
    Format the last N turns of supervisor conversation for the research pipeline's
    clarify node. This lets the clarify node see whether clarification Q&A has
    already happened and avoid looping.
    """
    relevant = [m for m in messages if isinstance(m, (HumanMessage, AIMessage))]
    recent = relevant[-(max_turns * 2):]
    lines = []
    for m in recent:
        if isinstance(m, HumanMessage):
            lines.append(f"User: {str(m.content)[:400]}")
        elif isinstance(m, AIMessage) and m.content:
            # Truncate long AI responses to just show the gist
            text = str(m.content)[:300]
            lines.append(f"Assistant: {text}{'...' if len(str(m.content)) > 300 else ''}")
    return "\n".join(lines)


# ── Lazy imports (avoids circular imports at module load time) ────────────────
_research_graph = None
_subagent_registry = None


def _get_research_graph():
    global _research_graph
    if _research_graph is None:
        try:
            from agents.graph import research_graph as rg
            _research_graph = rg
        except ImportError as exc:
            logger.error("Could not import research_pipeline: %s", exc)
    return _research_graph


def _get_subagent_registry():
    global _subagent_registry
    if _subagent_registry is None:
        try:
            from agents.graph import AGENT_REGISTRY
            _subagent_registry = AGENT_REGISTRY
        except ImportError as exc:
            logger.error("Could not import subagents: %s", exc)
            _subagent_registry = {}
    return _subagent_registry


# Structured-output LLM for memory extraction
memory_extractor = llm.with_structured_output(MemoryDecision)

# ── Routing maps ──────────────────────────────────────────────────────────────

class RouteDecision(BaseModel):
    next_node: Literal["web_search", "job_scenario", "interview_intel", "academic_help", "chat"] = Field(
        description="The specialist agent to route the user's query to."
    )

_RESEARCH_MODE_MAP = {
    "INTERVIEW_INTEL": "interview_intel",
    "JOB_SCENARIO":    "job_scenario",
    "ACADEMIC_HELP":   "academic_help",
}

_FORCED_NODE_MAP = {
    "web_search":      "web_search",
    "job_scenario":    "job_scenario",
    "interview_intel": "interview_intel",
    "academic_help":   "academic_help",
    "chat":            "chat",
    "quick_search":    "web_search",   # legacy alias
}

# Human-readable delegation messages shown in the UI status bar
_DELEGATION_STATUS = {
    "web_search":      "Web Scout activated — searching the live web...",
    "job_scenario":    "Job Market Analyst engaged — reading the career landscape...",
    "interview_intel": "Interview Intel Agent briefed — compiling insider knowledge...",
    "academic_help":   "Academic Research Agent activated — diving deep into the subject...",
    "chat":            "Research Assistant ready...",
    "research":        "Launching deep research pipeline...",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ORCHESTRATOR NODE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def orchestrator_node(state: SupervisorState, config: RunnableConfig):
    """
    Central router.
      research_pipeline_mode=False → one of four sub-agents or chat fallback.
      research_pipeline_mode=True  → classifies into a deep-research pipeline mode.
    """
    try:
        forced = state.get("forced_mode")
        if forced and forced != "auto":
            if ":" in forced:
                _, mode_raw = forced.split(":", 1)
                mode = _RESEARCH_MODE_MAP.get(mode_raw.upper(), "academic_help")
                await adispatch_custom_event(
                    "research_update",
                    {"message": _DELEGATION_STATUS.get("research", "Launching pipeline...")},
                    config=config,
                )
                return {"next_node": "research", "research_mode": mode}
            node = _FORCED_NODE_MAP.get(forced.lower(), "chat")
            await adispatch_custom_event(
                "research_update",
                {"message": _DELEGATION_STATUS.get(node, "Routing request...")},
                config=config,
            )
            return {"next_node": node, "research_mode": None}

        last_msg = state["messages"][-1].content
        pipeline_mode = state.get("research_pipeline_mode", False)

        if pipeline_mode:
            # Mode is sent explicitly from the frontend — no LLM classifier needed.
            mode = state.get("research_mode") or "academic_help"
            logger.debug("orchestrator → research pipeline, mode=%s", mode)
            await adispatch_custom_event(
                "research_update",
                {"message": _DELEGATION_STATUS.get("research", "Launching pipeline...")},
                config=config,
            )
            return {"next_node": "research", "research_mode": mode}

        router_llm = llm.with_structured_output(RouteDecision)
        decision = await router_llm.ainvoke(
            [HumanMessage(content=ORCHESTRATOR_CHAT_PROMPT.format(user_message=last_msg))]
        )
        node = decision.next_node
        logger.debug("orchestrator → node=%s (structured routing)", node)
        await adispatch_custom_event(
            "research_update",
            {"message": _DELEGATION_STATUS.get(node, "Processing your request...")},
            config=config,
        )
        return {"next_node": node, "research_mode": None}

    except Exception as exc:
        logger.error("orchestrator_node error: %s", exc)
        return {"next_node": "chat", "research_mode": None}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RESEARCH NODE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def research_node(state: SupervisorState, config: RunnableConfig):
    """
    Bridge to the unified deep-research pipeline (Research Mode only).

    Clarification flow (proper LangGraph pattern):
    1. Run the research pipeline.
    2. If clarification is needed, call interrupt() — the supervisor graph
       (which has a checkpointer) pauses here and saves state to PostgreSQL.
    3. The client detects the 'interrupt' SSE event and shows the questions.
    4. On the user's next message the server calls Command(resume=user_answer),
       which continues execution from this exact point.
    5. We re-run the pipeline with the clarification injected into prior_context.
    """
    research_graph = _get_research_graph()
    if not research_graph:
        return {"subgraph_output": "Error: Research pipeline unavailable."}

    prior_context = _format_conversation_history(state["messages"])
    logger.debug("research_node: prior_context length=%d chars", len(prior_context))

    def _build_inputs(extra_context: str = "") -> dict:
        return {
            "user_prompt":         state["messages"][-1].content,
            "research_mode":       state.get("research_mode", "academic_help"),
            "prior_context":       prior_context + extra_context,
            "clarification":       {},
            "needs_clarification": False,
            "_questions":          [],
            "subqueries":          [],
            "hits":                [],
            "pages":               [],
            "reflect_pass":        0,
            "report_markdown":     "",
        }

    res = await research_graph.ainvoke(_build_inputs(), config=config)

    if res.get("needs_clarification"):
        questions = res.get("_questions", ["Could you provide more details?"])
        clarification_message = (
            "I need a bit more information to produce a high-quality report. "
            "Could you clarify:\n" + "\n".join(f"- {q}" for q in questions)
        )

        # Pause the supervisor graph — execution resumes when the client sends
        # Command(resume=user_answer) on the next request for this thread.
        user_answer: str = interrupt({
            "type":      "clarification",
            "questions": questions,
            "message":   clarification_message,
        })

        # Re-run the pipeline with the user's clarification injected
        extra = f"\n\nClarification from user: {user_answer}"
        res = await research_graph.ainvoke(_build_inputs(extra), config=config)

    report = res.get("report_markdown", "Failed to generate a report.")
    return {"subgraph_output": report, "messages": [AIMessage(content=report)]}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SUB-AGENT NODES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _extract_content(msg) -> str:
    content = msg.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


async def _run_subagent(agent_key: str, state: SupervisorState, config: RunnableConfig) -> dict:
    registry = _get_subagent_registry()
    agent = registry.get(agent_key)
    if not agent:
        msg = f"The {agent_key.replace('_', ' ')} specialist is currently unavailable."
        return {"subgraph_output": msg, "messages": [AIMessage(content=msg)]}
    try:
        full_content = ""

        async for event in agent.astream_events(
            {"messages": state["messages"]}, config=config, version="v2"
        ):
            ev = event["event"]

            if ev == "on_tool_start":
                await adispatch_custom_event(
                    "research_update",
                    {"message": "Querying live web sources..."},
                    config=config,
                )

            elif ev == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk:
                    text = chunk.content if isinstance(chunk.content, str) else ""
                    if text:
                        full_content += text
                        await adispatch_custom_event(
                            "report_token", {"content": text}, config=config
                        )

        logger.debug("subagent %s: streamed %d chars", agent_key, len(full_content))

        if not full_content:
            # Fallback: no text was streamed (shouldn't normally happen)
            logger.warning("subagent %s: no tokens streamed, falling back to ainvoke", agent_key)
            result = await agent.ainvoke({"messages": state["messages"]}, config=config)
            full_content = _extract_content(result["messages"][-1])

        return {"subgraph_output": full_content, "messages": [AIMessage(content=full_content)]}
    except Exception as exc:
        logger.error("%s sub-agent error: %s", agent_key, exc)
        msg = "I ran into an issue. Please try again or rephrase your question."
        return {"subgraph_output": msg, "messages": [AIMessage(content=msg)]}


async def web_search_node(state: SupervisorState, config: RunnableConfig):
    return await _run_subagent("web_search", state, config)


async def job_scenario_node(state: SupervisorState, config: RunnableConfig):
    return await _run_subagent("job_scenario", state, config)


async def interview_intel_node(state: SupervisorState, config: RunnableConfig):
    return await _run_subagent("interview_intel", state, config)


async def academic_help_node(state: SupervisorState, config: RunnableConfig):
    return await _run_subagent("academic_help", state, config)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CHAT NODE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def chat_node(state: SupervisorState, config: RunnableConfig):
    """Conversational fallback for greetings, orientation, and general guidance."""
    from .prompts import CHAT_NODE_PROMPT
    prompt = CHAT_NODE_PROMPT.format(
        _TODAY=time.strftime("%Y-%m-%d"),
        user_message=state['messages'][-1].content
    )
    full_content = ""
    async for chunk in llm.astream([HumanMessage(content=prompt)]):
        if isinstance(chunk.content, str) and chunk.content:
            full_content += chunk.content
            await adispatch_custom_event(
                "report_token", {"content": chunk.content}, config=config
            )
    return {"subgraph_output": full_content, "messages": [AIMessage(content=full_content)]}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONTEXT PERSIST NODE
# Runs after every turn. Extracts new user facts and saves to long-term memory.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def context_persist_node(
    state: SupervisorState, config: RunnableConfig, *, store: BaseStore
):
    """
    Persists new user facts to PostgreSQL long-term memory store.

    What it does
    ────────────
    1. Reads existing user memories from store (namespace: user/{user_id}/details).
    2. Feeds the current interaction to the LLM (structured output: MemoryDecision).
    3. LLM extracts atomic facts (target role, location, topics researched, etc.).
    4. Saves only genuinely new facts back to the store.
    These facts persist across ALL future sessions for this user.
    """
    if not store:
        return {}

    user_id = config.get("configurable", {}).get("user_id", "default_user")
    ns_details = ("user", user_id, "details")

    existing_text = ""
    try:
        existing_items = await store.asearch(ns_details)
        if existing_items:
            existing_text = "\n".join(it.value.get("data", "") for it in existing_items)
    except Exception as exc:
        logger.warning("context_persist: failed to read store: %s", exc)

    last_user_msg = next(
        (m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
        "",
    )

    try:
        decision: MemoryDecision = await memory_extractor.ainvoke([
            SystemMessage(content=MEMORY_PROMPT.format(user_details_content=existing_text)),
            {"role": "user", "content": f"User: {last_user_msg}\nAgent: {state.get('subgraph_output', '')}"},
        ])
        if decision.should_write:
            for mem in decision.memories:
                if mem.is_new and mem.text:
                    await store.aput(ns_details, str(uuid.uuid4()), {"data": mem.text})
    except Exception as exc:
        logger.warning("context_persist: memory extraction failed: %s", exc)

    return {}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SESSION ARCHIVER NODE
# Runs after every turn. Archives every 40 messages to long-term memory.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def session_archiver_node(
    state: SupervisorState, config: RunnableConfig, *, store: BaseStore
):
    """
    Summarises and archives 40-message conversation windows to long-term memory.

    What it does
    ────────────
    1. Checks if 10+ new messages have appeared since the last archival.
    2. If yes, takes that chunk, asks the LLM to summarise key topics/decisions.
    3. Saves the summary to store (namespace: user/{user_id}/summaries).
    4. Prevents context-window bloat on very long conversations.
    """
    messages = state["messages"]
    last_idx = state.get("last_summary_idx", 0)
    current_len = len(messages)
    WINDOW = 10

    if current_len - last_idx < WINDOW:
        return {}

    await adispatch_custom_event(
        "user_event",
        {"type": "summary_update", "status": "Archiving conversation to long-term memory…"},
        config=config,
    )

    chunk = messages[last_idx:current_len]
    transcript = "\n".join(
        f"{'AI' if isinstance(m, AIMessage) else 'User'}: {m.content}" for m in chunk
    )

    try:
        response = await llm.ainvoke([HumanMessage(content=(
            "Summarise the following conversation segment. Extract key topics discussed, "
            "decisions made, and important context. Be concise but information-dense — "
            "this goes into long-term memory.\n\n"
            f"Conversation:\n{transcript}"
        ))])

        if store:
            user_id = config.get("configurable", {}).get("user_id", "default_user")
            await store.aput(
                ("user", user_id, "summaries"),
                f"summary_{int(time.time())}",
                {"data": response.content},
            )

        return {"last_summary_idx": current_len, "summary": ""}
    except Exception as exc:
        logger.warning("session_archiver: failed: %s", exc)
        return {"last_summary_idx": current_len}
