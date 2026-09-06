from src.graph.state import AgentState

async def intent_parser(state: AgentState) -> dict:
    return {
        "tools_called": [],
        "tool_results": {},
        "iterations": 0,
    }