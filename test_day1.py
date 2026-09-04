import asyncio
import logging

from sqlalchemy import select, text

from src.config.database import Repository, async_session_factory
from src.config.rabbitmq import check_rabbitmq_connection, get_rabbitmq_connection
from src.config.redis_client import check_redis_connection, get_redis_client
from src.tools.analytics_tool import (
    get_build_duration,
    get_contributor_trend,
    get_contributors,
    get_cycle_time_by_size,
    get_cycle_time_summary,
    get_cycle_time_trend,
    get_deployment_frequency,
    get_dora,
    get_open_prs,
    get_recent_deployments,
    get_review_heatmap,
    invalidate_cache,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("test_day1")


async def test_mysql():
    logger.info("=== 1. Testing MySQL (flowmetrics_github) ===")
    try:
        async with async_session_factory() as session:
            res = await session.execute(text("SELECT 1"))
            logger.info(f"MySQL SELECT 1 returned: {res.scalar()}")

            stmt = select(Repository).limit(5)
            result = await session.execute(stmt)
            repos = result.scalars().all()
            logger.info(f"Retrieved {len(repos)} repositories:")
            for r in repos:
                logger.info(f"  - Repo ID {r.id}: {r.full_name} (owner_id={r.owner_id}, org_id={r.org_id})")
            return repos
    except Exception as e:
        logger.error(f"MySQL test failed: {e}")
        return []


async def test_redis():
    logger.info("=== 2. Testing Redis ===")
    client = get_redis_client()
    try:
        status = await check_redis_connection(client)
        logger.info(f"Redis status check: {status}")
    finally:
        await client.aclose()


async def test_rabbitmq():
    logger.info("=== 3. Testing RabbitMQ ===")
    try:
        conn = await get_rabbitmq_connection()
        status = await check_rabbitmq_connection(conn)
        logger.info(f"RabbitMQ status check: {status}")
        await conn.close()
    except Exception as e:
        logger.error(f"RabbitMQ connection failed: {e}")


async def test_analytics_endpoints(repo_id: int):
    logger.info(f"=== 4. Testing 12 Analytics Endpoints against repoId={repo_id} ===")

    endpoints = [
        ("get_dora", lambda: get_dora(repo_id, 30)),
        ("get_cycle_time_trend", lambda: get_cycle_time_trend(repo_id, 90)),
        ("get_cycle_time_summary", lambda: get_cycle_time_summary(repo_id, 30)),
        ("get_cycle_time_by_size", lambda: get_cycle_time_by_size(repo_id, 30)),
        ("get_contributors", lambda: get_contributors(repo_id, 30)),
        ("get_contributor_trend", lambda: get_contributor_trend(repo_id, "adityasinghsss998-spec", 90)),
        ("get_review_heatmap", lambda: get_review_heatmap(repo_id, 90)),
        ("get_deployment_frequency", lambda: get_deployment_frequency(repo_id, 84)),
        ("get_build_duration", lambda: get_build_duration(repo_id, 84)),
        ("get_recent_deployments", lambda: get_recent_deployments(repo_id, 15)),
        ("get_open_prs", lambda: get_open_prs(repo_id)),
        ("invalidate_cache", lambda: invalidate_cache(repo_id)),
    ]

    results = {}
    for name, fn in endpoints:
        try:
            res = await asyncio.wait_for(fn(), timeout=3.0)
            logger.info(f"Endpoint {name}: SUCCESS -> {res}")
            results[name] = {"status": "SUCCESS", "response": res}
        except TimeoutError:
            logger.warning(f"Endpoint {name}: TIMEOUT (3.0s, waiting on analytics-service downstream Redis)")
            results[name] = {"status": "TIMEOUT", "reason": "analytics-service hangs waiting for local Redis"}
        except Exception as e:
            logger.warning(f"Endpoint {name}: ERROR -> {e}")
            results[name] = {"status": "ERROR", "error": str(e)}

    return results


async def main():
    repos = await test_mysql()
    await test_redis()
    await test_rabbitmq()

    test_repo_id = repos[0].id if repos else 1
    logger.info(f"Using repoId={test_repo_id} for analytics endpoint tests")
    results = await test_analytics_endpoints(test_repo_id)

    print("\n" + "=" * 60)
    print("DAY 1 TEST RESULTS SUMMARY")
    print("=" * 60)
    for name, data in results.items():
        print(f"{name:<25}: {data['status']}")

    from src.config.database import engine
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
