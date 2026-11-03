"""Scheduling contract: exclusive busy, cancel-to-canceled, eight bounded slots."""
from __future__ import annotations

import pytest

import harness
from sixmic_backend.errors import BackendError

pytestmark = pytest.mark.e2e


def test_exclusive_job_reports_busy_then_accepts_after_cancel(stack):
    monitor = stack.start("event_trigger", {"channel": 0})
    assert stack.get(monitor["jobId"])["state"] == "running"
    with pytest.raises(BackendError) as excinfo:
        stack.start("room_decay", {"stimulus": "clap"})
    assert excinfo.value.code == "busy"
    stopped = stack.stop(monitor["jobId"])
    assert stopped["cancelRequested"] is True
    assert stack.wait(monitor["jobId"])["state"] == "canceled"
    retry = stack.start("room_decay", {"stimulus": "clap"})
    assert stack.wait_completed(retry, timeout=20)["state"] == "completed"
    harness.record_artifact("scheduling_busy", {
        "busyError": {"code": "busy", "detail": excinfo.value.detail},
        "cancel": {"cancelRequested": True, "finalState": "canceled"},
        "afterCancelFeature": "room_decay",
        "afterCancelState": "completed",
        "fixture": stack.fixture_note(),
    })


def test_stop_immediately_after_start_reaches_canceled(stack):
    accepted = stack.start("room_clarity", {"stimulus": "clap"})
    stopped = stack.stop(accepted["jobId"])
    assert stopped["jobId"] == accepted["jobId"]
    final = stack.wait(accepted["jobId"], timeout=20)
    assert final["state"] == "canceled"


def test_eight_bounded_job_slots_recycle_oldest_terminal_job(stack):
    # Gateway fx_jobs is a fixed 8-slot table (feature_runtime.c FX_JOBS=8);
    # completed, unreferenced jobs are recycled oldest-first.
    jobs = []
    for _ in range(9):
        accepted = stack.start("fft", {"channel": 0})
        final = stack.wait_completed(accepted)
        jobs.append((accepted["jobId"], final["state"]))
    assert [state for _, state in jobs] == ["completed"] * 9
    assert [job for job, _ in jobs] == [f"feature-{index}" for index in range(1, 10)]
    with pytest.raises(BackendError) as excinfo:
        stack.get("feature-1")
    assert excinfo.value.code == "job_not_found"
    assert stack.get("feature-9")["state"] == "completed"
    harness.record_artifact("scheduling_slots", {
        "slotCount": 8,
        "slotEvidence": "ps/gateway/src/feature_runtime.c FX_JOBS=8; "
                        "completed unreferenced jobs recycled oldest-first",
        "startedJobs": [job for job, _ in jobs],
        "evictedJob": "feature-1",
        "retainedJob": "feature-9",
        "fixture": stack.fixture_note(),
    })
