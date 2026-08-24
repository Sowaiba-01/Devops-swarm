"""
Async engine, session factory and lifecycle helpers.

Schema changes go through Alembic (`alembic upgrade head`), not
`create_all` — the previous startup path could not express a column rename or a
backfill and would silently diverge from production.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import text

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

# SQLite (used by the test suite) rejects pool sizing arguments.
_engine_kwargs: dict = {"echo": settings.DB_ECHO, "pool_pre_ping": True}
if _is_sqlite:
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs.update(
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
    )

engine: AsyncEngine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    """
    FastAPI dependency.

    The session is committed on a clean exit and rolled back on any exception,
    so a handler can never leave a half-applied transaction behind for the next
    borrower of that pooled connection.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Same contract as get_db, for background tasks outside the request cycle."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def check_connection() -> bool:
    """Round-trip the database. Used by the readiness probe."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.exception("Database connectivity check failed")
        return False


async def create_all() -> None:
    """
    Create tables directly from the models.

    For tests and throwaway local databases only — production uses Alembic.
    """
    from app.db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    await engine.dispose()
