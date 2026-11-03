"""Capability honesty and the 46-row feature catalog derived from the real CSV."""
from __future__ import annotations

import pytest

from sixmic_backend.constants import CAP_STATES, REMOVED_CAPABILITIES
from sixmic_backend.errors import BackendError
from sixmic_backend.model.dto import DeviceCapabilities
from sixmic_backend.model.feature_catalog import FeatureCatalog, load_feature_catalog


def test_default_capabilities_are_not_ready():
    caps = DeviceCapabilities()
    assert caps.live_pcm == "not_ready"
    assert caps.live_results == "not_ready"
    assert caps.profile_upload == "not_ready"
    assert caps.config_commit == "not_ready"
    assert caps.device_log == "available"
    for field in ("live_pcm", "live_results", "event_capture", "event_download",
                  "raw_recording", "profile_upload", "profile_activate",
                  "task_control", "sensor_snapshot", "device_log", "config_commit"):
        assert getattr(caps, field) in CAP_STATES


def test_available_without_evidence_is_rejected():
    catalog = load_feature_catalog()
    feature = dict(catalog.get("io_pcm"))
    forged = dict(feature)
    forged["status"] = "available"
    payload = {"features": [forged] + [catalog.features[key]
                                       for key in catalog.features
                                       if key != "io_pcm"]}
    with pytest.raises(BackendError) as info:
        FeatureCatalog(payload)
    assert info.value.code == "schema_mismatch"


def test_catalog_has_52_rows_and_honest_statuses():
    catalog = load_feature_catalog()
    summary = catalog.summary()
    assert summary["total"] == 46
    assert summary["available"] == 0, "no feature may claim available before board acceptance"
    assert summary["unsupported"] == 1
    assert catalog.get("srpdnn_main")["status"] == "unsupported"
    assert catalog.get("io_pcm")["status"] == "not_ready"
    assert catalog.get("psd")["status"] == "experimental"
    assert catalog.get("stipa_experimental")["experimental"] is True
    # removed capabilities must never appear as product features
    for removed in REMOVED_CAPABILITIES:
        assert removed not in catalog.features


def test_catalog_evidence_mentions_real_sources():
    catalog = load_feature_catalog()
    for feature in catalog.features.values():
        evidence = feature["evidence"]
        assert evidence["sourceType"] == "FUNCTION_EXECUTION_MAP.csv"
        assert evidence["completeFunctionHardwareAccepted"] is False
        assert evidence["wholeBoardAccepted"] is False
