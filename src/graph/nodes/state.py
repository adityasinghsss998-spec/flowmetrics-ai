"""Graph nodes package."""
from typing import TypedDict, List, Optional

class AgentState(TypedDict):
    messages:List
    repo_id:int
    org_id: int
    user_question: str
    tools_called: List[str]
    tool_results: dict
    iterations: int

    final_answer: Optional[str]
    error: Optional[str]
