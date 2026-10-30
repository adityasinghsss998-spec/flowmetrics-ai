import asyncio
import json
import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.api.rate_limit import acquire_run_lock, check_rate_limit, release_run_lock
from src.api.run_store import load_run, new_run_record, save_run, update_run
from src.api.security import Caller, authorize_repo, require_internal_caller
from src.config.rabbitmq import publish_message
from src.graph.agent import get_agent_graph

logger = logging.getLogger("ai_service")
router = APIRouter()

# A question that runs longer than this is stopped, so a stuck run never hangs forever.
RUN_TIMEOUT_SECONDS = 150

# If a run still says "running" after this long, the server probably restarted in the middle of it.
RUN_STALE_SECONDS = 200

# The free Gemini tier allows only a few requests per minute for the whole service,
# so only this many questions run at the same time. Others wait their turn.
MAX_CONCURRENT_RUNS = 2
run_slots = asyncio.Semaphore(MAX_CONCURRENT_RUNS)

# Running tasks must be kept in a set. Otherwise Python may delete a task while it is still running.
background_tasks = set()


class RunFailed(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


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
        raise RunFailed("The analysis took too long. Please try again.")
    except Exception:
        # The real error goes to our log. The user only sees a friendly message.
        logger.exception("Agent run failed")
        raise RunFailed("The AI analyst is unavailable right now. Please try again.")


async def store_interrupt(app, payload, run_id, user_id, result):
    """The agent paused because an action needs a human to approve it."""
    redis = app.state.redis
    interrupt_list = result["__interrupt__"]
    proposed_action = interrupt_list[0].value["proposed_action"]

    pending_record = {
        "repoId": payload.repoId,
        "requestedBy": user_id,
        "proposedAction": proposed_action,
    }
    await redis.set("hitl_pending:" + run_id, json.dumps(pending_record), ex=60 * 60 * 48)

    rabbitmq_conn = getattr(app.state, "rabbitmq", None)
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

    await update_run(redis, run_id, {"status": "pending_approval", "proposedAction": proposed_action})


async def mark_failed(redis, run_id, message):
    try:
        await update_run(redis, run_id, {"status": "failed", "error": message})
    except Exception as error:
        logger.warning("Could not save the failed status: %s", error)


async def background_run(app, payload, question, run_id, user_id):
    """Runs the agent after the HTTP response has already been sent."""
    redis = app.state.redis
    try:
        result = await run_agent(payload, question, run_id)

        if "__interrupt__" in result:
            await store_interrupt(app, payload, run_id, user_id, result)
        else:
            answer = result.get("final_answer")
            if not answer:
                answer = "I could not produce an answer from the available data."
            tools_called = result.get("tools_called", [])
            await update_run(redis, run_id, {"status": "complete", "answer": answer, "toolsCalled": tools_called})

    except RunFailed as error:
        await mark_failed(redis, run_id, error.message)
    except Exception:
        logger.exception("Background run crashed")
        await mark_failed(redis, run_id, "The AI analyst is unavailable right now. Please try again.")
    finally:
        try:
            await release_run_lock(redis, user_id)
        except Exception as error:
            logger.warning("Could not release the run lock: %s", error)


@router.post("/chat", status_code=202)
async def chat(payload: ChatRequest, request: Request, caller: Caller = Depends(require_internal_caller)):
    question = payload.question.strip()
    if question == "":
        raise HTTPException(status_code=422, detail="Please enter a question.")

    redis = request.app.state.redis
    if redis is None:
        raise HTTPException(status_code=503, detail="The AI analyst is unavailable right now.")

    await check_rate_limit(redis, caller.user_id)
    await authorize_repo(caller, payload.repoId)

    got_lock = await acquire_run_lock(redis, caller.user_id)
    if not got_lock:
        raise HTTPException(status_code=429, detail="You already have a question running. Wait for it to finish.")

    run_id = str(uuid.uuid4())
    try:
        await save_run(redis, run_id, new_run_record(caller.user_id, payload.repoId))
    except Exception:
        logger.exception("Could not save the new run")
        await release_run_lock(redis, caller.user_id)
        raise HTTPException(status_code=503, detail="The AI analyst is unavailable right now.")

    task = asyncio.create_task(background_run(request.app, payload, question, run_id, caller.user_id))
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)

    # The answer is fetched later with GET /runs/{run_id}.
    return {"runId": run_id, "status": "running"}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request, caller: Caller = Depends(require_internal_caller)):
    redis = request.app.state.redis
    if redis is None:
        raise HTTPException(status_code=503, detail="Run lookup is unavailable right now.")

    record = await load_run(redis, run_id)
    if record is None:
        return {"status": "not_found"}

    # Only the person who asked can read the result. Others get "not found".
    if record.get("requestedBy") != caller.user_id:
        return {"status": "not_found"}

    status = record.get("status")

    if status == "running":
        age_seconds = int(time.time()) - int(record.get("startedAt", 0))
        if age_seconds > RUN_STALE_SECONDS:
            return {"status": "failed", "message": "The analysis was interrupted. Please try again."}
        return {"status": "running"}

    if status == "complete":
        return {
            "status": "complete",
            "answer": record.get("answer"),
            "toolsCalled": record.get("toolsCalled", []),
        }

    if status == "pending_approval":
        return {"status": "pending_approval", "runId": run_id, "proposedAction": record.get("proposedAction")}

    if status == "failed":
        return {"status": "failed", "message": record.get("error") or "The analysis failed. Please try again."}

    return {"status": "not_found"}


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest, request: Request, caller: Caller = Depends(require_internal_caller)):
    """Experimental and not used by the frontend. It does not support questions that need approval."""
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
            yield "data: " + json.dumps({"error": "The AI analyst is unavailable right now."}) + "\n\n"
        finally:
            await release_run_lock(redis, caller.user_id)

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)