"""Capability-state normalization: both protocol encodings must parse.

The frozen v1 backend models capability states as strings; the echo-features-1
candidate gateway serializes them as booleans.  The Lead-owned
sixmic_backend.model.dto.capability_state() normalizes both.  This test is the
unit-level proof; test_gateway_capability.py proves the same live over TCP.
"""
from __future__ import annotations

import pytest

from sixmic_backend.constants import CAP_STATES
from sixmic_backend.model.dto import DeviceCapabilities, capability_state

pytestmark = pytest.mark.e2e

STRING_STATES = CAP_STATES


@pytest.mark.parametrize("state", STRING_STATES)
def test_old_style_string_states_still_parse(state):
    assert capability_state(state) == state
    assert DeviceCapabilities.from_dict({"livePcm": state}).live_pcm == state


@pytest.mark.parametrize("value,expected", [
    (True, "available"),
    (False, "not_ready"),
])
def test_candidate_bool_encoding_normalizes(value, expected):
    assert capability_state(value) == expected
    caps = DeviceCapabilities.from_dict({"livePcm": value,
                                         "liveResults": value,
                                         "configCommit": value})
    assert caps.live_pcm == expected
    assert caps.live_results == expected
    assert caps.config_commit == expected


def test_missing_and_unknown_values_keep_documented_defaults():
    assert capability_state(None) == "not_ready"
    assert capability_state(None, "available") == "available"
    assert capability_state(1) == "not_ready"          # ints are not booleans
    assert capability_state(1.5) == "not_ready"
    assert capability_state("weird") == "not_ready"
    assert DeviceCapabilities.from_dict({}).device_log == "available"


def test_bool_false_live_pcm_is_not_available():
    # Candidate gateway currently reports livePcm=false.  The frozen session
    # layer must normalize it to not_ready, never to available.
    caps = DeviceCapabilities.from_dict({"livePcm": False})
    assert caps.live_pcm == "not_ready"
    assert caps.live_pcm != "available"


def test_bool_true_capabilities_remain_accepted():
    caps = DeviceCapabilities.from_dict({"livePcm": True, "liveResults": True,
                                         "eventCapture": True, "eventDownload": True,
                                         "taskControl": True, "deviceLog": True,
                                         "protocol3": True, "configVersion": 9})
    payload = caps.to_dict()
    for key in ("livePcm", "liveResults", "eventCapture", "eventDownload",
                "taskControl", "deviceLog"):
        assert payload[key] == "available"
    assert payload["protocol3"] is True
    assert payload["configVersion"] == 9
