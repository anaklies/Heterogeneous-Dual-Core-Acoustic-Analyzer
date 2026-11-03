"""Representative feature lifecycle per device mode (p0/p1/p2/events).

Every flow here uses the fixed hidden launch parameters from
ui/config/feature_view_spec.json: the user never edits parameters.  The app
stack is real; the gateway is the host test fixture (SIMULATED/test-fixture).
"""
from __future__ import annotations

import pytest

import harness

pytestmark = pytest.mark.e2e

SPEC = harness.load_spec()["features"]


def test_p0_feature_completes_and_returns_result(stack):
    feature = "fft"
    params = SPEC[feature]["launch"]["params"]
    accepted = stack.start(feature, params)
    assert accepted.get("responseStatus") == "accepted"
    assert accepted["state"] == "running"
    completed = stack.wait_completed(accepted)
    assert completed["state"] == "completed"
    assert completed["progress"]["completedStages"] == 0
    result = stack.client.get_feature_result(accepted["jobId"])
    payload = stack.assert_result(result)
    assert payload["state"] == "completed"
    assert payload["totalWords"] == 1025
    assert payload["schema"]["kind"] == "tensor"
    raw = stack.session.data_store.read_slice(result.data_ref["handleId"], 0, 8)
    assert len(raw) == 8 * 4
    released = stack.client.release_result(result)
    assert released is True, f"data-store release must confirm, got {released!r}"
    harness.record_artifact("lifecycle_modes", {
        "p0": {"featureId": feature, "params": params, "state": completed["state"],
               "totalWords": payload["totalWords"], "schemaKind": payload["schema"]["kind"],
               "jobId": accepted["jobId"]},
        "fixture": stack.fixture_note(),
    })


def test_p1_feature_completes_and_returns_result(stack):
    feature = "psd"
    params = SPEC[feature]["launch"]["params"]
    accepted = stack.start(feature, params)
    completed = stack.wait_completed(accepted)
    assert completed["state"] == "completed"
    result = stack.client.get_feature_result(accepted["jobId"])
    payload = stack.assert_result(result)
    assert payload["totalWords"] == 1026
    stack.client.release_result(result)


def test_room_decay_completes_after_confirmation(stack):
    accepted = stack.start("room_decay", {"stimulus": "clap"})
    completed = stack.wait_completed(accepted, timeout=20)
    assert completed["state"] == "completed"
    result = stack.client.get_feature_result(accepted["jobId"])
    payload = stack.assert_result(result)
    assert payload["totalWords"] == 48032
    assert payload["schema"]["kind"] == "tensor"
    assert completed["progress"]["capturedSamples"] > 0
    stack.client.release_result(result)


def test_zoom_fft_completes_after_registry_fix(stack):
    entry = SPEC["zoom_fft"]
    launch = entry["launch"]
    assert not (entry["devicePath"] or {}).get("knownGap")
    accepted = stack.start("zoom_fft", dict(launch.get("params") or {}))
    completed = stack.wait_completed(accepted, timeout=30)
    assert completed["state"] == "completed"
    assert completed["progress"]["capturedSamples"] == 4159
    result = stack.client.get_feature_result(accepted["jobId"])
    payload = stack.assert_result(result)
    assert payload["totalWords"] == 4096
    assert payload["schema"]["kind"] == "tensor"
    assert payload["sourceKind"] == "test-fixture"
    harness.record_artifact("zoom_fft_registry_fix", {
        "featureId": "zoom_fft",
        "state": completed["state"],
        "capturedSamples": completed["progress"]["capturedSamples"],
        "totalWords": payload["totalWords"],
        "schemaKind": payload["schema"]["kind"],
        "sourceKind": payload["sourceKind"],
        "registryFix": {"inputWords": 4159, "inputWordOffset": 1069056},
        "hardwareState": "NOT_TESTED",
        "numericDSPVerified": False,
        "hardwareAccepted": False,
        "interpretation": "Device registry fix verified on host fixture; "
                          "PC wiring complete; physical board/acoustic acceptance still pending.",
        "fixture": stack.fixture_note(),
    })
    stack.client.release_result(result)


def test_events_mode_monitor_runs_until_stopped_and_cancels(stack):
    feature = "event_trigger"
    accepted = stack.start(feature, SPEC[feature]["launch"]["params"])
    running = stack.get(accepted["jobId"])
    assert running["state"] == "running"
    assert running["progress"]["totalStages"] == 0
    # event.list is a frozen control op (not feature.result); it must work while
    # a monitoring job is running, and must not be used as a result page.
    events = stack.raw_session_request("event.list", {})
    assert isinstance(events.get("events"), list)
    stopped = stack.stop(accepted["jobId"])
    assert stopped["jobId"] == accepted["jobId"]
    final = stack.wait(accepted["jobId"], feature_id=feature)
    assert final["state"] == "canceled"
    # A canceled monitoring job has no downloadable feature result.
    from sixmic_backend.errors import BackendError
    with pytest.raises(BackendError) as excinfo:
        stack.result_page(accepted["jobId"])
    assert excinfo.value.code in {"bad_state", "job_not_found"}
    harness.record_artifact("lifecycle_events", {
        "featureId": feature,
        "runningState": running["state"],
        "finalState": final["state"],
        "eventListEntries": len(events.get("events") or []),
        "fixture": stack.fixture_note(),
    })


def test_staged_mode_requires_io_pcm_reference(stack):
    from sixmic_backend.errors import BackendError

    # Without a reference job the staged start must fail validation, not run.
    with pytest.raises(BackendError) as excinfo:
        stack.start("stipa_experimental", {"testSignalConfirmed": True})
    assert excinfo.value.code in {"bad_args", "bad_state"}
