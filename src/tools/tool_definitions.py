"""
Tool schemas for Gemini. Every function below exists ONLY so Gemini can read
its name, parameters, and docstring to know the tool exists — none of these
bodies ever run. The SDK builds the schema from the type hints + docstring
automatically. The REAL work happens in analytics_tool.py, dispatched by
name in execute_tool() at the bottom.
"""

from typing import Any

try:
    from . import analytics_tool
except ImportError:
    from src.tools import analytics_tool  # type: ignore[no-redef]


def get_dora_metrics(repo_id: int, days: int = 30) -> None:
    """Get the 4 DORA metrics (deployment frequency, lead time, change
    failure rate, mean time to recovery) for a repository, including
    performance levels (elite/high/medium/low) and current values.

    Args:
        repo_id: The repository ID to fetch metrics for.
        days: Time window in days. Defaults to 30.
    """


def get_cycle_time_trend(repo_id: int, days: int = 90) -> None:
    """Get the weekly cycle time and lead time trend over a period. Use
    this to find out WHEN a slowdown or speedup started.

    Args:
        repo_id: The repository ID.
        days: Time window in days. 90 is recommended for trend analysis.
    """


def get_contributor_stats(repo_id: int, days: int = 30) -> None:
    """Get a leaderboard of PR authors and reviewers — who is merging the
    most PRs, who reviews fastest, who does the most reviews.

    Args:
        repo_id: The repository ID.
        days: Time window in days.
    """


def get_review_heatmap(repo_id: int, days: int = 90) -> None:
    """Get code review activity broken down by day of week and hour of
    day, to answer questions about review timing or bottlenecks.

    Args:
        repo_id: The repository ID.
        days: Time window in days.
    """


def get_open_prs(repo_id: int) -> None:
    """Get all currently open PRs and how long each has been waiting.
    Flags PRs as stale (>48h) or critical (>120h). Use this to answer
    "what's blocked right now" questions.

    Args:
        repo_id: The repository ID.
    """


def get_deployment_history(repo_id: int, days: int = 84) -> None:
    """Get deployment frequency and build duration trends — how often the
    team ships and whether the CI pipeline is getting faster or slower.

    Args:
        repo_id: The repository ID.
        days: Time window in days.
    """


def get_pr_size_analysis(repo_id: int, days: int = 30) -> None:
    """Get PR size distribution (small/medium/large/xlarge) and how size
    correlates with cycle time.

    Args:
        repo_id: The repository ID.
        days: Time window in days.
    """


def get_contributor_trend(repo_id: int, username: str, days: int = 90) -> None:
    """Get week-by-week activity for one specific engineer: PR count,
    cycle time, and lines changed over time.

    Args:
        repo_id: The repository ID.
        username: The GitHub username to look up.
        days: Time window in days.
    """


# The list Gemini actually receives as `tools=`.
TOOL_FUNCTIONS: list[Any] = [
    get_dora_metrics,
    get_cycle_time_trend,
    get_contributor_stats,
    get_review_heatmap,
    get_open_prs,
    get_deployment_history,
    get_pr_size_analysis,
    get_contributor_trend,
]


async def execute_tool(tool_name: str, args: dict[str, Any]) -> Any:
    """Given the tool name + args Gemini picked, call the REAL function."""
    match tool_name:
        case "get_dora_metrics":
            return await analytics_tool.get_dora(**args)
        case "get_cycle_time_trend":
            return await analytics_tool.get_cycle_time_trend(**args)
        case "get_contributor_stats":
            return await analytics_tool.get_contributors(**args)
        case "get_review_heatmap":
            return await analytics_tool.get_review_heatmap(**args)
        case "get_open_prs":
            return await analytics_tool.get_open_prs(**args)
        case "get_deployment_history":
            freq = await analytics_tool.get_deployment_frequency(**args)
            dur = await analytics_tool.get_build_duration(**args)
            return {"frequency": freq, "duration": dur}
        case "get_pr_size_analysis":
            return await analytics_tool.get_cycle_time_by_size(**args)
        case "get_contributor_trend":
            return await analytics_tool.get_contributor_trend(**args)
        case _:
            raise ValueError(f"Unknown tool: {tool_name}")
