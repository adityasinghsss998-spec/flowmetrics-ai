import json
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.graph.agent import agent_graph

router = APIRouter()


class ChatRequest(BaseModel):
    repoId: int
    orgId: int
    question: str


def _initial_state(payload: ChatRequest) -> dict:
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
    }


@router.post("/chat")
async def chat(payload: ChatRequest, request: Request):
    run_id = str(uuid.uuid4())
    result = await agent_graph.ainvoke(_initial_state(payload))

    redis = request.app.state.redis
    if redis is not None:
        await redis.set(
            f"ai_run:{run_id}",
            json.dumps({"answer": result["final_answer"], "toolsCalled": result["tools_called"]}),
            ex=60 * 60 * 24,
        )

    return {"answer": result["final_answer"], "toolsCalled": result["tools_called"], "runId": run_id}


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest):
    async def event_generator():
        async for state_update in agent_graph.astream(_initial_state(payload), stream_mode="values"):
            event = {
                "toolsCalled": state_update.get("tools_called", []),
                "finalAnswer": state_update.get("final_answer"),
            }
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request):
    redis = request.app.state.redis
    if redis is None:
        return {"status": "unavailable", "reason": "redis not connected"}
    raw = await redis.get(f"ai_run:{run_id}")
    if raw is None:
        return {"status": "not_found"}
    return {"status": "complete", **json.loads(raw)}