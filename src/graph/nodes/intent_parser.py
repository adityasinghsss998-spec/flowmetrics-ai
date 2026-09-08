from google.genai import types

from src.graph.state import AgentState


async def intent_parser(state: AgentState) -> dict:
    """Prepares a fresh run — seeds the conversation with the user's
    question as a proper Gemini Content object."""
    initial_message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=state["user_question"])],
    )
    return {
        "messages": [initial_message],
        "tools_called": [],
        "tool_results": {},
        "iterations": 0,
    }