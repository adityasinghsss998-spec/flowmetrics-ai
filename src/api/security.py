import hmac
import logging
from dataclasses import dataclass
from urllib.parse import quote

import httpx
from fastapi import HTTPException, Request
from sqlalchemy import select

from src.config.database import Repository, async_session_factory
from src.config.settings import get_settings

logger = logging.getLogger("ai_service")
settings = get_settings()

DEV_USER_ID = "dev-user"
MAX_USER_ID_LENGTH = 64
AUTH_SERVICE_TIMEOUT_SECONDS = 3.0

# Roles that may ask questions and read results, and roles that may approve actions.
VIEW_ROLES = ["owner", "admin", "member"]
APPROVE_ROLES = ["owner", "admin"]


@dataclass
class Caller:
    user_id: str
    is_dev: bool


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
        # Local development only: no key and no real user.
        return Caller(user_id=DEV_USER_ID, is_dev=True)

    sent_key = request.headers.get("x-internal-key", "")
    user_id = request.headers.get("x-user-id", "")
    logger.info("DEBUG HEADERS: %r", dict(request.headers))
    if not keys_match(sent_key, real_key):
        raise HTTPException(status_code=401, detail="Unauthorized.")

    user_id = request.headers.get("x-user-id", "")
    if user_id == "" or len(user_id) > MAX_USER_ID_LENGTH:
        raise HTTPException(status_code=401, detail="Unauthorized.")

    return Caller(user_id=user_id, is_dev=False)


def extract_role(response_body):
    """Read the role out of auth-service's answer. It accepts {"data": {"role": ...}} or {"role": ...}."""
    if not isinstance(response_body, dict):
        return "" 

    inner = response_body.get("data")
    if isinstance(inner, str):
        return inner.lower()

    if isinstance(inner, dict) and inner.get("role"):
        return str(inner["role"]).lower()

    # Handle {"role": "owner"}
    if response_body.get("role"):
        return str(response_body["role"]).lower()

    return ""


async def get_member_role(org_id, user_id):
    """Ask auth-service which role this user has in this organization. Empty text means no role."""
    url = (
        settings.AUTH_SERVICE_URL.rstrip("/")
        + "/api/v1/internal/orgs/" + str(org_id)
        + "/members/" + quote(user_id, safe="")
        + "/role"
    )

    try:
        async with httpx.AsyncClient(timeout=AUTH_SERVICE_TIMEOUT_SECONDS) as client:
            response = await client.get(url)
    except httpx.HTTPError as error:
        # If we cannot verify access, we refuse. Failing open here would be a security hole.
        logger.warning("auth-service role lookup failed: %s", error)
        raise HTTPException(status_code=503, detail="Could not verify your access right now. Please try again.")

    if response.status_code == 404:
        return ""  # Not a member of this organization.

    if response.status_code != 200:
        logger.warning("auth-service role lookup returned status %s", response.status_code)
        raise HTTPException(status_code=503, detail="Could not verify your access right now. Please try again.")

    try:
        body = response.json()
    except ValueError:
        logger.warning("auth-service role lookup returned something that is not JSON")
        raise HTTPException(status_code=503, detail="Could not verify your access right now. Please try again.")

    return extract_role(body)


async def authorize_repo(caller, repo_id, allowed_roles=None):
    """
    Check that this user may use this repository.
    1. Look up the repository's REAL organization in the database. We never trust an org id from the browser.
    2. Ask auth-service what role the user has in that organization.
    3. Allow only if the role is in the allowed list.
    """
    if allowed_roles is None:
        allowed_roles = VIEW_ROLES

    async with async_session_factory() as session:
        result = await session.execute(select(Repository.org_id).where(Repository.id == repo_id))
        repo_org_id = result.scalar_one_or_none()

    if repo_org_id is None:
        raise HTTPException(status_code=404, detail="Repository not found.")

    if caller.is_dev:
        # Local development without the gateway: there is no real user to check.
        return

    role = await get_member_role(repo_org_id, caller.user_id)
    if role not in allowed_roles:
        raise HTTPException(status_code=403, detail="You do not have access to this repository.")