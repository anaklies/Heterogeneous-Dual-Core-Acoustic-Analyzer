"""Reference / two-stage flows: freeze-compare, insulation, STIPA, gates."""
from __future__ import annotations

import time

import pytest

import harness
from sixmic_backend.errors import BackendError

pytestmark = pytest.mark.e2e

SPEC = harness.load_spec()["features"]


def test_spectrum_freeze_reference_then_compare(stack):
    launch = SPEC["spectrum_freeze"]["launch"]
    reference = stack.start("spectrum_freeze", dict(launch["referenceParams"]))
    ref_done = stack.wait_completed(reference)
    assert ref_done["state"] == "completed"
    compare = stack.start("spectrum_freeze",
                          dict(launch["compareParams"],
                               referenceJobId=reference["jobId"]))
    cmp_done = stack.wait_completed(compare)
    assert cmp_done["state"] == "completed"
    ref_result = stack.client.get_feature_result(reference["jobId"])
    cmp_result = stack.client.get_feature_result(compare["jobId"])
    assert stack.assert_result(ref_result)["totalWords"] == 1025
    cmp_payload = stack.assert_result(cmp_result)
    assert cmp_payload["totalWords"] == 3075  # power / compare / difference
    stack.client.release_result(ref_result)
    stack.client.release_result(cmp_result)
    # A reference job id that does not exist must be rejected, not faked.
    with pytest.raises(BackendError) as excinfo:
        stack.start("spectrum_freeze", {"action": "compare",
                                        "referenceJobId": "feature-9999"})
    assert excinfo.value.code in {"bad_state", "job_not_found"}
    harness.record_artifact("reference_freeze_compare", {
        "featureId": "spectrum_freeze",
        "referenceJobId": reference["jobId"],
        "compareJobId": compare["jobId"],
        "referenceTotalWords": ref_result.data_ref["count"],
        "compareTotalWords": cmp_payload["totalWords"],
        "badReferenceError": excinfo.value.code,
        "fixture": stack.fixture_note(),
    })


def test_relative_limit_reference_then_compare(stack):
    launch = SPEC["relative_limit"]["launch"]
    reference = stack.start("relative_limit", dict(launch["referenceParams"]))
    assert stack.wait_completed(reference)["state"] == "completed"
    compare = stack.start("relative_limit",
                          dict(launch["compareParams"], referenceJobId=reference["jobId"]))
    assert stack.wait_completed(compare)["state"] == "completed"
    result = stack.client.get_feature_result(compare["jobId"])
    assert stack.assert_result(result)["totalWords"] == 3075
    stack.client.release_result(result)


def test_relative_insulation_reference_then_confirmed_measure(stack):
    launch = SPEC["relative_insulation"]["launch"]
    reference = stack.start("relative_insulation", dict(launch["referenceParams"]))
    assert stack.wait_completed(reference)["state"] == "completed"
    # The user-facing confirmation gate travels as confirmed=true and is fixed
    # by the spec; the PC never edits parameters in the UI.
    measure = stack.start("relative_insulation",
                          dict(launch["measureParams"],
                               referenceJobId=reference["jobId"]))
    done = stack.wait_completed(measure)
    assert done["state"] == "completed"
    result = stack.client.get_feature_result(measure["jobId"])
    payload = stack.assert_result(result)
    assert payload["totalWords"] == 36
    stack.client.release_result(result)
    # Missing user confirmation must fail validation (no silent default).
    with pytest.raises(BackendError) as excinfo:
        stack.start("relative_insulation",
                    {"action": "measure", "referenceJobId": reference["jobId"]})
    assert excinfo.value.code == "bad_args"
    harness.record_artifact("reference_insulation", {
        "featureId": "relative_insulation",
        "referenceJobId": reference["jobId"],
        "measureJobId": measure["jobId"],
        "measureTotalWords": 36,
        "missingConfirmationError": excinfo.value.code,
        "note": "relative difference only; never labelled Rw",
        "fixture": stack.fixture_note(),
    })


def test_stipa_staged_reference_two_stages_then_cancel(stack):
    reference = stack.start("io_pcm", {"samples": 720000, "channels": 1, "channel": 0})
    ref_done = stack.wait_completed(reference, timeout=20)
    assert ref_done["state"] == "completed"
    staged = stack.start("stipa_experimental",
                         {"referenceJobId": reference["jobId"],
                          "testSignalConfirmed": True})
    deadline = time.monotonic() + 20
    progress = stack.get(staged["jobId"])
    while (time.monotonic() < deadline
           and progress["state"] not in ("completed", "failed", "canceled")
           and progress["progress"]["completedStages"] < 2):
        time.sleep(0.005)
        progress = stack.get(staged["jobId"])
    assert progress["progress"]["totalStages"] == 101
    observed_stages = progress["progress"]["completedStages"]
    # The reference stays readable while the staged job is running.
    protected = stack.get(reference["jobId"])
    assert protected["state"] == "completed"
    if progress["state"] in ("completed", "failed", "canceled"):
        final_state = progress["state"]
        cancel_requested = None
    else:
        stopped = stack.stop(staged["jobId"])
        cancel_requested = stopped.get("cancelRequested")
        final_state = stack.wait(staged["jobId"], timeout=20)["state"]
    assert final_state in {"canceled", "completed"}
    if cancel_requested is not None:
        assert final_state == "canceled"
    assert observed_stages >= 2
    harness.record_artifact("reference_stipa_staged", {
        "featureId": "stipa_experimental",
        "referenceJobId": reference["jobId"],
        "stagedJobId": staged["jobId"],
        "totalStages": 101,
        "observedCompletedStages": observed_stages,
        "cancelRequested": cancel_requested,
        "finalState": final_state,
        "referenceStateDuringRun": protected["state"],
        "note": "experimental, not certified STIPA; 101 stages; cancel is a safe "
                "boundary, not a hard PL interrupt",
        "fixture": stack.fixture_note(),
    })


def test_room_stimulus_confirmation_gate(stack):
    with pytest.raises(BackendError) as excinfo:
        stack.start("room_decay", {})
    assert excinfo.value.code == "bad_args"
    accepted = stack.start("room_decay", {"stimulus": "impulse"})
    assert stack.wait_completed(accepted, timeout=20)["state"] == "completed"


def test_noise_rating_reference_confirmation_gate(stack):
    bad = {"family": "NR", "channel": 0}
    with pytest.raises(BackendError) as excinfo:
        stack.start("noise_rating", bad)
    assert excinfo.value.code == "bad_args"
    good = {"family": "NR", "channel": 0, "referenceConfirmed": True,
            "referenceOffsetDb": 0.0,
            "calibrationSource": "nominal user-declared digital reference"}
    accepted = stack.start("noise_rating", good)
    assert stack.wait_completed(accepted, timeout=20)["state"] == "completed"
