import sys
import os
import asyncio
import uuid
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from .shared import llm
from .state import SupervisorState, MemoryDecision
from .prompts import ORCHESTRATOR_PROMPT, MEMORY_PROMPT
from langgraph.store.base import BaseStore
from langchain_core.callbacks import adispatch_custom_event
import time

# ── Dynamic path handling ────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

try:
    from agents.research_pipeline import graph as research_graph
    from core.search import TavilyWebSearch
except ImportError as e:
    research_graph = None
    TavilyWebSearch = None

# Structured-output LLM for memory extraction
memory_extractor = llm.with_structured_output(MemoryDecision)

# Valid research modes
_VALID_MODES = {"INTERVIEW_INTEL", "JOB_SCENARIO", "ACADEMIC_HELP"}
_MODE_MAP = {
    "INTERVIEW_INTEL": "interview_intel",
    "JOB_SCENARIO":    "job_scenario",
    "ACADEMIC_HELP":   "academic_help",
}


# ─────────────────────────────────────────────────────────────────────────────
# ORCHESTRATOR NODE  (was: supervisor_router_node)
# ─────────────────────────────────────────────────────────────────────────────

async def orchestrator_node(state: SupervisorState):
    """
    Analyses the user's message and decides:
      - next_node    : "research" | "quick_search" | "chat"
      - research_mode: one of the three pipeline modes (only when research)
    """
    try:
        # API-level forced mode override
        forced = state.get("forced_mode")
        if forced and forced != "auto":
            # forced can be  "research:interview_intel" | "quick_search" | "chat"
            if ":" in forced:
                _, mode_raw = forced.split(":", 1)
                mode = _MODE_MAP.get(mode_raw.upper(), "academic_help")
                return {"next_node": "research", "research_mode": mode}
            return {"next_node": forced, "research_mode": None}

        messages = state["messages"]
        last_msg = messages[-1].content

        response = await llm.ainvoke(
            [HumanMessage(content=ORCHESTRATOR_PROMPT.format(user_message=last_msg))]
        )

        decision = response.content.strip().upper()

        # Parse RESEARCH:<MODE>  or  QUICK_SEARCH / CHAT
        if decision.startswith("RESEARCH:"):
            mode_raw = decision.split(":", 1)[1].strip()
            if mode_raw in _VALID_MODES:
                return {
                    "next_node": "research",
                    "research_mode": _MODE_MAP[mode_raw],
                }
            # Unrecognised mode → default to academic_help
            return {"next_node": "research", "research_mode": "academic_help"}

        if decision == "QUICK_SEARCH":
            return {"next_node": "quick_search", "research_mode": None}

        return {"next_node": "chat", "research_mode": None}

    except Exception:
        return {"next_node": "chat", "research_mode": None}


# ─────────────────────────────────────────────────────────────────────────────
# RESEARCH NODE  (unified bridge to the single research_pipeline subgraph)
# ─────────────────────────────────────────────────────────────────────────────

async def research_node(state: SupervisorState, config: RunnableConfig):
    """
    Execution bridge to the unified ResearchPipeline.
    Passes research_mode so the pipeline uses the correct prompt strategy.
    """
    if not research_graph:
        return {"subgraph_output": "Error: Research pipeline not available."}

    mode = state.get("research_mode", "academic_help")
    user_message = state["messages"][-1].content

    inputs = {
        "user_prompt":        user_message,
        "research_mode":      mode,
        "clarification":      {},
        "needs_clarification": False,
        "_questions":         [],
        "subqueries":         [],
        "hits":               [],
        "pages":              [],
        "reflect_pass":       0,
        "report_markdown":    "",
    }

    res = await research_graph.ainvoke(inputs, config=config)

    if res.get("needs_clarification"):
        questions = res.get("_questions", ["Could you provide more details?"])
        report = (
            "I need a bit more information to provide a high-quality report. "
            "Could you please clarify:\n"
            + "\n".join(f"- {q}" for q in questions)
        )
    else:
        report = res.get("report_markdown", "Failed to generate a report.")

    return {
        "subgraph_output": report,
        "messages": [AIMessage(content=report)],
    }


# ─────────────────────────────────────────────────────────────────────────────
# QUICK SEARCH NODE  (was: web_search_node)
# ─────────────────────────────────────────────────────────────────────────────

async def quick_search_node(state: SupervisorState):
    """Fast, single-turn web lookup via Tavily for simple factual questions."""
    last_msg = state["messages"][-1].content
    results = []

    if TavilyWebSearch:
        try:
            client = TavilyWebSearch()
            data = await client.search(last_msg, max_results=5)
            results = data.get("results", [])
        except Exception:
            results = []

    if not results:
        return {
            "subgraph_output": (
                "I couldn't find relevant information on the web right now. "
                "Try rephrasing your question or ask me directly."
            )
        }

    context_str = ""
    for idx, r in enumerate(results, 1):
        context_str += (
            f"Source {idx}: {r.get('title')}\n"
            f"URL: {r.get('url')}\n"
            f"Content: {r.get('content')}\n\n"
        )

    prompt = (
        f"You are a helpful assistant.\n"
        f"User Question: {last_msg}\n\n"
        f"Search Results (via Tavily):\n{context_str}\n"
        f"Instructions:\n"
        f"- Answer the question concisely based on the results.\n"
        f"- Cite sources using [idx] format.\n"
        f"- Provide the final answer only."
    )

    response = await llm.ainvoke([HumanMessage(content=prompt)])
    sources_txt = "\n\n**Sources:**\n" + "\n".join(
        f"[{i+1}] {r.get('url')}" for i, r in enumerate(results)
    )

    return {
        "subgraph_output": response.content + sources_txt,
        "search_results":  results,
        "messages":        [AIMessage(content=response.content + sources_txt)],
    }


