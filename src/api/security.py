from sqlalchemy.dialects.mysql import reserved_words
from sqlalchemy import Select
import hmac
import logging
from dataclasses import dataclass

from fastapi import HTTPException, Request
from sqlalchemy import select

from src.config.database import Repository, async_session_factory
from src.config.settings import get_settings

logger = logging.getLogger("ai_service")
settings = get_settings()

DEV_USER_ID = "dev-user"
MAX_USER_ID_LENGTH = 64


@dataclass
class Caller:
    user_id: str
    org_id: str


def keys_match(sent_key, real_key):
    # compare_digest takes the same time whether the first or the last character is wrong,
    # so an attacker cannot guess the key one character at a time by timing responses.
    sent_bytes = sent_key.encode("utf-8")
    real_bytes = real_key.encode("utf-8")
    return hmac.compare_digest(sent_bytes, real_bytes)


async def require_internal_caller(request: Request) -> Caller:
    """Only the API gateway may call this service. The gateway proves it with a shared secret."""
    real_key = settings.INTERNAL_API_KEY
    is_production = settings.ENVIRONMENT == "production"

    if real_key == "":
        if is_production:
            # Forgetting the key in production must never leave the service open.
            logger.error("INTERNAL_API_KEY is not set in production, refusing the request")
            raise HTTPException(status_code=503, detail="AI service is not configured.")
        # Local development only: no key needed.
        return Caller(user_id=DEV_USER_ID, org_id="")

    sent_key = request.headers.get("x-internal-key", "")
    if not keys_match(sent_key, real_key):
        raise HTTPException(status_code=401, detail="Unauthorized.")

    user_id = request.headers.get("x-user-id", "")
    if user_id == "" or len(user_id) > MAX_USER_ID_LENGTH:
        raise HTTPException(status_code=401, detail="Unauthorized.")

    org_id = request.headers.get("x-org-id", "")
    return Caller(user_id=user_id, org_id=org_id)


async def authorize_repo(caller, repo_id):
    """
    Check that this caller may see this repository.

    NOT FINISHED. Today it only checks that the repository exists, and that it belongs to the
    organization the gateway reported (when the gateway reports one). That is only safe if the
    gateway has verified the user really belongs to that organization. I will finish this after
    I see the gateway and the token contents. Do not expose the service publicly before then.
    """
    async with async_session_factory() as session:
        result=await session.execute(Select(Repository.org_id).where(Repository.id==repo_id))
        repo_org_id=result.scalar_one_or_none()
        if repo_org_id is None:
            raise HTTPException(status_code=404,detail="Repository not found")
        if repo_org_id != caller.org_id:
            raise HTTPException(status_code=403,detail="Repository does not belong to this organization") 
         