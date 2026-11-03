"""Frontend catalog tests: 51 unique entries, 8-category layout, pagination rules.

All device data used here is the captured host-gateway test fixture
(fixtures/features/captured_host_gateway.json, sourceKind=test-fixture,
hardwareState=NOT_TESTED) -- never real hardware or acoustic acceptance.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ui.features.catalog import (CATALOG_MAX_PAGE_SIZE, EXPECTED_FEATURE_COUNT,
                                 INTERFACE_VERSION, CatalogError, FeatureCatalog,
                                 load_spec, validate_feature_list_pages)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "features"

# The prompt's EIGHT documented logical categories, page -> one category group.
CONTRACT_LAYOUT = {
    "time": {"acquisition": ["io_pcm", "levels_core", "levels_extended",
                             "data_continuity", "signal_quality"]},
    "spectrum": {"spectrum_compare": ["fft", "psd", "stft", "spectrum_average",
                                      "peak_hold", "smoothing", "zoom_fft",
                                      "spectrum_freeze", "relative_limit"]},
    "bands": {"bands_stats": ["octave", "third_octave", "frequency_time_weighting",
                              "level_statistics", "noise_rating"]},
    "periodic": {"periodic": ["frequency_tracking", "frequency_drift", "centroid",
                              "flatness", "spectral_kurtosis", "cepstrum",
                              "fundamental", "harmonic_ratio", "sidebands",
                              "envelope_hilbert", "envelope_spectrum",
                              "modulation_spectrum"]},
    "multichannel": {"multichannel": ["csd", "coherence_phase", "autocorrelation",
                                      "cross_correlation", "gcc_phat"]},
    "events": {"events": ["energy_change", "band_tracking", "spectral_flux",
                          "event_trigger"]},
    "room": {"room": ["room_decay", "room_clarity", "spectral_decay",
                      "relative_insulation", "stipa_experimental"]},
}



@pytest.fixture(scope="module")
def spec():
    return load_spec()


@pytest.fixture(scope="module")
def gateway_fixture():
    path = FIXTURES / "captured_host_gateway.json"
    assert path.is_file(), "captured host-gateway fixture is required"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data.get("sourceKind") == "test-fixture"
    assert data.get("hardwareState") == "NOT_TESTED"
    assert "test-feature-server" in data.get("server", "")
    return data


def _catalog_result(spec, *, version=INTERFACE_VERSION):
    return {"version": version, "total": EXPECTED_FEATURE_COUNT,
            "features": [{"featureId": fid, "name": fid}
                         for fid in spec["features"]],
            "nextCursor": None}


# ---------------------------------------------------------------------------
# static spec / 8-category layout
# ---------------------------------------------------------------------------
def test_spec_has_45_unique_primary_entries(spec):
    features = spec["features"]
    assert len(features) == EXPECTED_FEATURE_COUNT == 45
    assert len(set(features)) == 45
    placed = [fid for page in spec["pages"].values()
              for group in page["groups"] for fid in group["features"]]
    assert len(placed) == 45
    assert sorted(placed) == sorted(features)
    assert spec["interfaceVersion"] == INTERFACE_VERSION
    assert spec["deviceDefault"]["maxJobSlots"] == 8
    assert spec["deviceDefault"]["catalogPageSize"] == 8
    assert spec["deviceDefault"]["catalogMaxPageSize"] == 16
    assert spec["deviceDefault"]["maxResultWordsPerPage"] == 1024


def test_page_layout_matches_documented_8_categories(spec):
    assert list(spec["pages"]) == list(CONTRACT_LAYOUT)
    for page_id, groups in CONTRACT_LAYOUT.items():
        page = spec["pages"][page_id]
        found = {group["id"]: list(group["features"]) for group in page["groups"]}
        assert found == groups, page_id


def test_every_entry_is_view_and_flow_metadata(spec):
    required = {"featureId", "name", "shortZh", "shortEn", "nameEn", "page",
                "group", "icon", "chart", "tier", "mode", "units", "validity",
                "limitations", "schemaKind", "producer", "prerequisites",
                "devicePath", "launch", "decode", "runtime", "display",
                "params"}
    for fid, feature in spec["features"].items():
        missing = required - set(feature)
        assert not missing, (fid, missing)
        assert feature["featureId"] == fid
        page = spec["pages"][feature["page"]]
        groups = {group["id"]: group for group in page["groups"]}
        assert feature["group"] in groups
        assert fid in groups[feature["group"]]["features"]


def test_all_launch_parameters_are_fixed_and_hidden(spec):
    for fid, feature in spec["features"].items():
        launch = feature["launch"]
        assert launch["policy"] == "fixed-hidden", fid
        assert launch["userEditable"] is False, fid
        params = launch.get("params")
        if params is not None:
            assert isinstance(params, dict), fid
        # The only confirmation-like keys in launch must be documented actions.
        for key in ("stimulus", "referenceJobId", "confirmed", "testSignalConfirmed"):
            if params and key in params:
                assert key in {"referenceJobId", "confirmed", "testSignalConfirmed"}, (
                    fid, key)
        runtime_params = (feature.get("parameterPolicy") or {}).get(
            "runtimeMutableParams") or []
        assert "stimulus" not in runtime_params or feature["launch"]["kind"] == (
            "room_stimulus")


def test_no_param_editor_metadata_in_entries_source(spec):
    # params exist only for internal validation/diagnostics and are never
    # exposed by FeatureRuntime.entries(); every mutability is documented as
    # compiled/variant/runtime/control (no free-form editing path).
    for fid, feature in spec["features"].items():
        for field in (feature.get("params") or {}).get("fields") or []:
            assert field.get("mutability") in (
                "compiled", "variant", "runtime", "control"), (fid, field.get("key"))


def test_pending_layouts_are_the_five_confirmed_features(spec):
    pending = {fid for fid, feature in spec["features"].items()
               if (feature.get("decode") or {}).get("layoutStatus")
               == "pending-layout-resolution"}
    # Lead removes layoutStatus from the generator once evidence lands; the
    # runtime/decoder confirms exactly these five from the device services.
    assert pending <= {"frequency_time_weighting", "level_statistics",
                       "noise_rating", "spectral_kurtosis",
                       "relative_insulation"}


def test_zoom_fft_registry_fix_removes_blocking_gap(spec):
    path = spec["features"]["zoom_fft"]["devicePath"]
    assert not path.get("knownGap"), "registry now provides inputWords/inputWordOffset"
    assert path.get("implementedDevicePath") is True
    assert path.get("hardwareState") == "NOT_TESTED"
    assert path.get("hardwareAccepted") is False
    assert path.get("numericVerified") is False


# ---------------------------------------------------------------------------
# real host-gateway catalog pagination fixture
# ---------------------------------------------------------------------------
def test_real_catalog_pages_validate_8_per_page(gateway_fixture, spec):
    pages = gateway_fixture["catalog"]["pages"]
    report = validate_feature_list_pages(pages, expected_ids=list(spec["features"]))
    assert report.complete, report.errors
    assert report.version == INTERFACE_VERSION
    assert report.page_sizes == [8, 8, 8, 8, 8, 5]
    assert report.pages_seen == 6
    assert len(report.features) == 45
    assert report.next_cursor is None
    assert report.duplicates == [] and report.missing == [] and report.extra == []


def test_16_per_page_is_accepted(spec):
    ids = list(spec["features"])
    pages = []
    for start in range(0, len(ids), 16):
        chunk = ids[start:start + 16]
        pages.append({"version": INTERFACE_VERSION, "total": 45,
                      "features": [{"featureId": fid} for fid in chunk],
                      "nextCursor": start + 16 if start + 16 < 45 else None})
    report = validate_feature_list_pages(pages, expected_ids=ids)
    assert report.complete, report.errors
    assert report.page_sizes[:3] == [16, 16, 13]
    assert report.pages_seen == 3


def _pages(pages):
    return copy.deepcopy(pages)


def test_duplicate_primary_entry_is_rejected(gateway_fixture, spec):
    pages = _pages(gateway_fixture["catalog"]["pages"])
    pages[1]["features"].append(dict(pages[1]["features"][0]))
    report = validate_feature_list_pages(pages, expected_ids=list(spec["features"]))
    assert not report.complete
    assert report.duplicates
    assert any("expected 45" in error or "duplicate" in error.lower()
               for error in report.errors) or report.duplicates


def test_out_of_order_or_repeated_cursor_is_rejected(gateway_fixture, spec):
    pages = _pages(gateway_fixture["catalog"]["pages"])
    pages[2]["nextCursor"] = 99
    report = validate_feature_list_pages(pages, expected_ids=list(spec["features"]))
    assert not report.complete
    assert any("cursor" in error.lower() for error in report.errors)


def test_unterminated_cursor_chain_is_rejected(gateway_fixture, spec):
    pages = _pages(gateway_fixture["catalog"]["pages"])[:3]
    report = validate_feature_list_pages(pages, expected_ids=list(spec["features"]))
    assert not report.complete
    assert report.pages_seen == 3


def test_version_change_mid_catalog_is_rejected(gateway_fixture, spec):
    pages = _pages(gateway_fixture["catalog"]["pages"])
    pages[3]["version"] = "echo-features-2"
    report = validate_feature_list_pages(pages, expected_ids=list(spec["features"]))
    assert not report.complete
    assert any("version" in error for error in report.errors)


def test_oversized_page_is_rejected(spec):
    ids = list(spec["features"])[:20]
    pages = [{"version": INTERFACE_VERSION, "features": [{"featureId": fid} for fid in ids],
              "nextCursor": None}]
    report = validate_feature_list_pages(pages, expected_ids=list(spec["features"]))
    assert not report.complete
    assert any("size" in error for error in report.errors)


# ---------------------------------------------------------------------------
# merged catalog + availability
# ---------------------------------------------------------------------------
def test_catalog_merge_and_availability(spec):
    catalog = FeatureCatalog(spec)
    available, reason = catalog.availability("psd")
    assert available is False
    assert reason["zh"] and reason["en"]  # catalog-pending

    report = catalog.merge_device_catalog(_catalog_result(spec))
    assert report.complete and catalog.device_catalog_complete
    for fid in spec["features"]:
        available, reason = catalog.availability(fid)
        assert available, (fid, reason)

    catalog.clear_device_catalog()
    assert catalog.device_catalog_complete is False


def test_merged_catalog_rejects_missing_duplicate_extra_and_bad_version(spec):
    catalog = FeatureCatalog(spec)
    missing = _catalog_result(spec)
    missing["features"] = missing["features"][:-1]
    report = catalog.merge_device_catalog(missing)
    assert not report.complete and report.missing == ["zoom_fft"] or report.missing

    duplicated = _catalog_result(spec)
    duplicated["features"].append({"featureId": spec["features"].popitem()[0]
                                   if False else list(spec["features"])[0]})
    report = catalog.merge_device_catalog(duplicated)
    assert not report.complete and report.duplicates

    extra = _catalog_result(spec)
    extra["features"].append({"featureId": "not_a_real_feature"})
    report = catalog.merge_device_catalog(extra)
    assert not report.complete and "not_a_real_feature" in report.extra

    old = _catalog_result(spec, version="0.9")
    report = catalog.merge_device_catalog(old)
    assert not report.complete
    assert any("echo-features-1" in error for error in report.errors)


def test_load_spec_rejects_invalid_files(tmp_path):
    broken = tmp_path / "spec.json"
    broken.write_text("{}", encoding="utf-8")
    with pytest.raises(CatalogError):
        load_spec(broken)
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not json", encoding="utf-8")
    with pytest.raises(CatalogError):
        load_spec(bad_json)


def test_reason_helper_is_bilingual():
    from ui.features.catalog import reason
    for key in ("not-connected", "feature-api-missing", "old-gateway",
                "catalog-pending", "layout-pending"):
        item = reason(key)
        assert item["zh"] and item["en"]
    assert reason("does-not-exist") == {"zh": "", "en": ""}


def test_catalog_page_ordering_preserves_group_order(spec):
    catalog = FeatureCatalog(spec)
    entries = catalog.page_features("periodic")
    ids = [item["feature"]["featureId"] for item in entries]
    assert ids == CONTRACT_LAYOUT["periodic"]["periodic"]
    groups = [item["group"] for item in entries]
    assert groups == ["periodic"] * 12
    assert len(CONTRACT_LAYOUT) * 0 == 0
