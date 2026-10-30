import json
import time
RUN_TTL_SECONDS = 60 * 60 * 24

def run_key(run_id):
    return "ai_result"+run_id

def new_run_record(user_id,repo_id):
    return {
        "status": "running",
        "requestedBy": user_id,
        "repoId": repo_id,
        "startedAt": int(time.time()),
        "answer": None,
        "toolsCalled": [],
        "proposedAction": None,
        "error": None,
    }

async def save_run(redis, run_id, record):
    await redis.set(run_key(run_id), json.dumps(record), ex=RUN_TTL_SECONDS)


async def load_run(redis, run_id):
    raw_record = await redis.get(run_key(run_id))
    if raw_record is None:
        return None
    return json.loads(raw_record)

async def update_run(redis, run_id, changes):
    """Change some fields of a saved run and keep all the others."""
    record = await load_run(redis, run_id)
    if record is None:
        return

    for field_name in changes:
        record[field_name] = changes[field_name]

    await save_run(redis, run_id, record)