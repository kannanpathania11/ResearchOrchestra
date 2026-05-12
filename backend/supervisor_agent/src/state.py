from typing import List, Literal, Optional, Dict, Any
from typing_extensions import TypedDict
from pydantic import BaseModel, Field
from langgraph.graph import MessagesState


class MemoryItem(BaseModel):
    text: str = Field(description="Atomic user memory")
    is_new: bool = Field(description="True if new, false if duplicate")


class MemoryDecision(BaseModel):
    should_write: bool
    memories: List[MemoryItem] = Field(default_factory=list)


class SupervisorState(MessagesState):
    """
    State for the Supervisor (Orchestrator) Graph.

    - next_node:       Worker chosen by the orchestrator.
    - research_mode:   Passed into the research_pipeline to select prompt strategy.
    - subgraph_output: Final text output from whichever worker ran.
    - summary:         Running STM summary for long conversations.
    - last_summary_idx: Tracking index for the 40-message summarisation window.
    - search_results:  Aggregated web results (used by quick_search node).
    - forced_mode:     API-level override for the orchestrator routing decision.
    """
    next_node: Literal["research", "quick_search", "chat", "__end__"]
    research_mode: Optional[Literal["interview_intel", "job_scenario", "academic_help"]]
    subgraph_output: Optional[str]
    summary: str
    last_summary_idx: int
    search_results: List[Dict[str, Any]]
    forced_mode: Optional[str]
