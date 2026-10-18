from sqlalchemy import select

from src.config.database import Commit, PullRequest, async_session_factory

# General knowledge shared by every repo (repo_id 0 means "applies to all").
STATIC_DOCS = [
    {"id": "static-dora", "repo_id": 0, "kind": "benchmark",
     "text": "DORA's four metrics are deployment frequency, lead time for changes, "
             "change failure rate, and time to restore service. Together they measure "
             "how fast and how safely a team delivers software."},
    {"id": "static-small-batches", "repo_id": 0, "kind": "best_practice",
     "text": "Higher-performing teams ship small changes often. Low deployment frequency "
             "usually means large, risky releases that are hard to review and roll back."},
    {"id": "static-pr-size", "repo_id": 0, "kind": "best_practice",
     "text": "Smaller pull requests are generally reviewed faster and with fewer missed "
             "issues, because a reviewer can understand the whole change at once."},
    {"id": "static-cycle-time", "repo_id": 0, "kind": "best_practice",
     "text": "Long cycle time is often caused by waiting for the first review, not by the "
             "review work itself. Reducing time to first review usually helps most."},
]


async def load_documents(repo_id: int) -> list[dict]:
    """Turn a repo's PRs and recent commits into searchable text."""
    async with async_session_factory() as session:
        prs = (await session.execute(
            select(PullRequest).where(PullRequest.repo_id == repo_id)
        )).scalars().all()
        commits = (await session.execute(
            select(Commit).where(Commit.repo_id == repo_id, Commit.message.isnot(None))
            .order_by(Commit.committed_at.desc()).limit(150)
        )).scalars().all()

    docs = []
    for pr in prs:
        text = (f"PR #{pr.number}: {pr.title} (by {pr.author_username}, "
                f"{pr.additions} lines added, {pr.deletions} removed, "
                f"cycle time {pr.cycle_time_hours}h)")
        docs.append({"id": f"r{repo_id}-pr-{pr.id}", "repo_id": repo_id, "kind": "pr", "text": text[:1000]})
    for c in commits:
        text = f"Commit by {c.author_username}: {c.message}"
        docs.append({"id": f"r{repo_id}-commit-{c.id}", "repo_id": repo_id, "kind": "commit", "text": text[:1000]})
    return docs