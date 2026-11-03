"""Unit-level proof of the stock FeatureClient request pacing.

The client-level token bucket is what keeps the product inside the gateway's
documented 64 req/s budget.  These tests use an injected fake clock/sleep, so
they prove the arithmetic without waiting in real time; the end-to-end timing
proof lives in test_large_results.py.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from pc_client import FeatureClient
from pc_client.client import _TokenBucket

pytestmark = pytest.mark.e2e


def _fake_time():
    now = [100.0]
    sleeps: list[float] = []

    def clock() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    return now, sleeps, clock, sleep


def test_token_bucket_allows_burst_then_paces_at_rate():
    _, sleeps, clock, sleep = _fake_time()
    bucket = _TokenBucket(rate=64.0, capacity=64, clock=clock, sleep=sleep)
    for _ in range(64):
        bucket.acquire()
    assert sleeps == [], "the burst allowance must be spent first"
    assert bucket.requests == 64
    bucket.acquire()
    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(1.0 / 64.0, rel=1e-9)


def test_token_bucket_sustained_rate_matches_documented_budget():
    _, sleeps, clock, sleep = _fake_time()
    bucket = _TokenBucket(rate=64.0, capacity=64, clock=clock, sleep=sleep)
    total = 192  # 64 burst + 128 paced slots == 2.0 s at 64/s
    for _ in range(total):
        bucket.acquire()
    assert bucket.requests == total
    assert sum(sleeps) == pytest.approx((total - 64) / 64.0, rel=1e-9)


def test_token_bucket_can_be_disabled_for_tests_only():
    _, sleeps, clock, sleep = _fake_time()
    bucket = _TokenBucket(rate=0.0, capacity=1, clock=clock, sleep=sleep)
    for _ in range(1000):
        bucket.acquire()
    assert sleeps == []
    assert bucket.requests == 1000


@pytest.mark.parametrize("rate,burst", [(64.0, 64), (32.0, 8), (0.0, 1)])
def test_feature_client_exposes_configurable_pacing(rate, burst):
    stub = SimpleNamespace(control=SimpleNamespace(session_id="sess-unit"))
    client = FeatureClient(stub, request_rate=rate, request_burst=burst)
    assert client._limiter.rate == pytest.approx(rate)
    assert client._limiter.capacity == pytest.approx(float(burst))
