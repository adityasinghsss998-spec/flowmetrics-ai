import json
import logging
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.graph.agent import get_agent_graph
from src.config.rabbitmq import publish_message

logger = logging.getLogger("ai_service")
router = APIRouter()


class ChatRequest(BaseModel):
    repoId: int
    orgId: int
    question: str


def _initial_state(payload: ChatRequest, run_id: str) -> dict:
    return {
        "messages": [],
        "repo_id": payload.repoId,
        "org_id": payload.orgId,
        "user_question": payload.question,
        "tools_called": [],
        "tool_results": {},
        "iterations": 0,
        "final_answer": None,
        "error": None,
        "requires_approval": False,
        "proposed_action": None,
        "approval_status": None,
        "run_id": run_id,
    }


@router.post("/chat")
async def chat(payload: ChatRequest, request: Request):
    run_id = str(uuid.uuid4())
    graph = await get_agent_graph()
    config = {"configurable": {"thread_id": run_id}}

    result = await graph.ainvoke(_initial_state(payload, run_id), config=config)
    redis = request.app.state.redis

    if "__interrupt__" in result:
        proposed_action = result["__interrupt__"][0].value["proposed_action"]
        rabbitmq_conn = getattr(request.app.state, "rabbitmq", None)
        if rabbitmq_conn is not None:
            try:
                await publish_message(
                    rabbitmq_conn,
                    "ai.action_requested",
                    {
                        "runId": run_id,
                        "repoId": payload.repoId,
                        "proposedAction": proposed_action.get("reasoning", ""),
                        "actionType": proposed_action.get("type", "post_pr_comment"),
                        "reasoning": proposed_action.get("reasoning", ""),
                        "requesterEmail": "",
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to publish ai.action_requested to RabbitMQ: {e}")
        if redis is not None:
            await redis.set(
                f"hitl_pending:{run_id}",
                json.dumps({"repoId": payload.repoId, "proposedAction": proposed_action}),
                ex=60 * 60 * 48,
            )
        return {"status": "pending_approval", "runId": run_id, "proposedAction": proposed_action}

    if redis is not None:
        await redis.set(
            f"ai_result:{run_id}",
            json.dumps({"answer": result["final_answer"], "toolsCalled": result["tools_called"]}),
            ex=60 * 60 * 24,
        )
    return {"answer": result["final_answer"], "toolsCalled": result["tools_called"], "runId": run_id}


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest):
    run_id = str(uuid.uuid4())
    graph = await get_agent_graph()
    config = {"configurable": {"thread_id": run_id}}

    async def event_generator():
        async for state_update in graph.astream(_initial_state(payload, run_id), config=config, stream_mode="values"):
            event = {"toolsCalled": state_update.get("tools_called", []), "finalAnswer": state_update.get("final_answer")}
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request):
    redis = request.app.state.redis
    if redis is None:
        return {"status connected nhi ha": "unavailable", "reason": "redis not connected"}
    raw = await redis.get(f"ai_result:{run_id}")
    if raw is not None:
        return {"status hogya": "complete", **json.loads(raw)}
    if await redis.exists(f"hitl_pending:{run_id}"):
        return {"status hehe": "pending_approval"}
    return {"status": "not_found"}