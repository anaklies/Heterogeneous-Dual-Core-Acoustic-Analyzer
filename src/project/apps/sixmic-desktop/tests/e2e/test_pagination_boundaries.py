"""1024-word result page boundary + protocol error handling (identity checks)."""
from __future__ import annotations

import struct

import pytest

import harness
from sixmic_backend.errors import BackendError

pytestmark = pytest.mark.e2e


@pytest.fixture()
def completed_fft(stack):
    accepted = stack.start("fft", {"channel": 0})
    completed = stack.wait_completed(accepted)
    assert completed["state"] == "completed"
    return accepted, completed


def _words(page: dict) -> list[int]:
    return [int(word) for word in page["words"]]


def test_result_pages_are_capped_at_1024_words(stack, completed_fft):
    accepted, completed = completed_fft
    job = accepted["jobId"]
    page0 = stack.result_page(job, offset=0, max_words=1024)
    page1 = stack.result_page(job, offset=1024, max_words=1024)
    assert page0["totalWords"] == 1025
    assert page0["offsetWords"] == 0
    assert len(page0["words"]) == 1024 and page0["more"] is True
    assert page1["offsetWords"] == 1024
    assert len(page1["words"]) == 1 and page1["more"] is False
    assert page0["schema"] == page1["schema"]
    stack.assert_identity(page0, "fft")
    stack.assert_identity(page1, "fft")
    assert {page0["jobId"], page1["jobId"]} == {job}
    assert page0["configuration"] == page1["configuration"]


def test_client_pagination_reassembles_exact_words(stack, completed_fft):
    accepted, _ = completed_fft
    job = accepted["jobId"]
    page0 = stack.result_page(job, offset=0, max_words=1024)
    page1 = stack.result_page(job, offset=1024, max_words=1024)
    expected = _words(page0) + _words(page1)
    result = stack.client.get_feature_result(job)
    payload = stack.assert_result(result)
    assert payload["totalWords"] == 1025
    raw = stack.session.data_store.read_slice(result.data_ref["handleId"], 0,
                                              result.data_ref["count"])
    actual = list(struct.unpack("<" + "I" * 1025, raw))
    assert actual == expected
    stack.client.release_result(result)


@pytest.mark.parametrize("offset,max_words", [
    (0, 2048),   # page larger than the 1024-word protocol maximum
    (0, 0),      # empty page is not a valid transfer
    (2048, 1024) # offset beyond totalWords
])
def test_invalid_result_pages_are_rejected(stack, completed_fft, offset, max_words):
    accepted, _ = completed_fft
    with pytest.raises(BackendError) as excinfo:
        stack.result_page(accepted["jobId"], offset=offset, max_words=max_words)
    assert excinfo.value.code == "bad_state"


def test_result_before_completion_is_not_readable(stack):
    accepted = stack.start("room_clarity", {"stimulus": "clap"})
    try:
        with pytest.raises(BackendError) as excinfo:
            stack.result_page(accepted["jobId"])
        assert excinfo.value.code == "bad_state"
    finally:
        stack.stop(accepted["jobId"])
        stack.wait(accepted["jobId"])


def test_unknown_job_and_feature_identities_are_rejected(stack):
    with pytest.raises(BackendError) as excinfo:
        stack.get("feature-9999")
    assert excinfo.value.code == "job_not_found"
    with pytest.raises(BackendError) as excinfo:
        stack.start("not_a_feature", {})
    assert excinfo.value.code in {"unsupported_feature", "bad_args"}
    accepted = stack.start("fft", {"channel": 0})
    completed = stack.wait_completed(accepted)
    assert completed["state"] == "completed"
    with pytest.raises(BackendError) as excinfo:
        stack.start("fft", {"channel": 99})
    assert excinfo.value.code == "bad_args"
    with pytest.raises(BackendError) as excinfo:
        stack.raw_request("feature.stop", {"jobId": accepted["jobId"],
                                           "controlToken": "not-a-token"})
    assert excinfo.value.code == "bad_token"
    harness.record_artifact("pagination_boundaries", {
        "featureId": "fft",
        "totalWords": 1025,
        "pageBoundary": {"page0": 1024, "page1": 1},
        "invalidPageErrors": {"maxWords2048": "bad_state", "maxWords0": "bad_state",
                              "offsetBeyond": "bad_state"},
        "clientReassemblyExact": True,
        "fixture": stack.fixture_note(),
    })
