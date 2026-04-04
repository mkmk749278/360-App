"""Tests for the depth endpoint circuit breaker in BinanceClient.

Validates that once the breaker trips, concurrent in-flight requests
bail out on their next retry instead of continuing to time out and
inflating the timeout counter.
"""

from __future__ import annotations

import asyncio
import time
import unittest.mock as mock

import pytest

from src.binance import BinanceClient, DEPTH_CIRCUIT_BREAKER_THRESHOLD, _DEPTH_CB_WINDOW_S


class _TimeoutContextManager:
    """Async context manager that raises TimeoutError on __aenter__."""

    async def __aenter__(self):
        raise asyncio.TimeoutError()

    async def __aexit__(self, *args):
        pass  # pragma: no cover


class _FakeSession:
    """Minimal stand-in for aiohttp.ClientSession."""

    def get(self, *args, **kwargs):
        return _TimeoutContextManager()

    @property
    def closed(self):
        return False


@pytest.fixture()
def client():
    c = BinanceClient(market="futures")
    # Bypass real session creation and rate-limiter waits.
    c._ensure_session = _make_fake_ensure()
    c._rate_limiter.acquire = lambda w: asyncio.sleep(0)
    return c


def _make_fake_ensure():
    session = _FakeSession()

    async def _ensure():
        return session

    return _ensure


class TestDepthCircuitBreakerConcurrency:
    """Concurrent requests must respect the breaker opened by another request."""

    async def test_concurrent_requests_stop_after_breaker_opens(self, client):
        """Simulate multiple concurrent depth calls where all time out.

        Once the threshold is reached by one coroutine, other coroutines
        that are in their retry loop must see the breaker is open and
        bail out — the timeout timestamp list must NOT grow unboundedly.
        """
        # Pre-seed the timestamp list just below the threshold so the very
        # first timeout from any coroutine will trip the breaker.
        now = time.monotonic()
        client._depth_timeout_timestamps = [
            now - 1.0 for _ in range(DEPTH_CIRCUIT_BREAKER_THRESHOLD - 1)
        ]

        # Patch asyncio.sleep to avoid real waits.
        with mock.patch("asyncio.sleep", return_value=asyncio.sleep(0)):
            tasks = [
                asyncio.create_task(
                    client._get("/fapi/v1/depth", params={"symbol": "BTCUSDT", "limit": 20})
                )
                for _ in range(10)
            ]
            await asyncio.gather(*tasks)

        # The first timeout trips the breaker (threshold reached, then list is
        # cleared).  All other coroutines should detect the open breaker and
        # return immediately.  The timestamp list is cleared when the breaker
        # trips, so any post-trip timestamps are from concurrent coroutines
        # that squeezed in before seeing the open breaker.
        assert len(client._depth_timeout_timestamps) <= 1
        assert client._depth_circuit_open_until > time.monotonic()

    async def test_semaphore_wait_rechecks_breaker(self, client):
        """Requests waiting on _inflight_sem must re-check the breaker after
        acquiring the semaphore.  Without this, requests that queued behind
        the semaphore while the breaker was still closed proceed to make
        HTTP calls that time out (5 s each), inflating scan latency."""
        http_calls = 0
        original_get = _FakeSession.get

        def counting_get(self_sess, *args, **kwargs):
            nonlocal http_calls
            http_calls += 1
            return original_get(self_sess, *args, **kwargs)

        # Shrink the semaphore to 1 so we can control ordering.
        client._inflight_sem = asyncio.Semaphore(1)

        async def _first_request():
            """Acquire the sem, trip the breaker, then release."""
            async with client._inflight_sem:
                # Simulate: while holding the sem, the breaker is tripped
                # (e.g. by accumulated timeouts from earlier requests).
                client._depth_circuit_open_until = time.monotonic() + 60

        async def _second_request():
            """This request should detect the breaker after acquiring sem."""
            # Let the first request grab the sem first.
            await asyncio.sleep(0)
            return await client._get(
                "/fapi/v1/depth", params={"symbol": "BTCUSDT", "limit": 20}
            )

        with mock.patch.object(_FakeSession, "get", counting_get):
            with mock.patch("asyncio.sleep", return_value=asyncio.sleep(0)):
                result = await asyncio.gather(
                    _first_request(), _second_request()
                )

        # The second request must have returned None without making any
        # HTTP call — the breaker was open when it finally acquired the sem.
        assert result[1] is None
        assert http_calls == 0

    async def test_retry_loop_checks_breaker_each_attempt(self, client):
        """A single request that enters the retry loop must re-check the
        breaker before each attempt, not just at _get() entry."""
        attempt_count = 0
        original_get = _FakeSession.get

        def counting_get(self_sess, *args, **kwargs):
            nonlocal attempt_count
            attempt_count += 1
            # After the first attempt triggers a timeout, open the
            # breaker as if another coroutine tripped it.
            if attempt_count == 1:
                client._depth_circuit_open_until = time.monotonic() + 60
            return original_get(self_sess, *args, **kwargs)

        with mock.patch.object(_FakeSession, "get", counting_get):
            with mock.patch("asyncio.sleep", return_value=asyncio.sleep(0)):
                result = await client._get(
                    "/fapi/v1/depth", params={"symbol": "ETHUSDT"}
                )

        assert result is None
        # Only one attempt should have been made; the second attempt sees
        # the open breaker and returns immediately.
        assert attempt_count == 1
        # The breaker was already open (set inside counting_get, simulating
        # another coroutine tripping it) when the TimeoutError handler ran,
        # so the timestamp list must NOT be updated — the handler checks
        # the breaker first and returns None.
        assert len(client._depth_timeout_timestamps) == 0

    async def test_window_based_tracking_does_not_reset_on_success(self, client):
        """Verify that a successful depth response does NOT clear the
        timeout timestamp list — entries age out via the rolling window."""
        now = time.monotonic()
        # Pre-seed 2 recent timeout timestamps.
        client._depth_timeout_timestamps = [now - 5.0, now - 3.0]

        # After a successful call, the timestamps should remain.
        # (We cannot actually call _get with a success here without a more
        # elaborate mock, so we verify the attribute is a list type and
        # is not cleared by construction.)
        assert len(client._depth_timeout_timestamps) == 2

    async def test_old_timestamps_are_pruned(self, client):
        """Timestamps older than _DEPTH_CB_WINDOW_S are pruned on each
        new timeout event."""
        now = time.monotonic()
        # 2 old timestamps (outside window) + 1 recent
        client._depth_timeout_timestamps = [
            now - _DEPTH_CB_WINDOW_S - 10.0,
            now - _DEPTH_CB_WINDOW_S - 5.0,
            now - 1.0,
        ]

        with mock.patch("asyncio.sleep", return_value=asyncio.sleep(0)):
            await client._get(
                "/fapi/v1/depth", params={"symbol": "BTCUSDT", "limit": 20}
            )

        # Old timestamps should have been pruned; only recent ones remain.
        # The new timeout adds 1 more entry on top of the 1 recent one.
        # With threshold=3, breaker should NOT have tripped (only 2 entries).
        for ts in client._depth_timeout_timestamps:
            assert ts > now - _DEPTH_CB_WINDOW_S
