"""Graph nodes package."""
from typing import TypedDict, List, Optional, Annotated
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    messages:Annotated[List,add_messages]
    repo_id:int
    org_id: int
    user_question: str
    tools_called: List[str]
    tool_results: dict
    iterations: int

    final_answer: Optional[str]
    error: Optional[str]
