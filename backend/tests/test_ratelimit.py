"""Token-bucket rate limiting."""

from __future__ import annotations

import asyncio

from app.core.ratelimit import RateLimiter


class TestTokenBucket:
    async def test_requests_within_the_budget_are_allowed(self):
        limiter = RateLimiter(rate=5, period=60.0)
        for _ in range(5):
            allowed, _ = await limiter.check("client")
            assert allowed

    async def test_the_next_request_over_the_budget_is_refused(self):
        limiter = RateLimiter(rate=3, period=60.0)
        for _ in range(3):
            await limiter.check("client")
        allowed, retry_after = await limiter.check("client")
        assert not allowed
        assert retry_after > 0

    async def test_clients_have_independent_budgets(self):
        limiter = RateLimiter(rate=2, period=60.0)
        await limiter.check("a")
        await limiter.check("a")
        assert (await limiter.check("a"))[0] is False
        assert (await limiter.check("b"))[0] is True

    async def test_tokens_refill_over_time(self):
        # 20/second, so a 0.1s wait restores roughly two.
        limiter = RateLimiter(rate=20, period=1.0)
        for _ in range(20):
            await limiter.check("client")
        assert (await limiter.check("client"))[0] is False
        await asyncio.sleep(0.15)
        assert (await limiter.check("client"))[0] is True

    async def test_concurrent_checks_never_exceed_the_budget(self):
        limiter = RateLimiter(rate=10, period=3600.0)
        results = await asyncio.gather(*(limiter.check("client") for _ in range(50)))
        assert sum(1 for allowed, _ in results if allowed) == 10

    async def test_retry_after_is_a_usable_hint(self):
        limiter = RateLimiter(rate=1, period=10.0)
        await limiter.check("client")
        _, retry_after = await limiter.check("client")
        assert 0 < retry_after <= 10

    async def test_idle_buckets_are_pruned(self):
        limiter = RateLimiter(rate=5, period=60.0)
        await limiter.check("client")
        assert await limiter.prune(max_idle_seconds=-1) == 1
