from typing import List, Dict, Any, Optional
from typing_extensions import TypedDict


class ResearchState(TypedDict):
    user_prompt: str
    research_mode: str           # "interview_intel" | "job_scenario" | "academic_help"
    prior_context: str           # formatted conversation history passed from supervisor
    clarification: Dict[str, str]
    needs_clarification: bool
    _questions: List[str]
    subqueries: List[str]
    hits: List[Dict[str, Any]]
    pages: List[Dict[str, Any]]
    reflect_pass: int            # how many reflect iterations have run
    report_markdown: str
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

    next_node           : Worker node chosen by the orchestrator.
    research_mode       : Research pipeline mode (interview_intel | job_scenario | academic_help).
    research_pipeline_mode: True when the UI Research Mode toggle is ON.
    subgraph_output     : Final text output from whichever worker ran.
    summary             : Running STM summary for long conversations.
    last_summary_idx    : Tracking index for the 40-message summarisation window.
    search_results      : Aggregated web results (legacy, kept for compatibility).
    forced_mode         : API-level override for the orchestrator routing decision.
    """
    next_node: Literal[
        "research",
        "web_search",
        "job_scenario",
        "interview_intel",
        "academic_help",
        "chat",
        "__end__",
    ]
    research_mode: Optional[Literal["interview_intel", "job_scenario", "academic_help"]]
    research_pipeline_mode: Optional[bool]
    subgraph_output: Optional[str]
    summary: str
    last_summary_idx: int
    search_results: List[Dict[str, Any]]
    forced_mode: Optional[str]
