from langgraph.graph import StateGraph, START, END
from .state import SupervisorState
from .nodes import (
    orchestrator_node,
    research_node,
    quick_search_node,
    chat_node,
    context_persist_node,
    session_archiver_node,
)

# ── Build the Supervisor (Orchestrator) Graph ────────────────────────────────
builder = StateGraph(SupervisorState)

# 1. Nodes
builder.add_node("orchestrator",    orchestrator_node)
builder.add_node("research",        research_node)
builder.add_node("quick_search",    quick_search_node)
builder.add_node("chat",            chat_node)
builder.add_node("context_persist", context_persist_node)
builder.add_node("session_archiver", session_archiver_node)

# 2. Entry
builder.add_edge(START, "orchestrator")

# 3. Orchestrator routes to one of three workers
builder.add_conditional_edges(
    "orchestrator",
    lambda state: state["next_node"],
    {
        "research":    "research",
        "quick_search": "quick_search",
        "chat":        "chat",
    },
)

# 4. All workers converge → context_persist → session_archiver → END
builder.add_edge("research",     "context_persist")
builder.add_edge("quick_search", "context_persist")
builder.add_edge("chat",         "context_persist")
builder.add_edge("context_persist",  "session_archiver")
builder.add_edge("session_archiver", END)

graph = builder.compile()
