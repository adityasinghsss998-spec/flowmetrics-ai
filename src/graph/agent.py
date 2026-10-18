"""LangGraph agent with Redis-backed checkpoint saver.

Falls back to MemorySaver when Redis is unavailable so the graph can be
tested locally without a running Redis instance.
"""

import logging

import redis.asyncio as aioredis
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from src.config.settings import get_settings
from src.graph.nodes.intent_parser import intent_parser
from src.graph.nodes.tool_executer import tool_executor
from src.graph.nodes.response_writer import response_writer
from src.graph.nodes.hitl_node import hitl_node
from src.graph.redis_saver import AsyncRedisCheckpointSaver
from src.graph.state import AgentState

logger = logging.getLogger("ai_service")

MAX_ITERATIONS = 5
settings = get_settings()


def route_intent(state: AgentState) -> str:
    return "hitl" if state.get("requires_approval") else "analyze"


def should_continue(state: AgentState) -> str:
    if state["iterations"] >= MAX_ITERATIONS:
        return "stop"
    if state.get("final_answer"):
        return "stop"
    return "continue"


graph_builder = StateGraph(AgentState)
graph_builder.add_node("intent_parser", intent_parser)
graph_builder.add_node("tool_executor", tool_executor)
graph_builder.add_node("response_writer", response_writer)
graph_builder.add_node("hitl_node", hitl_node)

graph_builder.set_entry_point("intent_parser")
graph_builder.add_conditional_edges(
    "intent_parser", route_intent, {"hitl": "hitl_node", "analyze": "tool_executor"}
)
graph_builder.add_conditional_edges(
    "tool_executor", should_continue, {"continue": "tool_executor", "stop": "response_writer"}
)
graph_builder.add_edge("hitl_node", END)
graph_builder.add_edge("response_writer", END)


_compiled_graph = None
_redis_client: aioredis.Redis | None = None


async def get_agent_graph():
    """Return the compiled graph, initialising the Redis checkpointer once.

    If Redis is unreachable a MemorySaver is used instead so the agent can
    still run (at the cost of no cross-request persistence).
    """
    global _compiled_graph, _redis_client
    if _compiled_graph is not None:
        return _compiled_graph

    checkpointer = None

    try:
        _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=False)
        # Quick connectivity check — fail fast rather than mid-request
        await _redis_client.ping()
        checkpointer = AsyncRedisCheckpointSaver(_redis_client)
        logger.info("Agent graph: using AsyncRedisCheckpointSaver")
    except Exception as e:
        logger.warning(
            "Redis unavailable (%s) — falling back to MemorySaver (no persistence)", e
        )
        if _redis_client is not None:
            await _redis_client.aclose()
            _redis_client = None
        checkpointer = MemorySaver()

    _compiled_graph = graph_builder.compile(checkpointer=checkpointer)
    return _compiled_graph