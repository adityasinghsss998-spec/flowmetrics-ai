import json
import logging
from datetime import datetime, timezone

import aio_pika

from src.config.rabbitmq import publish_message
from src.digest.generator import generate_digest

logger = logging.getLogger("ai_service")

EXCHANGE_NAME = "flowmetrics"
QUEUE_NAME = "ai.weekly_digest"
INCOMING_ROUTING_KEY = "weekly.digest"
OUTGOING_ROUTING_KEY = "ai.digest.ready"


async def handle_message(app, message):
    async with message.process():
        try:
            payload = json.loads(message.body)
            repo_id = int(payload["repoId"])
            repo_name = payload.get("repoName", "your repository")
            org_name = payload.get("orgName", "your team")
            recipient_email = payload.get("recipientEmail", "")
        except Exception as error:
            logger.warning("Weekly digest message was not valid, skipping: %s", error)
            return

        try:
            digest = await generate_digest(repo_id, repo_name, org_name)
        except Exception as error:
            # Not a problem: the normal template digest still goes out from
            # notification-service, so the team still gets an email.
            logger.warning("Could not write AI digest for repo %s: %s", repo_id, error)
            return 

        outgoing_payload = {
            "recipientEmail": recipient_email,
            "orgName": org_name,
            "repoName": repo_name,
            "repoId": repo_id,
            "subject": digest["subject"],
            "narrative": digest["narrative"],
            "generatedAt": datetime.now(timezone.utc).isoformat(),
        }

        try:
            await publish_message(app.state.rabbitmq, OUTGOING_ROUTING_KEY, outgoing_payload)
            logger.info("AI weekly digest published for repo %s", repo_id)
        except Exception as error:
            logger.warning("Could not publish AI digest for repo %s: %s", repo_id, error)


async def start_weekly_digest_consumer(app):
    connection = app.state.rabbitmq
    channel = await connection.channel()

    # Handle one message at a time. Each digest makes several Gemini calls,
    # and the free tier only allows a few per minute.
    await channel.set_qos(prefetch_count=1)

    exchange = await channel.declare_exchange(
        EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
    )
    queue = await channel.declare_queue(QUEUE_NAME, durable=True)
    await queue.bind(exchange, routing_key=INCOMING_ROUTING_KEY)

    async def on_message(message):
        await handle_message(app, message)

    await queue.consume(on_message)

    # Keep a reference so the channel stays open while the app runs.
    app.state.digest_channel = channel