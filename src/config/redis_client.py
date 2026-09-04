import redis.asyncio as aioredis

try:
    from .settings import get_settings
except ImportError:
    from src.config.settings import get_settings

settings = get_settings()


def get_redis_client() -> aioredis.Redis:
    """Create and return an async Redis client."""
    return aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=2.0,
        socket_timeout=2.0,
    )


async def check_redis_connection(redis_client: aioredis.Redis) -> dict:
    """Check Redis connectivity and report status."""
    try:
        res = await redis_client.ping()
        return {"status": "healthy" if res else "unhealthy", "connected": bool(res)}
    except Exception as e:
        return {"status": "unhealthy", "connected": False, "error": str(e)}
