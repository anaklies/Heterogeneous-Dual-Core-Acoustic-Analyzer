"""Large results through the app stack: 48032-word room decay, 720000-word PCM.

The stock FeatureClient now paces its own requests (Lead change 2026-10-26).
The 720000-word result needs 704 pages of 1024 words; at the documented
64 req/s budget the transfer takes about ten seconds, well inside the job
deadline (kind-6 io_pcm jobs get 120 s).  Pacing is proven end to end here and
in unit form in test_client_pacing.py.
"""
from __future__ import annotations

import struct
import time

import pytest

import harness
from sixmic_backend.errors import BackendError

pytestmark = pytest.mark.e2e


def _limiter_requests(stack) -> int:
    limiter = getattr(stack.client, "_limiter", None)
    return int(getattr(limiter, "requests", 0))


def test_room_decay_48032_word_result_transfers_through_stock_client(stack):
    accepted = stack.start("room_decay", {"stimulus": "clap"})
    completed = stack.wait_completed(accepted, timeout=20)
    assert completed["state"] == "completed"
    total_words = 48032
    started = time.monotonic()
    result = stack.client.get_feature_result(accepted["jobId"])
    elapsed = time.monotonic() - started
    payload = stack.assert_result(result)
    assert payload["totalWords"] == total_words
    assert result.data_ref["count"] == total_words
    assert elapsed < 10.0, f"47 pages must fit the burst budget, took {elapsed:.2f}s"
    page0 = stack.result_page(accepted["jobId"], offset=0, max_words=1024)
    last_offset = total_words - (total_words % 1024 or 1024)
    last_page = stack.result_page(accepted["jobId"], offset=last_offset, max_words=1024)
    raw = stack.session.data_store.read_slice(result.data_ref["handleId"], 0, total_words)
    words = list(struct.unpack("<" + "I" * total_words, raw))
    assert words[:1024] == [int(word) for word in page0["words"]]
    assert words[last_offset:] == [int(word) for word in last_page["words"]]
    stack.client.release_result(result)
    harness.record_artifact("large_result_room_decay", {
        "featureId": "room_decay",
        "totalWords": total_words,
        "pages": 47,
        "elapsedSeconds": round(elapsed, 3),
        "client": stack.fixture_note()["clientPacing"],
        "fixture": stack.fixture_note(),
    })


def test_io_pcm_720000_long_capture_full_result_transfer_with_pacing(stack):
    accepted = stack.start("io_pcm",
                           {"samples": 720000, "channels": 1, "channel": 0})
    completed = stack.wait_completed(accepted, timeout=20)
    assert completed["state"] == "completed"
    progress = completed["progress"]
    assert progress["capturedSamples"] == 720000
    assert progress["requiredSamples"] == 720000
    first_page = stack.result_page(accepted["jobId"], offset=0, max_words=1024)
    total_words = first_page["totalWords"]
    assert total_words == 720000
    pages = (total_words + 1023) // 1024
    assert pages == 704

    before = _limiter_requests(stack)
    started = time.monotonic()
    result = stack.client.get_feature_result(accepted["jobId"])
    elapsed = time.monotonic() - started
    after = _limiter_requests(stack)
    payload = stack.assert_result(result)
    assert payload["totalWords"] == 720000
    assert result.data_ref["count"] == 720000
    page_requests = after - before
    assert page_requests == pages, (
        f"expected exactly {pages} paged result requests, got {page_requests}")
    # Documented budget: burst 64, then 64 req/s.  The transfer must therefore
    # take at least (704-64)/64 = 10.0 s and must not exceed the job deadline.
    minimum_elapsed = (pages - 64) / 64.0
    assert elapsed >= minimum_elapsed - 0.5, (
        f"pacing violated: {pages} pages in {elapsed:.2f}s")
    assert elapsed <= 30.0, f"large-result transfer too slow: {elapsed:.2f}s"
    assert payload["totalWords"] == 720000
    limiter = getattr(stack.client, "_limiter", None)
    assert getattr(limiter, "waited_seconds", 0.0) > 5.0

    raw = stack.session.data_store.read_slice(result.data_ref["handleId"], 0, 720000)
    assert len(raw) == 720000 * 4
    words = struct.unpack("<" + "I" * 720000, raw)
    assert list(words[:1024]) == [int(word) for word in first_page["words"]]
    last_offset = 720000 - 128  # 703 full pages + 128-word final page
    last_page = stack.result_page(accepted["jobId"], offset=last_offset, max_words=1024)
    assert len(last_page["words"]) == 128 and last_page["more"] is False
    assert list(words[last_offset:]) == [int(word) for word in last_page["words"]]
    stack.client.release_result(result)
    harness.record_artifact("large_result_io_pcm_720000", {
        "featureId": "io_pcm",
        "params": {"samples": 720000, "channels": 1, "channel": 0},
        "state": completed["state"],
        "capturedSamples": progress["capturedSamples"],
        "totalWords": total_words,
        "pages": pages,
        "pageRequests": page_requests,
        "elapsedSeconds": round(elapsed, 3),
        "minimumElapsedSeconds": minimum_elapsed,
        "jobDeadlineSeconds": 120,
        "deadlineHeadroomSeconds": round(120 - elapsed, 2),
        "pacing": {"rate": getattr(limiter, "rate", None),
                   "capacity": getattr(limiter, "capacity", None),
                   "waitedSeconds": round(getattr(limiter, "waited_seconds", 0.0), 3)},
        "fixture": stack.fixture_note(),
    })


def test_unpaced_client_is_rejected_by_gateway_rate_limit(stack):
    """Negative proof for why the stock client paces.

    With request_rate=0 the 704-page 720000-word transfer exhausts the gateway
    token bucket (64/s burst 128); throttled responses carry requestId 0 and are
    dropped by the frozen transport, so the transfer fails with a timeout.
    This test asserts that documented failure mode; it is not a product
    regression.
    """
    from pc_client import FeatureClient

    accepted = stack.start("io_pcm",
                           {"samples": 720000, "channels": 1, "channel": 0})
    completed = stack.wait_completed(accepted, timeout=20)
    assert completed["state"] == "completed"
    unpaced = FeatureClient(stack.session, request_rate=0.0)
    with pytest.raises(BackendError) as excinfo:
        unpaced.get_feature_result(accepted["jobId"])
    assert excinfo.value.code in {"timeout", "connection_lost"}
    harness.record_artifact("large_result_unpaced_negative_proof", {
        "featureId": "io_pcm",
        "requestRate": 0,
        "outcome": "gateway rate-limit -> dropped response -> transport timeout",
        "error": {"code": excinfo.value.code, "detail": excinfo.value.detail},
        "conclusion": "stock FeatureClient pacing is required, not optional",
        "fixture": stack.fixture_note(),
    })
