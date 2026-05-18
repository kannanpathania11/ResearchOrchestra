"""
Sub-agent implementations for ResearchOrchestra.

Each agent is a self-contained LangGraph graph built from first principles:
    START → agent (LLM with bound tools) → tools (ToolNode) → agent → … → END

This avoids any prebuilt abstractions (create_react_agent is intentionally not used)
and gives full control over the agent loop, making it production-grade and future-proof.

All four agents share the same web_search tool but operate under different
system prompts and domain expertise.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import List

from langchain_core.messages import SystemMessage
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode

# Add backend root to sys.path for cross-directory imports
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from core.llm import llm
from .tools import ALL_TOOLS
from agents.prompts import (
    WEB_SEARCH_AGENT_PROMPT,
    JOB_SCENARIO_AGENT_PROMPT,
    INTERVIEW_INTEL_AGENT_PROMPT,
    ACADEMIC_HELP_AGENT_PROMPT,
)

logger = logging.getLogger(__name__)

# ── Shared tool node (one ToolNode handles execution for all agents) ──────────
_tool_node = ToolNode(ALL_TOOLS)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Agent graph factory
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _build_subagent(system_prompt: str, tools: list):
    """
    Build a tool-calling ReAct-style agent using pure LangGraph primitives.

    Graph structure:
        START → [agent] ─(has tool calls)→ [tools] → [agent] → …
                        ↘(no tool calls)→ END

    Parameters
    ----------
    system_prompt : str
        System message injected at the front of every LLM call.
    tools : list
        LangChain tools available to this agent.
    """
    model = llm.bind_tools(tools)

    async def call_model(state: MessagesState) -> dict:
        """Invoke the LLM with the system prompt prepended to the message history."""
        messages = [SystemMessage(content=system_prompt)] + state["messages"]
        response = await model.ainvoke(messages)
        return {"messages": [response]}

    def should_continue(state: MessagesState) -> str:
        """Route: call tools if the LLM made tool calls, otherwise finish."""
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", ToolNode(tools))

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

    return graph.compile()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Module-level singletons — compiled once at startup, reused for every request
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

web_search_agent     = _build_subagent(WEB_SEARCH_AGENT_PROMPT,     ALL_TOOLS)
job_scenario_agent   = _build_subagent(JOB_SCENARIO_AGENT_PROMPT,   ALL_TOOLS)
interview_intel_agent = _build_subagent(INTERVIEW_INTEL_AGENT_PROMPT, ALL_TOOLS)
academic_help_agent  = _build_subagent(ACADEMIC_HELP_AGENT_PROMPT,  ALL_TOOLS)


# Lookup map used by nodes.py for dynamic dispatch
AGENT_REGISTRY: dict = {
    "web_search":      web_search_agent,
    "job_scenario":    job_scenario_agent,
    "interview_intel": interview_intel_agent,
    "academic_help":   academic_help_agent,
}
"""
Unified Research Pipeline for ResearchOrchestra.

Supports three modes configured via MODE_META:
  - interview_intel  : deep company/role interview preparation report
  - job_scenario     : job market analysis and career outlook report
  - academic_help    : academic deep-dive study guide

Graph: clarify → query_planner → search → fetch → reflect → synthesize
The reflect node may loop back to search once if coverage is insufficient.

