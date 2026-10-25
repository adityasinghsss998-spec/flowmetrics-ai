from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from src.config.database import Repository, async_session_factory
from src.digest.generator import generate_digest

router = APIRouter()


class DigestPreviewRequest(BaseModel):
    repoId: int
    orgName: str = "your team"


@router.post("/digest/preview")
async def preview_digest(payload: DigestPreviewRequest):
    async with async_session_factory() as session:
        result = await session.execute(
            select(Repository.full_name).where(Repository.id == payload.repoId)
        )
        repo_name = result.scalar_one_or_none()

    if repo_name is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    try:
        digest = await generate_digest(payload.repoId, repo_name, payload.orgName)
    except Exception as error:
        raise HTTPException(status_code=503, detail="Could not generate digest: " + str(error))

    return digest