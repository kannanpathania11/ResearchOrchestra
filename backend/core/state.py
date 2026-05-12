from typing import List, Dict, Any, Optional
from typing_extensions import TypedDict


class ResearchState(TypedDict):
    user_prompt: str
    research_mode: str           # "interview_intel" | "job_scenario" | "academic_help"
    clarification: Dict[str, str]
    needs_clarification: bool
    _questions: List[str]
    subqueries: List[str]
    hits: List[Dict[str, Any]]
    pages: List[Dict[str, Any]]
    reflect_pass: int            # how many reflect iterations have run
    report_markdown: str