Triggered only when Research Mode is ON (research_pipeline_mode=True in the UI).
"""



import logging
import time
from typing import Dict, List

from langchain_core.callbacks import adispatch_custom_event
from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel, Field

from core.llm import llm
from .state import ResearchState
from .tools import node_search, node_fetch

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MODE CONFIGURATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MODE_META: Dict[str, Dict] = {
    "interview_intel": {
        "label":        "Interview Intelligence",
        "clarify_role": "expert Career Interview Consultant",
        "clarify_goal": (
            "ensure you have the correct COMPANY NAME and the JOB ROLE (if applicable). "
            "If the user provides just a company (e.g., 'Google'), ask what role they are "
            "interested in. If they provide both (e.g., 'Software Engineer at Stripe'), no "
            "clarification needed."
        ),
        "clarify_limit": 2,
        "plan_scope": (
            "Interview Intelligence plan with 10-12 distinct web search queries covering:\n"
            "1. Recent Interview Questions for the specific role.\n"
            "2. Hiring Process: Rounds, technical assessments, cultural fit interviews.\n"
            "3. Company Culture & Values: What they look for in candidates.\n"
            "4. Recent News & Projects: What the company is currently working on.\n"
            "5. Tech Stack & Tools used in the relevant department.\n"
            "6. Salary & Benefits for Interns/Entry-level (Glassdoor/Levels.fyi).\n"
            "7. Employee Reviews for New Grads.\n"
            "Include Company Name and Role in every query. Keep queries under 10 words."
        ),
        "plan_max":   12,
        "synth_role": "Senior Career Coach",
        "synth_task": (
            "an EXTREMELY DETAILED Interview Intelligence Report (1000-1500+ lines).\n\n"
            "MANDATORY SECTIONS:\n"
            "1. Interview Strategy Overview\n"
            "2. Predicted Interview Questions (Technical & Behavioral)\n"
            "3. Step-by-Step Hiring Process\n"
            "4. Deep Dive: Company Culture & Values\n"
            "5. Critical Projects & Recent News (to mention in interviews)\n"
            "6. Role-Specific Tech Stack\n"
            "7. Salary Benchmarks & Benefits\n"
            "8. Common Candidate Pitfalls\n"
            "9. Suggested Questions for the Interviewer\n"
            "10. Personalised 3-Day Prep Roadmap\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            "- 1000-1500+ lines. Use paragraphs for deep strategic advice.\n"
            "- Data-driven: prioritise real interview experiences and news from the corpus.\n"
            "- Do not invent questions; base them on recent candidate reports.\n"
            "- h1 (#) for sections, h2 (##) for subsections. Tables for salary/competitor info.\n"
            "- Tone: Empowering, strategic, and practical for a student."
        ),
        "status_plan":  "Drafting Interview Intelligence query plan...",
        "status_synth": "Compiling your personalised Interview Guide...",
        "clarify_init": "Identifying Company & Role...",
    },

    "job_scenario": {
        "label":        "Job Scenario Analysis",
        "clarify_role": "Job Scenario Analyst",
        "clarify_goal": (
            "ensure you have a specific JOB ROLE or INDUSTRY and ideally a LOCATION (optional). "
            "If the student says something vague like 'What is the job market like?', ask what "
            "role they are interested in. If they say 'Data Science in London', no clarification "
            "needed."
        ),
        "clarify_limit": 3,
        "plan_scope": (
            "Job Scenario analysis plan with 6-8 distinct web search queries covering:\n"
            "1. Hiring Trends: Current volume of job openings, growth rate.\n"
            "2. In-Demand Skills: Most requested technical and soft skills in 2026.\n"
            "3. Salary Benchmarks: Entry-level, junior, and mid-level pay by location.\n"
            "4. Top Employers: Companies currently hiring most for this role.\n"
            "5. Educational Requirements: Degree trends, certification value.\n"
            "6. Market Competition: Number of applicants per opening, saturation.\n"
            "Be specific (include role names and years). Keep queries under 10 words."
        ),
        "plan_max":   8,
        "synth_role": "Senior Job Scenario Analyst",
        "synth_task": (
            "a comprehensive Job Scenario Analysis Report (~500+ lines).\n\n"
            "MANDATORY SECTIONS:\n"
            "1. Title & Executive Summary\n"
            "2. Current Hiring Sentiment\n"
            "3. Skill Gap Analysis: What students have vs. what employers want.\n"
            "4. Salary Landscape: Entry-level to Senior (Markdown table).\n"
            "5. Geographic Hotspots: Top cities/regions for this role.\n"
            "6. Industry Breakdown: Which sectors are hiring (Tech, Finance, Health, etc.).\n"
            "7. Future Outlook: Impact of AI/Automation on this role over the next 5 years.\n"
            "8. Educational ROI: Best degrees/certifications for this path.\n"
            "9. Top 10 Active Employers for this Role.\n"
            "10. Conclusion & Strategic Career Advice.\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            "- 500+ lines. Use paragraphs for deep analysis.\n"
            "- Data-driven: prioritise salary numbers and hiring percentages from corpus.\n"
            "- Do not invent data. Cite every fact as [x].\n"
            "- Tone: Professional, data-heavy, but encouraging for students."
        ),
        "status_plan":  "Drafting Job Scenario analysis query plan...",
        "status_synth": "Synthesising job market dynamics report...",
        "clarify_init": "Analysing Job Market Topic...",
    },

    "academic_help": {
        "label":        "Academic Deep-Dive",
        "clarify_role": "Academic Help Assistant",
        "clarify_goal": (
            "identify if the topic is specific enough for a high-quality study guide. "
            "If the topic is too broad (e.g., 'Physics'), ask for a specific sub-topic or exam "
            "level (e.g., 'Quantum Mechanics for AP Physics'). If it is specific (e.g., "
            "'Transformer architectures in NLP'), no clarification needed."
        ),
        "clarify_limit": 3,
        "plan_scope": (
            "academic research plan with 4-8 distinct web search queries covering:\n"
            "1. Academic Depth: Use terms like 'fundamentals', 'advanced concepts', 'theoretical "
            "framework'.\n"
            "2. Current Research: Recent papers, case studies, or breakthroughs (2024-2026).\n"
            "3. Practical Applications: How this topic is used in the real world/industry.\n"
            "4. Exam Focus: Common questions or complex areas often tested in this subject."
        ),
        "plan_max":   8,
        "synth_role": "Senior Academic Researcher",
        "synth_task": (
            "a comprehensive Deep-Dive Study Guide (~300-500 lines).\n\n"
            "MANDATORY SECTIONS:\n"
            "1. Title & Executive Summary\n"
            "2. Fundamentals & Core Concepts\n"
            "3. Advanced Theoretical Framework\n"
            "4. Practical Real-World Applications\n"
            "5. Recent Breakthroughs & Research Trends (2024-2026)\n"
            "6. Case Studies & Examples\n"
            "7. Frequently Asked Questions (Exam Focus)\n"
            "8. Summary Cheat Sheet (Key formulas, dates, or terms)\n"
            "9. Further Reading & Recommended Resources\n"
            "10. Conclusion & Learning Path Recommendations\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            "- 300+ lines of markdown. Expand on details — this is for students to learn from.\n"
            "- Do not invent data. Cite every fact as [x].\n"
            "- Use LaTeX-style notation if applicable for formulas.\n"
            "- Tone: Educational, clear, structured, and academic."
        ),
        "status_plan":  "Drafting Academic Research query plan...",
        "status_synth": "Compiling your Comprehensive Study Guide...",
        "clarify_init": "Analysing Academic Topic...",
    },
}


def _meta(state: ResearchState) -> Dict:
    return MODE_META.get(state.get("research_mode", "academic_help"), MODE_META["academic_help"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STRUCTURED OUTPUT SCHEMAS  (replaces fragile regex parsing)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ClarificationResult(BaseModel):
    needs: bool = Field(description="True if clarification is required before proceeding")
    questions: List[str] = Field(
        default_factory=list,
        description="Short clarifying questions to ask the user (empty when needs=False)",
    )


class ReflectResult(BaseModel):
    sufficient: bool = Field(description="True if coverage is sufficient for synthesis")
    extra_queries: List[str] = Field(
        default_factory=list,
        description="Up to 3 supplementary search queries if coverage is insufficient",
    )


_clarify_extractor = llm.with_structured_output(ClarificationResult)
_reflect_extractor = llm.with_structured_output(ReflectResult)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# NODE 1 — CLARIFY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def node_clarify(state: ResearchState) -> ResearchState:
    m = _meta(state)
    await adispatch_custom_event("research_update", {"message": m["clarify_init"]})

    prior = state.get("prior_context", "").strip()

    # Build the prior-context section of the prompt.
    # If prior Q&A exists the LLM is instructed to NEVER ask again.
    prior_section = ""
    if prior:
        prior_section = (
            f"\n\n--- PRIOR CONVERSATION HISTORY ---\n{prior}\n"
            "--- END OF HISTORY ---\n\n"
            "CRITICAL RULE: The history above shows what the user has already told you. "
            "If you can see that clarifying questions were ALREADY asked (by an Assistant turn) "
            "AND the user replied with answers, you MUST set needs=false immediately. "
            "Do NOT ask for information the user has already provided. "
            "Synthesise their prior answers into the research plan instead.\n"
        )

    prompt = (
        f"You are an {m['clarify_role']} at ResearchOrchestra.\n"
        f"Today's Date: {time.strftime('%Y-%m-%d')}\n"
        f"Current User Input: \"\"\"{state['user_prompt']}\"\"\"\n"
        f"{prior_section}\n"
        f"Your goal is to {m['clarify_goal']}\n\n"
        f"Ask at most {m['clarify_limit']} short questions ONLY if this is the very first "
        f"message and the topic is genuinely too vague to proceed. "
        f"If the input is already specific enough OR prior Q&A exists, set needs=false and questions=[]."
    )

    result: ClarificationResult = await _clarify_extractor.ainvoke(prompt)
    needs = result.needs and bool(result.questions)

    logger.debug(
        "node_clarify: mode=%s needs=%s questions=%s prior_context_chars=%d",
        state.get("research_mode"), needs, result.questions, len(prior),
    )

    if needs:
        await adispatch_custom_event(
            "research_update",
            {"message": "Clarification needed", "questions": result.questions},
        )
    else:
        await adispatch_custom_event(
            "research_update", {"message": "Topic confirmed. Moving to query planning."}
        )

    return {
        **state,
        "needs_clarification": needs,
        "_questions":          result.questions if needs else [],
        "reflect_pass":        0,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# NODE 2 — QUERY PLANNER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def node_query_planner(state: ResearchState) -> ResearchState:
    m = _meta(state)
    await adispatch_custom_event("research_update", {"message": m["status_plan"]})

    clar = (
        "\n".join(f"- {k}: {v}" for k, v in state["clarification"].items())
        if state.get("clarification")
        else "(none)"
    )

    prompt = (
        f"Create a {m['plan_scope']}\n\n"
        f"Today's Date: {time.strftime('%Y-%m-%d')}\n"
        f"User Request: {state['user_prompt']}\n"
        f"Clarifications: {clar}\n\n"
        f"Return one query per line, no numbering, no bullets."
    )

    msg = await llm.ainvoke(prompt)
    queries = [q.strip("- ").strip() for q in msg.content.splitlines() if q.strip()][: m["plan_max"]]

    await adispatch_custom_event(
        "research_update",
        {"message": f"Query plan ready — {len(queries)} targeted searches queued.", "queries": queries},
    )
    return {**state, "subqueries": queries}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# NODE 3 — REFLECT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MAX_REFLECT_PASSES = 1


async def node_reflect(state: ResearchState) -> ResearchState:
    """
    Self-critique node. Checks whether fetched pages give enough coverage
    to write a high-quality report. Triggers at most one supplementary search round.
    """
    pages = state.get("pages", [])
    reflect_pass = state.get("reflect_pass", 0)

    await adispatch_custom_event(
        "research_update",
        {"message": f"Reflecting on search coverage ({len(pages)} pages fetched)..."},
    )

    if reflect_pass >= MAX_REFLECT_PASSES or len(pages) >= 6:
        await adispatch_custom_event(
            "research_update", {"message": "Coverage sufficient. Proceeding to synthesis."}
        )
        return {**state, "reflect_pass": reflect_pass}

    snippet = "\n".join(
        f"- {p.get('title', 'Untitled')} ({p.get('url', '')})" for p in pages[:10]
    )
    prompt = (
        f"You are a research quality reviewer.\n"
        f"Research topic: {state['user_prompt']}\n"
        f"Mode: {state.get('research_mode', 'unknown')}\n"
        f"Pages fetched so far:\n{snippet}\n\n"
        f"Is the coverage sufficient for a comprehensive, data-rich report? "
        f"If not, provide up to 3 additional specific search queries to fill the gap."
    )

    result: ReflectResult = await _reflect_extractor.ainvoke(prompt)

    if result.sufficient or not result.extra_queries:
        await adispatch_custom_event(
            "research_update", {"message": "Coverage verified. Proceeding to synthesis."}
        )
        return {**state, "reflect_pass": reflect_pass}

    extra = result.extra_queries[:3]
    await adispatch_custom_event(
        "research_update",
        {"message": f"Coverage gap detected. Running {len(extra)} supplementary searches...",
         "queries": extra},
    )
    return {
        **state,
        "subqueries":         extra,
        "hits":               [],
        "reflect_pass":       reflect_pass + 1,
        "_needs_extra_search": True,
    }


def _reflect_router(state: ResearchState) -> str:
    return "search" if state.get("_needs_extra_search") else "synthesize"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# NODE 4 — SYNTHESIZE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def node_synthesize(state: ResearchState) -> ResearchState:
    m = _meta(state)
    logger.info(
        "node_synthesize: mode=%s pages=%d subqueries=%d",
        state.get("research_mode"), len(state.get("pages", [])), len(state.get("subqueries", [])),
    )
    await adispatch_custom_event("research_update", {"message": m["status_synth"]})

    pages = state.get("pages", [])
    sources_text = "\n".join(
        f"[{i}] {p.get('title') or p.get('url')} - ({p['url']})"
        for i, p in enumerate(pages, start=1)
    )
    corpus_text = "\n".join(
        f"### Source {i}\nURL: {p.get('url')}\nTitle: {p.get('title')}\n\n"
        f"{(p.get('text') or '')[:3000]}\n"
        for i, p in enumerate(pages, start=1)
    )

    prompt = (
        f"You are a {m['synth_role']} at ResearchOrchestra. "
        f"Write {m['synth_task']}\n\n"
        f"Today's Date: {time.strftime('%Y-%m-%d')}\n"
        f"User Request: \"\"\"{state['user_prompt']}\"\"\"\n\n"
        f"Sources:\n{sources_text}\n\n"
        f"Corpus:\n{corpus_text}"
    )

    report_chunks: List[str] = []
    async for chunk in llm.astream(prompt):
        piece = chunk.content or ""
        report_chunks.append(piece)
        await adispatch_custom_event("report_token", {"content": piece})

    report = "".join(report_chunks)
    report += "\n\n## Referenced Sources\n" + "\n".join(
        f"{i}. [{p.get('title') or p.get('url')}]({p.get('url', '#')})"
        for i, p in enumerate(pages, start=1)
    )
    return {**state, "report_markdown": report}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GRAPH ASSEMBLY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

research_builder = StateGraph(ResearchState)

research_builder.add_node("clarify",       node_clarify)
research_builder.add_node("query_planner", node_query_planner)
research_builder.add_node("search",        node_search)
research_builder.add_node("fetch",         node_fetch)
research_builder.add_node("reflect",       node_reflect)
research_builder.add_node("synthesize",    node_synthesize)

research_builder.add_edge(START, "clarify")

research_builder.add_conditional_edges(
    "clarify",
    lambda s: "query_planner" if not s["needs_clarification"] else END,
    {"query_planner": "query_planner", END: END},
)

research_builder.add_edge("query_planner", "search")
research_builder.add_edge("search",        "fetch")
research_builder.add_edge("fetch",         "reflect")

research_builder.add_conditional_edges(
    "reflect",
    _reflect_router,
    {"search": "search", "synthesize": "synthesize"},
)

research_builder.add_edge("synthesize", END)

research_graph = research_builder.compile()
from langgraph.graph import StateGraph, START, END

from .state import SupervisorState
from .nodes import (
    orchestrator_node,
    research_node,
    web_search_node,
    job_scenario_node,
    interview_intel_node,
    academic_help_node,
    chat_node,
    context_persist_node,
    session_archiver_node,
)

# ── Build the Supervisor (Orchestrator) Graph ────────────────────────────────
supervisor_builder = StateGraph(SupervisorState)

# 1. Nodes
supervisor_builder.add_node("orchestrator",    orchestrator_node)
supervisor_builder.add_node("research",        research_node)       # deep-research pipeline (Research Mode)
supervisor_builder.add_node("web_search",      web_search_node)     # general live-web queries
supervisor_builder.add_node("job_scenario",    job_scenario_node)   # job market analysis
supervisor_builder.add_node("interview_intel", interview_intel_node) # interview preparation
supervisor_builder.add_node("academic_help",   academic_help_node)  # study plans & learning
supervisor_builder.add_node("chat",            chat_node)           # conversational fallback
supervisor_builder.add_node("context_persist", context_persist_node)
supervisor_builder.add_node("session_archiver", session_archiver_node)

# 2. Entry point
supervisor_builder.add_edge(START, "orchestrator")

# 3. Orchestrator routes to the appropriate worker
supervisor_builder.add_conditional_edges(
    "orchestrator",
    lambda state: state["next_node"],
    {
        "research":       "research",
        "web_search":     "web_search",
        "job_scenario":   "job_scenario",
        "interview_intel": "interview_intel",
        "academic_help":  "academic_help",
        "chat":           "chat",
    },
)

# 4. All workers converge → context_persist → session_archiver → END
for worker in ("research", "web_search", "job_scenario", "interview_intel", "academic_help", "chat"):
    supervisor_builder.add_edge(worker, "context_persist")

supervisor_builder.add_edge("context_persist",  "session_archiver")
supervisor_builder.add_edge("session_archiver", END)

# Compiled without persistence — used for visualisation and testing.
# Production use goes through database.py which compiles with checkpointer + store.
supervisor_graph = supervisor_builder.compile()
