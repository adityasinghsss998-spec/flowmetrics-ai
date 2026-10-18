import logging
from datetime import date

from src.tools import analytics_tool

logger = logging.getLogger("ai_service")

# ---- Thresholds: change these to make alerts more or less sensitive ----
CYCLE_SPIKE_MULTIPLIER = 2.0   # latest week must be 2x the earlier average
CYCLE_SPIKE_MIN_HOURS = 24.0   # ...and at least a day, so tiny numbers don't trigger
CYCLE_MIN_PRIOR_WEEKS = 2      # need 2+ earlier weeks to compare against
CYCLE_MAX_AGE_DAYS = 14        # ignore if the latest week with data is older than this
FAILURE_RATE_PERCENT = 30.0    # alert if 30%+ of recent deployments failed
FAILURE_MIN_DEPLOYMENTS = 3    # ...but only with at least 3 deployments
FAILURE_WINDOW_DAYS = 28
STALE_PR_COUNT = 3             # alert if 3+ PRs are stale (waiting over 48h)
NO_DEPLOY_QUIET_DAYS = 14      # alert if nothing deployed for 14 days...
NO_DEPLOY_HISTORY_DAYS = 84    # ...but only if it did deploy before that


def _num(value, default=0.0) -> float:
    """analytics-service sends some numbers as text ('47.23'); convert safely."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


async def _check_cycle_time(repo_id: int):
    trend = (await analytics_tool.get_cycle_time_trend(repo_id, days=90)).get("data") or []
    trend = sorted(trend, key=lambda w: w["week_start"])
    if len(trend) < CYCLE_MIN_PRIOR_WEEKS + 1:
        return None

    latest, earlier = trend[-1], trend[:-1]
    if (date.today() - date.fromisoformat(latest["week_start"][:10])).days > CYCLE_MAX_AGE_DAYS:
        return None  # the data is old news, not a current problem

    latest_hours = _num(latest["avg_cycle_hours"])
    baseline = sum(_num(w["avg_cycle_hours"]) for w in earlier) / len(earlier)
    if latest_hours >= CYCLE_SPIKE_MIN_HOURS and latest_hours > baseline * CYCLE_SPIKE_MULTIPLIER:
        return {
            "type": "cycle_time_spike",
            "current_value": f"{latest_hours:.1f}h average cycle time this week",
            "threshold": f"more than {CYCLE_SPIKE_MULTIPLIER}x the earlier average ({baseline:.1f}h)",
            "facts": {"latest_week_hours": latest_hours, "earlier_average_hours": round(baseline, 1)},
        }
    return None


async def _check_deployment_failures(repo_id: int):
    rows = (await analytics_tool.get_deployment_frequency(repo_id, days=FAILURE_WINDOW_DAYS)).get("data") or []
    total = sum(_num(r.get("total_deployments")) for r in rows)
    succeeded = sum(_num(r.get("successful")) for r in rows)
    if total < FAILURE_MIN_DEPLOYMENTS:
        return None

    rate = (total - succeeded) / total * 100
    if rate >= FAILURE_RATE_PERCENT:
        return {
            "type": "deployment_failure",
            "current_value": f"{rate:.0f}% of {int(total)} deployments failed in the last {FAILURE_WINDOW_DAYS} days",
            "threshold": f"{FAILURE_RATE_PERCENT:.0f}% failure rate",
            "facts": {"deployments": int(total), "failed": int(total - succeeded), "failure_rate_percent": round(rate)},
        }
    return None


async def _check_stale_prs(repo_id: int):
    prs = (await analytics_tool.get_open_prs(repo_id)).get("data") or []
    stale = [p for p in prs if p.get("is_stale") or p.get("is_critical")]
    critical = [p for p in prs if p.get("is_critical")]
    if len(stale) < STALE_PR_COUNT and not critical:
        return None
    return {
        "type": "stale_prs",
        "current_value": f"{len(stale)} PRs stuck waiting ({len(critical)} for over 5 days)",
        "threshold": f"{STALE_PR_COUNT} or more stale PRs, or any PR waiting over 5 days",
        "facts": {"stale_prs": len(stale), "critical_prs": len(critical),
                  "examples": [f"#{p.get('number')} {p.get('title')}" for p in stale[:3]]},
    }


async def _check_no_deployments(repo_id: int):
    recent = (await analytics_tool.get_deployment_frequency(repo_id, days=NO_DEPLOY_QUIET_DAYS)).get("data") or []
    if sum(_num(r.get("total_deployments")) for r in recent) > 0:
        return None  # it deployed recently, all fine

    history = (await analytics_tool.get_deployment_frequency(repo_id, days=NO_DEPLOY_HISTORY_DAYS)).get("data") or []
    if sum(_num(r.get("total_deployments")) for r in history) == 0:
        return None  # it never deploys, so "no deployments" isn't news
    return {
        "type": "no_deployments",
        "current_value": f"no deployments in the last {NO_DEPLOY_QUIET_DAYS} days",
        "threshold": f"{NO_DEPLOY_QUIET_DAYS} days without a deployment",
        "facts": {"quiet_days": NO_DEPLOY_QUIET_DAYS},
    }


async def detect_anomalies(repo_id: int) -> list[dict]:
    """Run all four checks. One check failing never stops the others."""
    found = []
    for check in (_check_cycle_time, _check_deployment_failures, _check_stale_prs, _check_no_deployments):
        try:
            result = await check(repo_id)
        except Exception as e:
            logger.warning("Anomaly check %s failed for repo %s: %s", check.__name__, repo_id, e)
            continue
        if result:
            found.append(result)
    return found