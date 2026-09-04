import time
from typing import Any

import httpx
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

try:
    from ...config.database import async_session_factory
    from ...config.settings import get_settings
except ImportError:
    from src.config.database import async_session_factory
    from src.config.settings import get_settings

router = APIRouter(tags=["Health"])
settings = get_settings()


@router.get("/health")
async def health_check(request: Request) -> JSONResponse:
    """Comprehensive health check verifying MySQL, Redis, RabbitMQ, and Analytics Service."""
    checks: dict[str, Any] = {}
    overall_healthy = True

    # 1. MySQL (flowmetrics_github) Check
    db_start = time.perf_counter()
    try:
        async with async_session_factory() as session:
            result = await session.execute(text("SELECT 1"))
            val = result.scalar()
            db_duration_ms = round((time.perf_counter() - db_start) * 1000, 2)
            if val == 1:
                checks["mysql"] = {
                    "status": "healthy",
                    "latency_ms": db_duration_ms,
                    "database": settings.DB_NAME,
                    "host": settings.DB_HOST,
                }
            else:
                overall_healthy = False
                checks["mysql"] = {
                    "status": "unhealthy",
                    "error": f"Unexpected result from query: {val}",
                }
    except Exception as e:
        overall_healthy = False
        checks["mysql"] = {
            "status": "unhealthy",
            "error": str(e),
            "database": settings.DB_NAME,
        }

    # 2. Redis Check
    redis_client = getattr(request.app.state, "redis", None)
    redis_start = time.perf_counter()
    if redis_client is not None:
        try:
            pong = await redis_client.ping()
            redis_duration_ms = round((time.perf_counter() - redis_start) * 1000, 2)
            if pong:
                checks["redis"] = {
                    "status": "healthy",
                    "latency_ms": redis_duration_ms,
                    "url": settings.REDIS_URL,
                }
            else:
                overall_healthy = False
                checks["redis"] = {"status": "unhealthy", "error": "Ping failed"}
        except Exception as e:
            overall_healthy = False
            checks["redis"] = {"status": "unhealthy", "error": str(e)}
    else:
        checks["redis"] = {"status": "unhealthy", "error": "Redis client not initialized"}
        overall_healthy = False

    # 3. RabbitMQ Check
    rabbitmq_conn = getattr(request.app.state, "rabbitmq", None)
    if rabbitmq_conn is not None:
        try:
            if not rabbitmq_conn.is_closed:
                checks["rabbitmq"] = {
                    "status": "healthy",
                    "connected": True,
                }
            else:
                overall_healthy = False
                checks["rabbitmq"] = {
                    "status": "unhealthy",
                    "connected": False,
                    "error": "Connection is closed",
                }
        except Exception as e:
            overall_healthy = False
            checks["rabbitmq"] = {"status": "unhealthy", "error": str(e)}
    else:
        overall_healthy = False
        checks["rabbitmq"] = {
            "status": "unhealthy",
            "connected": False,
            "error": "RabbitMQ connection not initialized",
        }

    # 4. Analytics Service Dependency Check
    analytics_start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=2.0) as http_client:
            resp = await http_client.get(f"{settings.ANALYTICS_SERVICE_URL.rstrip('/')}/health")
            analytics_duration_ms = round((time.perf_counter() - analytics_start) * 1000, 2)
            checks["analytics_service"] = {
                "status": "healthy" if resp.status_code == 200 else "reachable",
                "http_status": resp.status_code,
                "latency_ms": analytics_duration_ms,
                "url": settings.ANALYTICS_SERVICE_URL,
            }
    except Exception as e:
        checks["analytics_service"] = {
            "status": "unreachable",
            "error": str(e),
            "url": settings.ANALYTICS_SERVICE_URL,
        }

    status_code = status.HTTP_200_OK if overall_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    response_payload = {
        "status": "healthy" if overall_healthy else "degraded",
        "service": "ai-service",
        "checks": checks,
    }
    return JSONResponse(status_code=status_code, content=response_payload)
