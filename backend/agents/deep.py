import re
import time
from typing import List

from langchain_core.callbacks.manager import adispatch_custom_event
from langgraph.graph import StateGraph, START, END
from core.llm import llm
from core.state import ResearchState
from core.web import node_search, node_fetch


async def node_clarify(state: ResearchState) -> ResearchState:
    await adispatch_custom_event("research_update", {"message": "Analyzing Academic Topic..."})
    prompt = f"""You are an Academic Help Assistant at ResearchOrchestra. The student wants a comprehensive study guide or research report on a topic.
Today's Date: {time.strftime("%Y-%m-%d")}
User Input: \"\"\"{state['user_prompt']}\"\"\"

Your goal is to identify if the topic is specific enough for a high-quality study guide.
- If the topic is too broad (e.g., "Physics"), ask for a specific sub-topic or exam level (e.g., "Quantum Mechanics for AP Physics").
- If it's specific (e.g., "Transformer architectures in NLP"), no clarification needed.

Return JSON with keys:
- needs: boolean
- questions: list of short questions (max 3)
If nothing is needed, needs=false and questions=[].
"""
    msg = await llm.ainvoke(prompt)
    text = msg.content
    needs = "true" in text.lower()
    questions = re.findall(r"- (.+)", text) if needs else []

    if needs and questions:
        await adispatch_custom_event("research_update", {"message": "Clarification needed", "questions": questions})
    else:
        await adispatch_custom_event("research_update", {"message": "No clarification needed. Proceeding to plan."})

    return {**state, "needs_clarification": bool(needs and questions), "_questions": questions}


async def node_plan(state: ResearchState) -> ResearchState:
    await adispatch_custom_event("research_update", {"message": "Drafting Academic Research plan..."})
    clar = "\n".join(f"- {k}: {v}" for k, v in state["clarification"].items()) if state["clarification"] else "(none)"
    prompt = f"""Create a comprehensive academic research plan with 4-8 distinct web search queries.
Todays Date: {time.strftime("%Y-%m-%d")}
User Prompt: {state['user_prompt']}
Clarifications:
{clar}

Guidance for Queries:
1. Academic Depth: Use terms like "fundamentals", "advanced concepts", "theoretical framework".
2. Current Research: Look for recent papers, case studies, or breakthroughs (2024-2026).
3. Practical Applications: How this topic is used in the real world/industry.
4. Exam Focus: Common questions or complex areas often tested in this subject.

Return one query per line, no numbering.
"""
    msg = await llm.ainvoke(prompt)
    queries = [q.strip("- ").strip() for q in msg.content.splitlines() if q.strip()][:8]

    await adispatch_custom_event("research_update", {"message": f"Plan created with {len(queries)} queries.", "queries": queries})
    return {**state, "subqueries": queries}


async def node_synthesize(state: ResearchState) -> ResearchState:
    await adispatch_custom_event("research_update", {"message": "Compiling your Comprehensive Study Guide..."})

    sources_text = "\n".join(f"[{i}] {p.get('title') or p.get('url')} - ({p['url']})" for i, p in enumerate(state["pages"], start=1))
    corpus_text = "\n".join(
        f"### Source {i}\nURL: {p.get('url')}\nTitle: {p.get('title')}\n\n{(p.get('text') or '')[:3000]}\n"
        for i, p in enumerate(state["pages"], start=1)
    )

    prompt = f"""You are a Senior Academic Researcher at ResearchOrchestra. Write a comprehensive Deep-Dive Study Guide (~300-500 lines).

Today's Date: {time.strftime("%Y-%m-%d")}
User Request: \"\"\"{state['user_prompt']}\"\"\"

MANDATORY SECTIONS:
1. Title & Executive Summary | 2. Fundamentals & Core Concepts
3. Advanced Theoretical Framework | 4. Practical Real-World Applications
5. Recent Breakthroughs & Research Trends (2024-2026)
6. Case Studies & Examples | 7. Frequently Asked Questions (Exam Focus)
8. Summary Cheat Sheet (Key formulas, dates, or terms)
9. Further Reading & Recommended Resources
10. Conclusion & Learning Path Recommendations

CRITICAL INSTRUCTIONS:
- 300+ lines of markdown. Expand on details — this is for students to learn from.
- Do not invent data. Cite every fact as [x].
- Use LaTeX-style notation if applicable for formulas.
- Tone: Educational, clear, structured, and academic.

Sources:
{sources_text}

Corpus:
{corpus_text}
"""

    report_chunks: List[str] = []
    async for chunk in llm.astream(prompt):
        piece = chunk.content or ""
        report_chunks.append(piece)
        await adispatch_custom_event("report_token", {"content": piece})

    report = "".join(report_chunks)
    report += "\n\n## Referenced Sources\n" + "\n".join(
        f"{i}. [{p.get('title') or p.get('url')}]({p.get('url', '#')})"
        for i, p in enumerate(state["pages"], start=1)
    )
    return {**state, "report_markdown": report}


# ---------- GRAPH ----------
builder = StateGraph(ResearchState)
builder.add_node("d_clarify", node_clarify)
builder.add_node("d_plan", node_plan)
builder.add_node("d_search", node_search)
builder.add_node("d_fetch", node_fetch)
builder.add_node("d_synthesize", node_synthesize)

builder.add_edge(START, "d_clarify")
builder.add_conditional_edges(
    "d_clarify",
    lambda state: "d_plan" if not state["needs_clarification"] else "INTERRUPT",
    {"d_plan": "d_plan", "INTERRUPT": END},
)
builder.add_edge("d_plan", "d_search")
builder.add_edge("d_search", "d_fetch")
builder.add_edge("d_fetch", "d_synthesize")
builder.add_edge("d_synthesize", END)

graph = builder.compile()
