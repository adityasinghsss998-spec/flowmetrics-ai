import json

from fastapi import APIRouter, Request,Depends,HTTPException
from langgraph.types import Command
from pydantic import BaseModel

from src.graph.agent import get_agent_graph

router = APIRouter()


class ApproveRequest(BaseModel):
    runId: str
    approved: bool
    reason: str = ""


@router.post("/hitl/approve")
async def approve(payload: ApproveRequest, request: Request):
    graph = await get_agent_graph()
    config = {"configurable": {"thread_id": payload.runId}}

    result = await graph.ainvoke(
        Command(resume={"approved": payload.approved, "reason": payload.reason}),
        config=config,
    )

    redis = request.app.state.redis
    if redis is not None:
        await redis.delete(f"hitl_pending:{payload.runId}")

    approval_status = result.get("approval_status")
    return {
        "status": approval_status,
        "approval_status": approval_status,
        "finalAnswer": result.get("final_answer"),
    }


@router.get("/hitl/pending")
async def list_pending(repoId: int, request: Request):
    redis = request.app.state.redis
    if redis is None:
        return {"pending": []}

    pending = []
    async for key in redis.scan_iter(match="hitl_pending:*"):
        raw = await redis.get(key)
        if raw is None:
            continue
        record = json.loads(raw)
        if record.get("repoId") == repoId:
            key_str = key.decode() if isinstance(key, bytes) else key
            pending.append({"runId": key_str.split(":", 1)[1], **record})
    return {"pending": pending}