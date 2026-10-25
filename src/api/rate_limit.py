import logging
import time

from fastapi import HTTPException

logger = logging.getLogger("ai_service")

MAX_QUESTIONS_PER_MINUTE = 6
RUN_LOCK_SECONDS = 120


async def check_rate_limit(redis, user_id):
    """Each user may ask a limited number of questions per minute."""
    if redis is None:
        logger.warning("Redis is not connected, rate limit skipped")
        return

    # time.time() // 60 is the same number for a whole minute, so every request in that
    # minute shares one counter.
    current_minute = int(time.time() // 60)
    counter_key="ai_rate"+user_id + ":" + str(current_minute)
    count=await redis.incr(counter_key)
    if count == 1:
        await redis.expire(counter_key,120) 

    if count > MAX_QUESTIONS_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Too many questions. Wait a minute and try again.")


async def acquire_run_lock(redis, user_id):
    """Only one running question per user. Returns True if this request got the lock."""
    if redis is None:
        return True

    lock_key = "ai_lock:" + user_id
    # nx=True means "only set if the key does not exist", so only one request can win.
    # ex=... makes the lock delete itself, so a crash can never lock a user out forever.
    was_set = await redis.set(lock_key, "1", nx=True, ex=RUN_LOCK_SECONDS)
    return bool(was_set)


async def release_run_lock(redis, user_id):
    if redis is None:
        return
    await redis.delete("ai_lock:" + user_id)