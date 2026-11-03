"""Reconnect, control re-claim and result identity across a new network session."""
from __future__ import annotations

import pytest

import harness

pytestmark = pytest.mark.e2e


def test_reconnect_reclaims_control_and_keeps_job_identity(stack):
    session = stack.session
    old_session_id = session.session_id
    old_epoch = session.connection_epoch
    old_control = session.control
    assert isinstance(old_session_id, str) and old_session_id
    assert isinstance(old_epoch, int)

    # Stock client created on the old login: after reconnect it must detect the
    # session change/no-token state and claim a new control token.
    from pc_client import FeatureClient
    client = FeatureClient(session)

    before = stack.start("fft", {"channel": 0})
    before_done = stack.wait_completed(before)
    assert before_done["state"] == "completed"
    old_token = session._control_token
    assert old_token, "control token must be held after feature.start"

    session.disconnect()
    assert session.state == "disconnected"
    hello = session.connect()
    assert session.state == "connected"
    new_session_id = session.session_id
    new_epoch = session.connection_epoch
    assert session.control is not old_control, "reconnect must create a new transport"
    assert isinstance(hello, dict) and hello.get("sessionId") == new_session_id
    assert isinstance(new_session_id, str) and new_session_id
    assert isinstance(new_epoch, int) and new_epoch >= old_epoch

    # Reusing the pre-reconnect client must re-claim control on the new login.
    after = client.start_feature("fft", {"channel": 0})
    after_done = stack.wait_completed(after)
    assert after_done["state"] == "completed"
    new_token = session._control_token
    assert new_token, "control must be re-claimed after reconnect"
    assert new_token != old_token, "a new login must not reuse the old lease token"

    catalog = client.list_features()
    assert len(catalog["features"]) == 51

    # Job identity belongs to the device job, not to the TCP login: the old job
    # is still queryable after the reconnect and keeps its test-fixture marker.
    old_job = client.get_feature(before["jobId"])
    stack.assert_identity(old_job, "fft")
    assert old_job["state"] == "completed"
    assert old_job["sourceKind"] == "test-fixture"

    configuration = after_done["configuration"]
    assert isinstance(configuration["session"], int)
    assert not isinstance(configuration["session"], bool)
    for counter in ("generation", "sourceFrame"):
        assert isinstance(configuration[counter], str)
        assert configuration[counter].isdigit()
    assert new_session_id != str(configuration["session"])
    harness.record_artifact("reconnect_identity", {
        "oldSessionId": old_session_id,
        "newSessionId": new_session_id,
        "sessionIdReusedByFixture": new_session_id == old_session_id,
        "fixtureNote": "session id is sess-<epoch>-<connection slot>; a clean "
                       "reconnect can reuse the same slot id. The identity "
                       "contract is the control token + job identity, verified here.",
        "oldEpoch": old_epoch,
        "newEpoch": new_epoch,
        "oldTokenReplaced": new_token != old_token,
        "oldJob": {"jobId": before["jobId"], "state": old_job["state"],
                   "sourceKind": old_job["sourceKind"]},
        "newJob": {"jobId": after["jobId"], "state": after_done["state"]},
        "configurationTypes": {key: type(configuration[key]).__name__
                               for key in ("session", "config", "generation", "sourceFrame")},
        "networkSessionIsNotPlSession": True,
        "catalogAfterReconnect": len(catalog["features"]),
        "fixture": stack.fixture_note(),
    })


def test_result_identity_is_stable_across_pages_and_operations(stack):
    accepted = stack.start("fft", {"channel": 0})
    completed = stack.wait_completed(accepted)
    page0 = stack.result_page(accepted["jobId"], 0, 1024)
    page1 = stack.result_page(accepted["jobId"], 1024, 1024)
    identity_keys = ("jobId", "featureId", "state", "sourceKind", "configuration",
                     "schema", "totalWords")
    assert {key: page0[key] for key in identity_keys} == \
           {key: page1[key] for key in identity_keys}
    assert page0["configuration"] == completed["configuration"]
