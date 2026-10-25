import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.api.rate_limit import acquire_run_lock, check_rate_limit, release_run_lock
from src.api.security import Caller, authorize_repo, require_internal_caller
from src.config.rabbitmq import publish_message
from src.graph.agent import get_agent_graph

logger = logging.getLogger("ai_service")
router = APIRouter()

# A question that runs longer than this is stopped, so a stuck run never hangs forever.
RUN_TIMEOUT_SECONDS = 80

# The free Gemini tier allows only a few requests per minute for the whole service,
# so only this many questions run at the same time. Others wait their turn.
MAX_CONCURRENT_RUNS = 2
run_slots = asyncio.Semaphore(MAX_CONCURRENT_RUNS)


class ChatRequest(BaseModel):
    repoId: int = Field(gt=0)
    orgId: int = Field(gt=0)
    question: str = Field(min_length=1, max_length=1000)


def build_initial_state(payload, question, run_id):
    return {
        "messages": [],
        "repo_id": payload.repoId,
        "org_id": payload.orgId,
        "user_question": question,
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


async def run_agent(payload, question, run_id):
    graph = await get_agent_graph()
    config = {"configurable": {"thread_id": run_id}}
    initial_state = build_initial_state(payload, question, run_id)

    async def invoke_with_slot():
        async with run_slots:
            return await graph.ainvoke(initial_state, config=config)

    try:
        # The timeout covers both waiting for a free slot and the run itself.
        return await asyncio.wait_for(invoke_with_slot(), timeout=RUN_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="The analysis took too long. Please try again.")
    except HTTPException:
        raise
    except Exception:
        # The real error goes to our log. The user only sees a friendly message.
        logger.exception("Agent run failed")
        raise HTTPException(status_code=502, detail="The AI analyst is unavailable right now. Please try again.")


@router.post("/chat")
async def chat(payload: ChatRequest, request: Request, caller: Caller = Depends(require_internal_caller)):
    question = payload.question.strip()
    if question == "":
        raise HTTPException(status_code=422, detail="Please enter a question.")

    redis = request.app.state.redis
    await check_rate_limit(redis, caller.user_id)
    await authorize_repo(caller, payload.repoId)

    got_lock = await acquire_run_lock(redis, caller.user_id)
    if not got_lock:
        raise HTTPException(status_code=429, detail="You already have a question running. Wait for it to finish.")

    run_id = str(uuid.uuid4())
    try:
        result = await run_agent(payload, question, run_id)
    finally:
        await release_run_lock(redis, caller.user_id)

    # The agent paused and wants a human to approve an action.
    if "__interrupt__" in result:
        interrupt_list = result["__interrupt__"]
        proposed_action = interrupt_list[0].value["proposed_action"]

        if redis is None:
            raise HTTPException(status_code=503, detail="Approvals are unavailable right now.")

        pending_record = {
            "repoId": payload.repoId,
            "requestedBy": caller.user_id,
            "proposedAction": proposed_action,
        }
        await redis.set("hitl_pending:" + run_id, json.dumps(pending_record), ex=60 * 60 * 48)

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
            except Exception as error:
                logger.warning("Failed to publish ai.action_requested: %s", error)

        return {"status": "pending_approval", "runId": run_id, "proposedAction": proposed_action}

    answer = result.get("final_answer")
    if not answer:
        answer = "I could not produce an answer from the available data."
    tools_called = result.get("tools_called", [])

    # Saving the answer for /runs is a bonus. If Redis fails, the user still gets the answer.
    if redis is not None:
        try:
            result_record = {"answer": answer, "toolsCalled": tools_called, "requestedBy": caller.user_id}
            await redis.set("ai_result:" + run_id, json.dumps(result_record), ex=60 * 60 * 24)
        except Exception as error:
            logger.warning("Could not save run result: %s", error)

    return {"answer": answer, "toolsCalled": tools_called, "runId": run_id}


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest, request: Request, caller: Caller = Depends(require_internal_caller)):
    """Experimental. It does not support questions that need approval. Use /chat for those."""
    question = payload.question.strip()
    if question == "":
        raise HTTPException(status_code=422, detail="Please enter a question.")

    redis = request.app.state.redis
    await check_rate_limit(redis, caller.user_id)
    await authorize_repo(caller, payload.repoId)

    got_lock = await acquire_run_lock(redis, caller.user_id)
    if not got_lock:
        raise HTTPException(status_code=429, detail="You already have a question running. Wait for it to finish.")

    run_id = str(uuid.uuid4())
    graph = await get_agent_graph()
    config = {"configurable": {"thread_id": run_id}}
    initial_state = build_initial_state(payload, question, run_id)

    async def event_generator():
        try:
            async with run_slots:
                async for state_update in graph.astream(initial_state, config=config, stream_mode="values"):
                    event = {
                        "toolsCalled": state_update.get("tools_called", []),
                        "finalAnswer": state_update.get("final_answer"),
                    }
                    yield "data: " + json.dumps(event) + "\n\n"
        except Exception:
            logger.exception("Streaming run failed")
            error_event = {"error": "The AI analyst is unavailable right now."}
            yield "data: " + json.dumps(error_event) + "\n\n"
        finally:
            await release_run_lock(redis, caller.user_id)

    # These headers stop proxies from holding the stream back until it finishes.
    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)


@router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request, caller: Caller = Depends(require_internal_caller)):
    redis = request.app.state.redis
    if redis is None:
        raise HTTPException(status_code=503, detail="Run lookup is unavailable right now.")

    raw_result = await redis.get("ai_result:" + run_id)
    if raw_result is not None:
        record = json.loads(raw_result)
        # Only the person who asked can read the answer. Others get "not found".
        if record.get("requestedBy") != caller.user_id:
            return {"status": "not_found"}
        return {
            "status": "complete",
            "answer": record.get("answer"),
            "toolsCalled": record.get("toolsCalled", []),
        }

    raw_pending = await redis.get("hitl_pending:" + run_id)
    if raw_pending is not None:
        record = json.loads(raw_pending)
        if record.get("requestedBy") == caller.user_id:
            return {"status": "pending_approval"}

    return {"status": "not_found"}