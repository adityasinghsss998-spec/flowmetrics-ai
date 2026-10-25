from langchain_core.utils import pre_init
from requests import status_codes
import json
import logging
from fastapi import APIRouter, Request,Depends,HTTPException
from langgraph.types import Command
from pydantic import BaseModel,Field

from src.api.security import Caller,authorize_repo,require_internal_caller
from src.graph.agent import get_agent_graph

router = APIRouter()
logger = logging.getLogger("ai_service")

PENDING_SECONDS = 60 * 60 * 48

class ApproveRequest(BaseModel):
    runId: str= Field(min_length=8,max_length=64)
    approved: bool
    reason: str = Field(default="",max_length=500)


@router.post("/hitl/approve")
async def approve(payload: ApproveRequest, request: Request,caller :Caller = Depends(require_internal_caller)):
    redis=request.app.state.redis
    if redis is None:
        return HTTPException(status_code=503,detail="Approvals are unavailable right now")
    
    pending_key="hitl_pending" + payload.runId
    raw_record=await redis.get(pending_key)
    if raw_record is None:
        raise HTTPException(status_code=409, detail="This request was already decided or has expired.")

    record = json.loads(raw_record)
    await authorize_repo(caller,int(record["repoId"]))
    removed_count = await redis.delete(pending_key)
    if removed_count == 0:
        raise HTTPException(status_code=409, detail="This request was already decided or has expired.")
    
    graph = await get_agent_graph()
    config = {"configurable": {"thread_id": payload.runId}}

    try:
        result = await graph.ainvoke(
            Command(resume={"approved": payload.approved, "reason": payload.reason}),
            config=config,
        )
    except Exception:
        logger.exception("Could not resume the paused run")
        # Put the request back so the reviewer can try again.
        await redis.set(pending_key, raw_record, ex=PENDING_SECONDS)
        raise HTTPException(status_code=502, detail="Could not apply the decision. Please try again.")

    return {"status": result.get("approval_status"), "finalAnswer": result.get("final_answer")}



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