# ─────────────────────────────────────────────────────────────────────────────
# CHAT NODE
# ─────────────────────────────────────────────────────────────────────────────

async def chat_node(state: SupervisorState):
    """Conversational fallback for greetings, guidance, and vague queries."""
    last_msg = state["messages"][-1].content

    prompt = (
        f"You are ResearchOrchestra, a helpful career and academic research assistant.\n"
        f"A student sent a message that doesn't require a full research report or web search.\n\n"
        f"Student message: {last_msg}\n\n"
        f"Respond helpfully and conversationally. "
        f"If they seem unsure what to ask, guide them toward:\n"
        f"- Interview Prep (company + role)\n"
        f"- Job Scenario Analysis (role or industry)\n"
        f"- Academic Deep-Dive (topic or subject)"
    )

    response = await llm.ainvoke([HumanMessage(content=prompt)])
    return {
        "subgraph_output": response.content,
        "messages":        [AIMessage(content=response.content)],
    }


# ─────────────────────────────────────────────────────────────────────────────
# CONTEXT PERSIST NODE  (was: remember_node)
# ─────────────────────────────────────────────────────────────────────────────

async def context_persist_node(state: SupervisorState, config: RunnableConfig, *, store: BaseStore):
    """Persists new user facts discovered in this interaction to long-term memory."""
    user_id = config.get("configurable", {}).get("user_id", "default_user")
    ns_details = ("user", user_id, "details")

    # Fetch existing memories
    existing_text = ""
    if store:
        try:
            existing_items = await asyncio.to_thread(store.search, ns_details)
            existing_text = (
                "\n".join(it.value.get("data", "") for it in existing_items)
                if existing_items else ""
            )
        except Exception:
            pass

    # Build interaction context
    last_user_msg = ""
    for m in reversed(state["messages"]):
        if isinstance(m, HumanMessage):
            last_user_msg = m.content
            break

    interaction_content = (
        f"User: {last_user_msg}\n"
        f"Agent Output: {state.get('subgraph_output', '')}"
    )

    # Extract and store new memories
    try:
        decision: MemoryDecision = await memory_extractor.ainvoke(
            [
                SystemMessage(content=MEMORY_PROMPT.format(user_details_content=existing_text)),
                {"role": "user", "content": interaction_content},
            ]
        )

        if decision.should_write:
            for mem in decision.memories:
                if mem.is_new and mem.text and store:
                    await asyncio.to_thread(
                        store.put, ns_details, str(uuid.uuid4()), {"data": mem.text}
                    )
    except Exception:
        pass

    return {}


# ─────────────────────────────────────────────────────────────────────────────
# SESSION ARCHIVER NODE  (was: summarize_node)
# ─────────────────────────────────────────────────────────────────────────────

async def session_archiver_node(state: SupervisorState, config: RunnableConfig, *, store: BaseStore):
    """
    Short-term memory management. Archives conversation segments to LTM
    in windows of 40 messages so the context window stays lean.
    """
    messages = state["messages"]
    last_summary_idx = state.get("last_summary_idx", 0)
    current_len = len(messages)
    WINDOW_SIZE = 40

    if current_len - last_summary_idx < WINDOW_SIZE:
        return {}

    chunk = messages[last_summary_idx:current_len]

    await adispatch_custom_event(
        "user_event",
        {"type": "summary_update", "status": "Archiving conversation segment to long-term memory..."},
        config=config,
    )

    transcript = ""
    for m in chunk:
        role = "AI" if isinstance(m, AIMessage) else "User"
        transcript += f"{role}: {m.content}\n"

    prompt = (
        f"Analyse the following conversation segment and extract key insights, outcomes, and context.\n\n"
        f"Conversation Segment:\n{transcript}\n\n"
        f"Instructions:\n"
        f"1. Summarise the main topics discussed and decisions made.\n"
        f"2. Keep it concise but information-dense.\n"
        f"3. This summary will be stored in long-term memory to preserve global context."
    )

    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        segment_summary = response.content

        user_id = config.get("configurable", {}).get("user_id", "default_user")
        ns_summaries = ("user", user_id, "summaries")
        key = f"summary_{int(time.time())}"

        if store:
            await asyncio.to_thread(store.put, ns_summaries, key, {"data": segment_summary})

        return {"last_summary_idx": current_len, "summary": ""}
    except Exception:
        return {"last_summary_idx": current_len}
