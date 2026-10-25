from fastapi.dependencies.utils import analyze_param
import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from src.anomaly.scanner import scan_all_repos
from src.api.routes.anomaly import router as anomaly_router
from src.api.routes.digest import router as digest_router
from src.consumers.weekly_digest import start_weekly_digest_consumer
# Configure WindowsSelectorEventLoopPolicy on Windows for SSL socket support
if sys.platform == "win32":
    policy_cls = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if isinstance(policy_cls, type):
        policy = policy_cls()
        if isinstance(policy, asyncio.AbstractEventLoopPolicy):
            asyncio.set_event_loop_policy(policy)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes.chat import router as chat_router
from src.api.routes.health import router as health_router
from src.api.routes.hitl import router as hitl_router
from src.config.database import engine
from src.config.rabbitmq import get_rabbitmq_connection
from src.config.redis_client import get_redis_client
from src.config.settings import get_settings
from src.api.routes.rag import router as rag_router

logger = logging.getLogger("ai_service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan manager for FastAPI. Opens connections on startup and cleans up on shutdown."""
    logger.info("Initializing ai-service dependencies...")

    # 1. Stash DB Engine on app.state
    app.state.db_engine = engine

    # 2. Redis Client
    app.state.redis = None
    redis_client = None
    try:
        redis_client = get_redis_client()
        await redis_client.ping()
        app.state.redis = redis_client
        logger.info("Redis connected successfully")
    except Exception as e:
        logger.warning(f"Redis connection warning during startup: {e}")
        # Keep client instance on app.state so /health can report actual error
        if redis_client is not None:
            app.state.redis = redis_client

    # 3. RabbitMQ Connection
    app.state.rabbitmq = None
    try:
        rabbitmq_conn = await get_rabbitmq_connection()
        app.state.rabbitmq = rabbitmq_conn
        logger.info("RabbitMQ connected successfully")
    except Exception as e:
        logger.warning(f"RabbitMQ connection warning during startup: {e}")
    
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        scan_all_repos,"interval",hours=1,args=[app],
        id="anomaly_scan",max_instances=1,coalesce=True,
    )
    scheduler.start()
    app.state.scheduler = scheduler 
    logger.info("Anomaly scan scheduled every hour.")

    # 5. Weekly digest listener
    if app.state.rabbitmq is not None:
        try:
            await start_weekly_digest_consumer(app)
            logger.info("Weekly digest listener started")
        except Exception as e:
            logger.warning(f"Could not start weekly digest listener: {e}")
    yield 

    # Shutdown sequence
    logger.info("Shutting down ai-service dependencies...")
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler is not None:
        scheduler.shutdown(wait=False)    

    shutdown_rabbitmq = getattr(app.state, "rabbitmq", None)
    if shutdown_rabbitmq is not None:
        try:
            await shutdown_rabbitmq.close()
            logger.info("RabbitMQ connection closed.")
        except Exception as e:
            logger.warning(f"Error closing RabbitMQ connection: {e}")

    shutdown_redis = getattr(app.state, "redis", None)
    if shutdown_redis is not None:
        try:
            await shutdown_redis.close()
            logger.info("Redis connection closed.")
        except Exception as e:
            logger.warning(f"Error closing Redis connection: {e}")

    shutdown_db = getattr(app.state, "db_engine", None)
    if shutdown_db is not None:
        try:
            await shutdown_db.dispose()
            logger.info("Database engine disposed.")
        except Exception as e:
            logger.warning(f"Error disposing database engine: {e}")


app = FastAPI(
    title="FlowMetrics AI Service",
    description="Agentic AI analyst microservice for FlowMetrics platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(chat_router)
app.include_router(hitl_router)
app.include_router(anomaly_router)
app.include_router(rag_router)
app.include_router(digest_router)
@app.get("/")
async def root():
    return {
        "service": "ai-service",
        "status": "online",
        "docs": "/docs",
        "health": "/health",
    }
