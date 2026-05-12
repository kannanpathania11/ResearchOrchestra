import re
import time
from typing import List

from langchain_core.callbacks.manager import adispatch_custom_event
from langgraph.graph import StateGraph, START, END
from core.llm import llm
from core.state import ResearchState
from core.web import node_search, node_fetch


async def node_clarify(state: ResearchState) -> ResearchState:
    await adispatch_custom_event("research_update", {"message": "Identifying Company & Role..."})
    prompt = f"""You are an expert Career Interview Consultant. The student wants to prepare for an interview or learn about a company.
Today's Date: {time.strftime("%Y-%m-%d")}
User Input: \"\"\"{state['user_prompt']}\"\"\"

Your goal is to ensure you have the correct COMPANY NAME and the JOB ROLE (if applicable).
- If the user provides just a company (e.g., "Google"), ask what role they are interested in.
- If they provide both (e.g., "Software Engineer at Stripe"), no clarification needed.

Return JSON with keys:
- needs: boolean
- questions: list of short questions (max 2)
If nothing is needed, needs=false and questions=[].
"""
    msg = await llm.ainvoke(prompt)
    text = msg.content
    needs = "true" in text.lower()
    questions = re.findall(r"- (.+)", text) if needs else []

    if needs and questions:
        await adispatch_custom_event("research_update", {"message": "Clarification needed", "questions": questions})
    else:
        await adispatch_custom_event("research_update", {"message": "Target Company Identified. Proceeding to plan."})

    return {**state, "needs_clarification": bool(needs and questions), "_questions": questions}


async def node_plan(state: ResearchState) -> ResearchState:
    await adispatch_custom_event("research_update", {"message": "Drafting Interview Intel plan..."})
    clar = "\n".join(f"- {k}: {v}" for k, v in state["clarification"].items()) if state["clarification"] else "(none)"
    prompt = f"""Create a comprehensive Interview Intelligence plan with 10-12 distinct web search queries.
Todays Date: {time.strftime("%Y-%m-%d")}
Target Request: {state['user_prompt']}
Clarifications:
{clar}

Generate queries covering:
1. Recent Interview Questions: Specifically for the role mentioned (or general roles if not).
2. Hiring Process: Rounds, technical assessments, cultural fit interviews.
3. Company Culture & Values: What they look for in candidates, "Leadership Principles".
4. Recent News & Projects: What the company is currently working on to mention in interviews.
5. Tech Stack & Tools: Common technologies used in the relevant department.
6. Salary & Benefits for Interns/Entry-level: Recent data from Glassdoor/Levels.fyi.
7. Employee Reviews for New Grads: Sentiment from recent joiners.

- Include Company Name and Role in every query.
- Keep queries under 10 words.
Return one query per line, no numbering.
"""
    msg = await llm.ainvoke(prompt)
    queries = [q.strip("- ").strip() for q in msg.content.splitlines() if q.strip()][:12]

    await adispatch_custom_event("research_update", {"message": f"Plan created with {len(queries)} queries.", "queries": queries})
    return {**state, "subqueries": queries}


async def node_synthesize(state: ResearchState) -> ResearchState:
    await adispatch_custom_event("research_update", {"message": "Compiling your personalized Interview Guide..."})

    sources_text = "\n".join(f"[{i}] {p.get('title') or p.get('url')} - ({p['url']})" for i, p in enumerate(state["pages"], start=1))
    corpus_text = "\n".join(
        f"### Source {i}\nURL: {p.get('url')}\nTitle: {p.get('title')}\n\n{(p.get('text') or '')[:3000]}\n"
        for i, p in enumerate(state["pages"], start=1)
    )

    prompt = f"""You are a Senior Career Coach at ResearchOrchestra. Write an EXTREMELY DETAILED Interview Intelligence Report (1000-1500+ lines).

Today's Date: {time.strftime("%Y-%m-%d")}
Target: \"\"\"{state['user_prompt']}\"\"\"

MANDATORY SECTIONS:
1. Interview Strategy Overview | 2. Predicted Interview Questions (Technical & Behavioral)
3. Step-by-Step Hiring Process | 4. Deep Dive: Company Culture & Values
5. Critical Projects & Recent News (To mention in interviews) | 6. Role-Specific Tech Stack
7. Salary Benchmarks & Benefits | 8. Common Candidate Pitfalls
9. Suggested Questions for the Interviewer | 10. Personalized 3-Day Prep Roadmap

CRITICAL INSTRUCTIONS:
- 1000-1500+ lines. Use paragraphs for deep strategic advice.
- Data-driven: prioritize real interview experiences and news from the corpus.
- Do not invent questions; base them on recent candidate reports in the data.
- h1 (#) for sections, h2 (##) for subsections. Tables for salary/competitor info.
- Tone: Empowering, strategic, and practical for a student.

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
builder.add_node("c_clarify", node_clarify)
builder.add_node("c_plan", node_plan)
builder.add_node("c_search", node_search)
builder.add_node("c_fetch", node_fetch)
builder.add_node("c_synthesize", node_synthesize)

builder.add_edge(START, "c_clarify")
builder.add_conditional_edges(
    "c_clarify",
    lambda state: "c_plan" if not state["needs_clarification"] else "INTERRUPT",
    {"c_plan": "c_plan", "INTERRUPT": END},
)
builder.add_edge("c_plan", "c_search")
builder.add_edge("c_search", "c_fetch")
builder.add_edge("c_fetch", "c_synthesize")
builder.add_edge("c_synthesize", END)

graph = builder.compile()
