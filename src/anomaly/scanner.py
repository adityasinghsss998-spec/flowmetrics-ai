import logging
from datetime import datetime, timezone

from google import genai
from sqlalchemy import select

from src.anomaly.detector import detect_anomalies
from src.config.database import Repository, async_session_factory
from src.config.rabbitmq import publish_message
from src.config.settings import get_settings

logger = logging.getLogger("ai_service")
settings = get_settings()
client = genai.Client(api_key=settings.GEMINI_API_KEY)

ALERT_COOLDOWN_SECONDS = 24 * 60 * 60  # don't repeat the same alert for 24 hours


async def _describe(repo_name: str, anomaly: dict) -> str:
    """Ask Gemini for a short explanation. If it fails, use a plain sentence."""
    fallback = (f"{repo_name}: {anomaly['type'].replace('_', ' ')} - "
                f"{anomaly['current_value']} (alert level: {anomaly['threshold']}).")
    prompt = (
        "Write 2 short sentences for an engineering lead explaining this alert. "
        "Use only the facts below. Do not invent numbers.\n"
        f"Repository: {repo_name}\nProblem: {anomaly['type']}\n"
        f"Current: {anomaly['current_value']}\nAlert level: {anomaly['threshold']}\n"
        f"Facts: {anomaly['facts']}"
    )
    try:
        response = await client.aio.models.generate_content(model=settings.GEMINI_MODEL, contents=prompt)
        return (response.text or "").strip() or fallback
    except Exception as e:
        logger.warning("Gemini description failed, using plain text instead: %s", e)
        return fallback


async def _should_send(redis, repo_id: int, anomaly_type: str, force: bool) -> bool:
    """True if we haven't already alerted about this repo + problem recently."""
    if force or redis is None:
        return True
    try:
        # nx=True means "only write if the note doesn't exist yet"
        was_new = await redis.set(f"anomaly_sent:{repo_id}:{anomaly_type}", "1",
                                  nx=True, ex=ALERT_COOLDOWN_SECONDS)
        return bool(was_new)
    except Exception as e:
        logger.warning("Redis unavailable, skipping duplicate check: %s", e)
        return True


async def scan_repo(app, repo_id: int, repo_name: str, force: bool = False,
                    anomalies: list[dict] | None = None) -> list[dict]:
    """Check one repo and publish an alert for each problem found."""
    if anomalies is None:
        anomalies = await detect_anomalies(repo_id)

    if not anomalies:
        return []

    sent = []
    for anomaly in anomalies:
        if not await _should_send(getattr(app.state, "redis", None), repo_id, anomaly["type"], force):
            logger.info("Skipping %s for repo %s (alerted recently)", anomaly["type"], repo_id)
            continue

        payload = {
            "recipientEmail": settings.ALERT_EMAIL,
            "repoName": repo_name,
            "repoId": repo_id,
            "anomalyType": anomaly["type"],
            "description": await _describe(repo_name, anomaly),
            "currentValue": anomaly["current_value"],
            "threshold": anomaly["threshold"],
            "detectedAt": datetime.now(timezone.utc).isoformat(),
        }

        rabbitmq = getattr(app.state, "rabbitmq", None)
        if rabbitmq is None:
            logger.warning("RabbitMQ not connected, alert not published")
            continue
        try:
            await publish_message(rabbitmq, "anomaly.detected", payload)
            sent.append(payload)
        except Exception as e:
            logger.warning("Failed to publish alert: %s", e)
    return sent


async def scan_all_repos(app) -> None:
    """The hourly job: scan every repo in the database."""
    logger.info("Anomaly scan started")
    async with async_session_factory() as session:
        repos = (await session.execute(select(Repository.id, Repository.full_name))).all()

    total = 0
    for repo_id, repo_name in repos:
        try:
            total += len(await scan_repo(app, repo_id, repo_name))
        except Exception as e:
            logger.warning("Scan failed for repo %s: %s", repo_id, e)
    logger.info("Anomaly scan finished: %d alert(s) sent across %d repo(s)", total, len(repos))