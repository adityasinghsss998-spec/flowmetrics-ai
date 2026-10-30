import json
import logging
from src.api.run_store import update_run
from fastapi import APIRouter, Depends, HTTPException, Request
from langgraph.types import Command
from pydantic import BaseModel, Field

from src.api.security import Caller, authorize_repo, require_internal_caller,APPROVE_ROLES
from src.graph.agent import get_agent_graph

logger = logging.getLogger("ai_service")
router = APIRouter()

PENDING_SECONDS = 60 * 60 * 48


class ApproveRequest(BaseModel):
    runId: str = Field(min_length=8, max_length=64)
    approved: bool
    reason: str = Field(default="", max_length=500)


@router.post("/hitl/approve")
async def approve(payload: ApproveRequest, request: Request, caller: Caller = Depends(require_internal_caller)):
    redis = request.app.state.redis
    if redis is None:
        raise HTTPException(status_code=503, detail="Approvals are unavailable right now.")

    pending_key = "hitl_pending:" + payload.runId
    raw_record = await redis.get(pending_key)
    if raw_record is None:
        raise HTTPException(status_code=409, detail="This request was already decided or has expired.")

    record = json.loads(raw_record)

    # Anyone who may see this repository may decide. (Role checks can be added later.)
    await authorize_repo(caller, int(record["repoId"]),APPROVE_ROLES)

    # Claim the decision by deleting the pending key first. DELETE returns how many keys it
    # removed. If another request got there first, it returns 0 and we stop. This is what
    # makes the first decision final, even if two people click at the same moment.
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
    try:
        await update_run(redis, payload.runId, {"status": "complete", "answer": result.get("final_answer"), "toolsCalled": []})
    except Exception as error:
        logger.warning("Could not update the saved run: %s", error)
    return {"status": result.get("approval_status"), "finalAnswer": result.get("final_answer")}


@router.get("/hitl/pending")
async def list_pending(repoId: int, request: Request, caller: Caller = Depends(require_internal_caller)):
    await authorize_repo(caller, repoId,APPROVE_ROLES)

    redis = request.app.state.redis
    if redis is None:
        return {"pending": []}

    pending = []
    async for key in redis.scan_iter(match="hitl_pending:*"):
        raw_record = await redis.get(key)
        if raw_record is None:
            continue

        record = json.loads(raw_record)
        if record.get("repoId") != repoId:
            continue

        key_text = key
        if isinstance(key, bytes):
            key_text = key.decode("utf-8")
        run_id = key_text.split(":", 1)[1]

        pending.append({
            "runId": run_id,
            "repoId": record.get("repoId"),
            "proposedAction": record.get("proposedAction"),
        })

    return {"pending": pending}