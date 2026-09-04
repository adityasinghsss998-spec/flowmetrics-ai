from typing import Any

import httpx

try:
    from ..config.settings import get_settings
except ImportError:
    from src.config.settings import get_settings

settings = get_settings()

BASE_URL = settings.ANALYTICS_SERVICE_URL.rstrip("/")
DEFAULT_TIMEOUT = 10.0


class AnalyticsClient:
    """Async client wrapper for all FlowMetrics analytics-service endpoints."""

    def __init__(self, base_url: str | None = None, timeout: float = DEFAULT_TIMEOUT):
        self.base_url = (base_url or BASE_URL).rstrip("/")
        self.timeout = timeout

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if client is not None:
            response = await client.request(method, url, params=params, timeout=self.timeout)
            response.raise_for_status()
            return response.json()

        async with httpx.AsyncClient(timeout=self.timeout) as local_client:
            response = await local_client.request(method, url, params=params)
            response.raise_for_status()
            return response.json()

    async def get_dora(
        self, repo_id: int, days: int = 30, client: httpx.AsyncClient | None = None
    ) -> dict[str, Any]:
        """GET /api/v1/analytics/dora?repoId=N&days=30"""
        return await self._request(
            "GET",
            "/api/v1/analytics/dora",
            params={"repoId": repo_id, "days": days},
            client=client,
        )

    async def get_cycle_time_trend(
        self, repo_id: int, days: int = 90, client: httpx.AsyncClient | None = None
    ) -> dict[str, Any]:
        """GET /api/v1/analytics/cycle-time/trend?repoId=N&days=90"""
        return await self._request(
            "GET",
            "/api/v1/analytics/cycle-time/trend",
            params={"repoId": repo_id, "days": days},
            client=client,
        )

    async def get_cycle_time_summary(
        self, repo_id: int, days: int = 30, client: httpx.AsyncClient | None = None
    ) -> dict[str, Any]:
        """GET /api/v1/analytics/cycle-time/summary?repoId=N&days=30"""
        return await self._request(
            "GET",
            "/api/v1/analytics/cycle-time/summary",
            params={"repoId": repo_id, "days": days},
            client=client,
        )

    async def get_cycle_time_by_size(
        self, repo_id: int, days: int = 30, client: httpx.AsyncClient | None = None
    ) -> dict[str, Any]:
        """GET /api/v1/analytics/cycle-time/by-size?repoId=N&days=30"""
        return await self._request(
            "GET",
            "/api/v1/analytics/cycle-time/by-size",
            params={"repoId": repo_id, "days": days},
            client=client,
        )

    async def get_contributors(
        self, repo_id: int, days: int = 30, client: httpx.AsyncClient | None = None
    ) -> dict[str, Any]:
        """GET /api/v1/analytics/contributors?repoId=N&days=30"""
        return await self._request(
            "GET",
            "/api/v1/analytics/contributors",
            params={"repoId": repo_id, "days": days},
            client=client,
        )

    async def get_contributor_trend(
        self, repo_id: int, username: str, days: int = 90, client: httpx.AsyncClient | None = None
    ) -> dict[str, Any]:
        """GET /api/v1/analytics/contributors/:username/trend?repoId=N&days=90"""
        return await self._request(
            "GET",
            f"/api/v1/analytics/contributors/{username}/trend",
            params={"repoId": repo_id, "days": days},
            client=client,
        )

    async def get_review_heatmap(
        self, repo_id: int, days: int = 90, client: httpx.AsyncClient | None = None
    ) -> dict[str, Any]:
        """GET /api/v1/analytics/reviews/heatmap?repoId=N&days=90"""
        return await self._request(
            "GET",
            "/api/v1/analytics/reviews/heatmap",
            params={"repoId": repo_id, "days": days},
            client=client,
        )

    async def get_deployment_frequency(
        self, repo_id: int, days: int = 84, client: httpx.AsyncClient | None = None
    ) -> dict[str, Any]:
        """GET /api/v1/analytics/deployments/frequency?repoId=N&days=84"""
        return await self._request(
            "GET",
            "/api/v1/analytics/deployments/frequency",
            params={"repoId": repo_id, "days": days},
            client=client,
        )

    async def get_build_duration(
        self, repo_id: int, days: int = 84, client: httpx.AsyncClient | None = None
    ) -> dict[str, Any]:
        """GET /api/v1/analytics/deployments/build-duration?repoId=N&days=84"""
        return await self._request(
            "GET",
            "/api/v1/analytics/deployments/build-duration",
            params={"repoId": repo_id, "days": days},
            client=client,
        )

    async def get_recent_deployments(
        self, repo_id: int, limit: int = 15, client: httpx.AsyncClient | None = None
    ) -> dict[str, Any]:
        """GET /api/v1/analytics/deployments/recent?repoId=N&limit=15"""
        return await self._request(
            "GET",
            "/api/v1/analytics/deployments/recent",
            params={"repoId": repo_id, "limit": limit},
            client=client,
        )

    async def get_open_prs(
        self, repo_id: int, client: httpx.AsyncClient | None = None
    ) -> dict[str, Any]:
        """GET /api/v1/analytics/prs/open?repoId=N"""
        return await self._request(
            "GET",
            "/api/v1/analytics/prs/open",
            params={"repoId": repo_id},
            client=client,
        )

    async def invalidate_cache(
        self, repo_id: int, client: httpx.AsyncClient | None = None
    ) -> dict[str, Any]:
        """DELETE /api/v1/analytics/cache/:repoId"""
        return await self._request(
            "DELETE",
            f"/api/v1/analytics/cache/{repo_id}",
            client=client,
        )


default_client = AnalyticsClient()

# Functional exports matching tool-execution expectations
get_dora = default_client.get_dora
get_cycle_time_trend = default_client.get_cycle_time_trend
get_cycle_time_summary = default_client.get_cycle_time_summary
get_cycle_time_by_size = default_client.get_cycle_time_by_size
get_contributors = default_client.get_contributors
get_contributor_trend = default_client.get_contributor_trend
get_review_heatmap = default_client.get_review_heatmap
get_deployment_frequency = default_client.get_deployment_frequency
get_build_duration = default_client.get_build_duration
get_recent_deployments = default_client.get_recent_deployments
get_open_prs = default_client.get_open_prs
invalidate_cache = default_client.invalidate_cache
