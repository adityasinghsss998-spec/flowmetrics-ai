from google.genai import types

from src.graph.state import AgentState

ACTION_KEYWORDS = ("comment on", "assign", "create an issue", "create issue", "post a comment")


async def intent_parser(state: AgentState) -> dict:
    initial_message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=state["user_question"])],
    )
    is_action_request = any(kw in state["user_question"].lower() for kw in ACTION_KEYWORDS)
    return {
        "messages": [initial_message],
        "tools_called": [],
        "tool_results": {},
        "iterations": 0,
        "requires_approval": is_action_request,
    }