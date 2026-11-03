"""Live capability/identity checks against the host fixture gateway (TCP).

SIMULATED / test-fixture: this proves the PC's DTO layer accepts the candidate
gateway's boolean capability encoding and reports featureApi correctly.  It does
not prove any PL path or numeric result.
"""
from __future__ import annotations

import pytest

import harness

pytestmark = pytest.mark.e2e

VALID_CAP_STATES = {"available", "experimental", "not_ready", "disabled", "unsupported"}


def test_fixture_ready_line_is_marked_simulated(stack):
    ready = stack.ready
    assert ready["sourceKind"] == "test-fixture"
    assert ready["numericDSPVerified"] is False
    assert isinstance(ready["controlPort"], int) and ready["controlPort"] > 0
    assert isinstance(ready["binaryPort"], int) and ready["binaryPort"] > 0
    assert ready["controlPort"] != ready["binaryPort"]
    evidence = {"ready": dict(ready), "fixture": stack.fixture_note()}
    harness.record_artifact("capability_gateway_ready", evidence)


def test_device_session_connects_and_normalizes_bool_capabilities(stack):
    session = stack.session
    assert session.state == "connected"
    assert isinstance(session.session_id, str) and session.session_id
    assert isinstance(session.connection_epoch, int)
    assert session.device_info is not None and session.device_info.device_id

    caps = session.capabilities.to_dict()
    for key in ("livePcm", "liveResults", "eventCapture", "eventDownload",
                "rawRecording", "profileUpload", "profileActivate", "taskControl",
                "sensorSnapshot", "deviceLog", "configCommit"):
        state = caps[key]
        assert isinstance(state, str), f"{key} must normalize to a string, got {state!r}"
        assert state in VALID_CAP_STATES, f"{key}={state!r}"
    # Candidate gateway serializes booleans: false -> not_ready, true -> available.
    assert caps["livePcm"] == "not_ready"
    assert caps["liveResults"] == "not_ready"
    assert caps["configCommit"] == "available"
    assert caps["deviceLog"] == "available"
    assert caps["resultSnapshotProtocol"] == 3
    assert caps["protocol3"] is True
    assert caps["configVersion"] == 1
    assert any("deterministic fixture model" in text for text in caps["missing"])
    harness.record_artifact("capability_gateway_device", {
        "sessionId": session.session_id,
        "connectionEpoch": session.connection_epoch,
        "deviceId": session.device_info.device_id,
        "capabilities": caps,
    })


def test_gateway_feature_api_is_reported(stack):
    refreshed = stack.session.refresh_capabilities()
    gateway = refreshed["gateway"]
    feature_api = gateway["featureApi"]
    assert feature_api["version"] == 1
    assert feature_api["enabled"] is True
    assert feature_api["featureCount"] == 51
    assert feature_api["maxResultWordsPerPage"] == 1024
    assert feature_api["catalogPageSize"] == 8
    assert gateway["mockFixture"] is True
    assert gateway["simulated"] is True
    assert gateway["protocol"] == "sixmic-analysis"
    assert gateway["protocolVersion"] == 1
    assert gateway["featureApi"]["enabled"] is True
    harness.record_artifact("capability_gateway_feature_api", {
        "gateway": gateway,
        "fixture": stack.fixture_note(),
    })


def test_live_pcm_capability_is_not_treated_as_available(stack):
    caps = stack.session.capabilities
    assert caps.live_pcm != "available"
    assert caps.live_pcm == "not_ready"
