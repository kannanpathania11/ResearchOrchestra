import re
import time
from typing import List

from langchain_core.callbacks.manager import adispatch_custom_event
from langgraph.graph import StateGraph, START, END
from core.llm import llm
from core.state import ResearchState
from core.web import node_search, node_fetch


async def node_clarify(state: ResearchState) -> ResearchState:
    await adispatch_custom_event("research_update", {"message": "Analyzing Job Market Topic..."})
    prompt = f"""You are a Job Scenario Analyst at ResearchOrchestra. The student wants to understand the market for a specific role or industry.
Today's Date: {time.strftime("%Y-%m-%d")}
User Input: \"\"\"{state['user_prompt']}\"\"\"

Your goal is to ensure you have a specific JOB ROLE or INDUSTRY and ideally a LOCATION (optional).
- If the student says something vague like "What is the job market like?", ask what role they are interested in.
- If they say "Data Science in London", no clarification needed.

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
    await adispatch_custom_event("research_update", {"message": "Drafting Job Market analysis plan..."})
    clar = "\n".join(f"- {k}: {v}" for k, v in state["clarification"].items()) if state["clarification"] else "(none)"
    prompt = f"""Create a comprehensive job scenario analysis plan with 6-8 distinct web search queries.
Todays Date: {time.strftime("%Y-%m-%d")}
Job Role/Industry: {state['user_prompt']}
Clarifications:
{clar}

Generate queries covering:
1. Hiring Trends: Current volume of job openings, growth rate.
2. In-Demand Skills: Most requested technical and soft skills for this role in 2026.
3. Salary Benchmarks: Entry-level, junior, and mid-level pay scales by location.
4. Top Employers: Companies currently hiring most for this role.
5. Educational Requirements: Degree trends, certification value.
6. Market Competition: Number of applicants per opening, saturation levels.

- Be specific (include role names and years).
- Keep queries under 10 words.
Return one query per line, no numbering.
"""
    msg = await llm.ainvoke(prompt)
    queries = [q.strip("- ").strip() for q in msg.content.splitlines() if q.strip()][:8]

    await adispatch_custom_event("research_update", {"message": f"Plan created with {len(queries)} queries.", "queries": queries})
    return {**state, "subqueries": queries}


async def node_synthesize(state: ResearchState) -> ResearchState:
    await adispatch_custom_event("research_update", {"message": "Synthesizing market dynamics report..."})

    sources_text = "\n".join(f"[{i}] {p.get('title') or p.get('url')} - ({p['url']})" for i, p in enumerate(state["pages"], start=1))
    corpus_text = "\n".join(
        f"### Source {i}\nURL: {p.get('url')}\nTitle: {p.get('title')}\n\n{(p.get('text') or '')[:3000]}\n"
        for i, p in enumerate(state["pages"], start=1)
    )

    prompt = f"""You are a Senior Job Scenario Analyst at ResearchOrchestra. Write a comprehensive Job Scenario Analysis Report (~500+ lines).

Today's Date: {time.strftime("%Y-%m-%d")}
Job Role/Industry: \"\"\"{state['user_prompt']}\"\"\"

MANDATORY SECTIONS:
1. Title & Executive Summary | 2. Current Hiring Sentiment
3. Skill Gap Analysis: What students have vs. what employers want.
4. Salary Landscape: Entry-level to Senior (Markdown table).
5. Geographic Hotspots: Top cities/regions for this role.
6. Industry Breakdown: Which sectors are hiring (Tech, Finance, Health, etc.).
7. Future Outlook: Impact of AI/Automation on this role over the next 5 years.
8. Educational ROI: Best degrees/certifications for this path.
9. Top 10 Active Employers for this Role.
10. Conclusion & Strategic Career Advice.

CRITICAL INSTRUCTIONS:
- 500+ lines. Use paragraphs for deep analysis.
- Data-driven: prioritize salary numbers and hiring percentages from corpus.
- Do not invent data. Cite every fact as [x].
- Tone: Professional, data-heavy, but encouraging for students.

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
builder.add_node("m_clarify", node_clarify)
builder.add_node("m_plan", node_plan)
builder.add_node("m_search", node_search)
builder.add_node("m_fetch", node_fetch)
builder.add_node("m_synthesize", node_synthesize)

builder.add_edge(START, "m_clarify")
builder.add_conditional_edges(
    "m_clarify",
    lambda state: "m_plan" if not state["needs_clarification"] else "INTERRUPT",
    {"m_plan": "m_plan", "INTERRUPT": END},
)
builder.add_edge("m_plan", "m_search")
builder.add_edge("m_search", "m_fetch")
builder.add_edge("m_fetch", "m_synthesize")
builder.add_edge("m_synthesize", END)

graph = builder.compile()
