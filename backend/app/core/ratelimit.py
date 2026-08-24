"""
In-process token-bucket rate limiting.

Each swarm run costs LLM tokens, a cloud sandbox, and GitHub API quota, so the
trigger endpoint needs a ceiling. This implementation is per-process and
therefore correct for a single replica; a multi-replica deployment should point
`RateLimiter` at Redis instead. The interface is kept narrow so that swap is a
one-file change.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from fastapi import HTTPException, Request, status

from app.config import settings


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


@dataclass
class RateLimiter:
    """Refills `rate` tokens per `period` seconds, capped at `burst`."""

    rate: int
    period: float
    burst: int | None = None
    _buckets: dict[str, _Bucket] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self) -> None:
        self._capacity = float(self.burst or self.rate)
        self._refill_per_second = self.rate / self.period

    async def check(self, key: str) -> tuple[bool, float]:
        """Consume one token. Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        async with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=self._capacity, updated_at=now)
                self._buckets[key] = bucket

            elapsed = now - bucket.updated_at
            bucket.tokens = min(self._capacity, bucket.tokens + elapsed * self._refill_per_second)
            bucket.updated_at = now

            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return True, 0.0

            deficit = 1.0 - bucket.tokens
            return False, deficit / self._refill_per_second

    async def prune(self, max_idle_seconds: float = 3600.0) -> int:
        """Drop buckets that have been full and untouched — bounds memory."""
        now = time.monotonic()
        async with self._lock:
            stale = [k for k, b in self._buckets.items() if now - b.updated_at > max_idle_seconds]
            for k in stale:
                del self._buckets[k]
            return len(stale)

    def reset(self) -> None:
        self._buckets.clear()


trigger_limiter = RateLimiter(
    rate=settings.RATE_LIMIT_TRIGGERS_PER_HOUR,
    period=3600.0,
)
read_limiter = RateLimiter(
    rate=settings.RATE_LIMIT_READS_PER_MINUTE,
    period=60.0,
)


def client_key(request: Request) -> str:
    """
    Identify the caller for bucketing.

    Prefers the API key fingerprint; falls back to the peer address. Note that
    X-Forwarded-For is only trustworthy behind a proxy that overwrites it, so it
    is used solely when the app is told it sits behind one.
    """
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"key:{hash(api_key)}"
    if settings.is_production:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return f"ip:{forwarded.split(',')[0].strip()}"
    return f"ip:{request.client.host if request.client else 'unknown'}"


async def enforce(limiter: RateLimiter, request: Request) -> None:
    if not settings.RATE_LIMIT_ENABLED:
        return
    allowed, retry_after = await limiter.check(client_key(request))
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(max(1, int(retry_after)))},
        )


async def rate_limit_triggers(request: Request) -> None:
    await enforce(trigger_limiter, request)


async def rate_limit_reads(request: Request) -> None:
    await enforce(read_limiter, request)
