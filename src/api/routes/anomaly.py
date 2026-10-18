from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from src.anomaly.scanner import scan_repo
from src.config.database import Repository, async_session_factory

router = APIRouter()


class ScanRequest(BaseModel):
    repoId: int
    orgId: int
    force: bool = False  # true = ignore the 24-hour "already alerted" note
    demo: bool = False  # true = send a fake TEST alert to prove the pipeline works


DEMO_ANOMALY = {
    "type": "stale_prs",
    "current_value": "4 open PRs waiting more than 48 hours (TEST ALERT)",
    "threshold": "3 or more stale PRs",
    "facts": {"stale_prs": 4, "note": "This is a test alert"},
}


@router.post("/anomaly/scan")
async def scan(payload: ScanRequest, request: Request):
    async with async_session_factory() as session:
        repo_name = (
            await session.execute(
                select(Repository.full_name).where(Repository.id == payload.repoId)
            )
        ).scalar_one_or_none()
    if repo_name is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    alerts = await scan_repo(
        request.app,
        payload.repoId,
        repo_name,
        force=payload.force or payload.demo,
        anomalies=[DEMO_ANOMALY] if payload.demo else None,
    )
    return {"repo": repo_name, "alertPublished": len(alerts), "anomalies": alerts}
