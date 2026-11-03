"""PC-side pacing: gateway documents <=64 req/s; large result paging must obey it."""
from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP_ROOT))

from pc_client.client import FeatureClient, _TokenBucket  # noqa: E402


class FakeControl:
    session_id = "s-1"

    def __init__(self):
        self.requests = []

    def request(self, op, args):
        self.requests.append((op, dict(args)))
        return {"ok": True, "op": op}


class FakeSession:
    def __init__(self):
        self.control = FakeControl()


def test_token_bucket_spends_documented_budget():
    now = {"t": 1000.0}
    slept: list[float] = []

    def clock():
        return now["t"]

    def sleep(seconds):
        slept.append(seconds)
        now["t"] += seconds

    bucket = _TokenBucket(rate=64.0, capacity=64, clock=clock, sleep=sleep)
    for _ in range(64):
        bucket.acquire()
    assert slept == []
    for _ in range(136):
        bucket.acquire()
    # 136 more requests at 64/s => ~2.125 s of local pacing.
    assert 2.0 <= bucket.waited_seconds <= 2.3
    assert bucket.requests == 200


def test_disabled_pacing_never_sleeps():
    bucket = _TokenBucket(rate=0, capacity=1)
    for _ in range(1000):
        bucket.acquire()
    assert bucket.waited_seconds == 0.0


def test_feature_client_paces_each_request():
    session = FakeSession()
    client = FeatureClient(session, request_rate=64.0, request_burst=8)
    now = {"t": 500.0}
    slept: list[float] = []

    def clock():
        return now["t"]

    def sleep(seconds):
        slept.append(seconds)
        now["t"] += seconds

    client._limiter = _TokenBucket(rate=64.0, capacity=8, clock=clock, sleep=sleep)
    for index in range(72):
        client._request("feature.get", {"jobId": f"job-{index}"})
    assert len(session.control.requests) == 72
    # 72 requests - 8 burst tokens => 64 paced slots at 64/s = 1.0 s.
    assert 0.9 <= sum(slept) <= 1.1
    assert all(op == "feature.get" for op, _ in session.control.requests)


def test_feature_client_rate_limit_is_configurable_for_tests():
    client = FeatureClient(FakeSession(), request_rate=0)
    for _ in range(100):
        client._request("feature.list", {"cursor": 0, "limit": 8})
    assert client._limiter.waited_seconds == 0.0


def test_start_retries_explicit_busy_only(monkeypatch):
    from sixmic_backend.errors import BackendError
    client=FeatureClient(FakeSession(),request_rate=0);client._feature_modes={'fft':'p0'};calls=[];sleeps=[]
    def request(op,args):
        calls.append(op)
        if len(calls)<3:raise BackendError('busy',{})
        return {'jobId':'accepted-once'}
    client._request=request;monkeypatch.setattr('pc_client.client.time.sleep',sleeps.append)
    assert client.start_feature('fft')['jobId']=='accepted-once'
    assert len(calls)==3 and sleeps==[.05,.1]


def test_start_does_not_replay_unknown_timeout(monkeypatch):
    import pytest
    from sixmic_backend.errors import BackendError
    client=FeatureClient(FakeSession(),request_rate=0);client._feature_modes={'fft':'p0'};calls=[]
    def request(op,args):calls.append(op);raise BackendError('timeout',{})
    client._request=request
    with pytest.raises(BackendError):client.start_feature('fft')
    assert calls==['feature.start']


def test_persistent_busy_is_bounded(monkeypatch):
    import pytest
    from sixmic_backend.errors import BackendError
    client=FeatureClient(FakeSession(),request_rate=0);client._feature_modes={'fft':'p0'};calls=[]
    def request(op,args):calls.append(op);raise BackendError('busy',{})
    client._request=request;monkeypatch.setattr('pc_client.client.time.sleep',lambda _:None)
    with pytest.raises(BackendError):client.start_feature('fft')
    assert len(calls)==6
