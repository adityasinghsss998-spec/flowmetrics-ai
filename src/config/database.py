import ssl
from collections.abc import AsyncGenerator

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

try:
    from .settings import get_settings
except ImportError:
    from src.config.settings import get_settings

settings = get_settings()


class Base(DeclarativeBase):
    pass


# =====================================================================
# Read-only Declarative Models mapped to flowmetrics_github tables
# =====================================================================

class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    github_repo_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    org_id: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(100), default="main")
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    webhook_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_synced_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    github_access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)

    pull_requests: Mapped[list["PullRequest"]] = relationship(
        "PullRequest", back_populates="repository", lazy="selectin"
    )
    deployments: Mapped[list["Deployment"]] = relationship(
        "Deployment", back_populates="repository", lazy="selectin"
    )


class PullRequest(Base):
    __tablename__ = "pull_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    github_pr_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    repo_id: Mapped[int] = mapped_column(Integer, ForeignKey("repositories.id"), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    author_github_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    author_username: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(50), default="open")
    base_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    head_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    additions: Mapped[int] = mapped_column(Integer, default=0)
    deletions: Mapped[int] = mapped_column(Integer, default=0)
    changed_files: Mapped[int] = mapped_column(Integer, default=0)
    commits_count: Mapped[int] = mapped_column(Integer, default=0)
    review_comments_count: Mapped[int] = mapped_column(Integer, default=0)
    cycle_time_hours: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    first_review_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    pr_opened_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    pr_merged_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    pr_closed_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)

    repository: Mapped["Repository"] = relationship("Repository", back_populates="pull_requests")
    reviews: Mapped[list["PrReview"]] = relationship("PrReview", back_populates="pull_request")
    commits: Mapped[list["Commit"]] = relationship("Commit", back_populates="pull_request")


class PrReview(Base):
    __tablename__ = "pr_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    github_review_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    pr_id: Mapped[int] = mapped_column(Integer, ForeignKey("pull_requests.id"), nullable=False)
    repo_id: Mapped[int] = mapped_column(Integer, ForeignKey("repositories.id"), nullable=False)
    reviewer_github_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reviewer_username: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(50), nullable=False)
    submitted_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)

    pull_request: Mapped["PullRequest"] = relationship("PullRequest", back_populates="reviews")


class Commit(Base):
    __tablename__ = "commits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sha: Mapped[str] = mapped_column(String(40), nullable=False)
    repo_id: Mapped[int] = mapped_column(Integer, ForeignKey("repositories.id"), nullable=False)
    pr_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("pull_requests.id"), nullable=True)
    author_github_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    author_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    additions: Mapped[int] = mapped_column(Integer, default=0)
    deletions: Mapped[int] = mapped_column(Integer, default=0)
    committed_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)

    pull_request: Mapped["PullRequest | None"] = relationship("PullRequest", back_populates="commits")


class Deployment(Base):
    __tablename__ = "deployments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    github_deployment_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    repo_id: Mapped[int] = mapped_column(Integer, ForeignKey("repositories.id"), nullable=False)
    environment: Mapped[str] = mapped_column(String(100), default="production")
    status: Mapped[str] = mapped_column(String(50), default="pending")
    sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    deployed_by_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lead_time_hours: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    deployed_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    build_duration_minutes: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    created_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)

    repository: Mapped["Repository"] = relationship("Repository", back_populates="deployments")


# =====================================================================
# Database Engine and Session Factory
# =====================================================================

def create_engine_and_session() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    connect_args = {}
    if settings.DB_SSL:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        connect_args["ssl"] = ssl_ctx

    engine = create_async_engine(
        settings.async_database_url,
        connect_args=connect_args,
        echo=False,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    return engine, session_factory


engine, async_session_factory = create_engine_and_session()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
