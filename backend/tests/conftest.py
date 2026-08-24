"""
Shared test fixtures.

Environment variables are set *before* any application module is imported,
because `app.config.settings` is constructed at import time and the database
engine is built from it. A SQLite file (not `:memory:`) is used so that every
connection in the pool sees the same schema.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMP_DIR = Path(tempfile.mkdtemp(prefix="swarm-tests-"))
_DB_PATH = _TMP_DIR / "test.db"

os.environ.update(
    ENVIRONMENT="development",
    DATABASE_URL=f"sqlite+aiosqlite:///{_DB_PATH.as_posix()}",
    LOG_LEVEL="WARNING",
    LOG_FORMAT="console",
    GITHUB_PAT="ghp_testtokentesttokentesttoken1234",
    GROQ_API_KEY="gsk_testtesttesttesttesttesttest",
    E2B_API_KEY="e2b_testtesttesttesttesttest",
    GITHUB_WEBHOOK_SECRET="test-webhook-secret",
    API_KEYS="",
    REPO_ALLOWLIST="*",
    RATE_LIMIT_ENABLED="false",
    CORS_ORIGINS="http://localhost:3000",
)

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core import redaction  # noqa: E402
from app.core.ratelimit import read_limiter, trigger_limiter  # noqa: E402
from app.db import repository  # noqa: E402
from app.db.database import AsyncSessionLocal, create_all, engine  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
async def _clean_database():
    """Recreate the schema around every test so cases cannot leak into each other."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await create_all()
    repository._seq_counters.clear()
    yield
    redaction._reset_for_tests()
    repository._seq_counters.clear()
    trigger_limiter.reset()
    read_limiter.reset()


@pytest.fixture
async def session():
    async with AsyncSessionLocal() as s:
        yield s


@pytest.fixture
async def client():
    """
    HTTP client bound directly to the ASGI app.

    Lifespan is deliberately not run: it starts the sandbox reaper and would
    leave a background task alive between tests.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def make_run():
    """Insert a run row and return it."""

    async def _make(**overrides):
        from app.db.models import Run, utcnow

        defaults: dict = dict(  # noqa: C408
            id=overrides.pop("id", "11111111-1111-1111-1111-111111111111"),
            repo_owner="octocat",
            repo_name="hello-world",
            issue_number=1,
            issue_title="Fix the thing",
            installation_id=0,
            status="running",
            phase="coder",
            iteration_count=0,
            created_at=utcnow(),
        )
        defaults.update(overrides)
        async with AsyncSessionLocal() as s:
            run = Run(**defaults)
            s.add(run)
            await s.commit()
            await s.refresh(run)
            return run

    return _make
