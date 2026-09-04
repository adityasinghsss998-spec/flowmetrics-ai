import aio_pika

try:
    from .settings import get_settings
except ImportError:
    from src.config.settings import get_settings

settings = get_settings()


async def get_rabbitmq_connection() -> aio_pika.abc.AbstractRobustConnection:
    """Connect to RabbitMQ asynchronously with robust reconnection."""
    return await aio_pika.connect_robust(
        settings.RABBITMQ_URL,
        timeout=5.0,
    )


async def check_rabbitmq_connection(connection: aio_pika.abc.AbstractRobustConnection | None) -> dict:
    """Check RabbitMQ connectivity and report status."""
    if connection is None:
        return {"status": "unhealthy", "connected": False, "error": "Connection is None"}
    try:
        if not connection.is_closed:
            return {"status": "healthy", "connected": True}
        return {"status": "unhealthy", "connected": False, "error": "Connection is closed"}
    except Exception as e:
        return {"status": "unhealthy", "connected": False, "error": str(e)}
