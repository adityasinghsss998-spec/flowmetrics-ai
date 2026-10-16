import json

import aio_pika

try:
    from .settings import get_settings
except ImportError:
    from src.config.settings import get_settings

settings = get_settings()

EXCHANGE_NAME = "flowmetrics"


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


async def publish_message(
    connection: aio_pika.abc.AbstractRobustConnection,
    routing_key: str,
    payload: dict,
) -> None:
    """Publish a JSON-serializable payload to the flowmetrics topic exchange.
    Opens a short-lived channel per call — fine for low-frequency events
    like HITL requests and anomaly alerts, not a hot path."""
    channel = await connection.channel()
    try:
        exchange = await channel.declare_exchange(
            EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
        )
        message = aio_pika.Message(body=json.dumps(payload).encode("utf-8"))
        await exchange.publish(message, routing_key=routing_key)
    finally:
        await channel.close()