"""51-feature catalog pagination: FeatureClient (8/page) and raw 8/16 limits."""
from __future__ import annotations

import pytest

import harness
from sixmic_backend.errors import BackendError

pytestmark = pytest.mark.e2e


def test_stock_client_catalog_returns_all_51_unique_features(stack):
    catalog = stack.client.list_features()
    assert catalog["version"] == "echo-features-1"
    assert catalog["nextCursor"] is None
    features = catalog["features"]
    assert isinstance(features, list) and len(features) == 51
    ids = [feature["featureId"] for feature in features]
    assert len(set(ids)) == 51
    spec = harness.load_spec()
    assert set(ids) == set(spec["features"])
    for feature in features:
        assert feature["hardwareAccepted"] is False
        assert isinstance(feature.get("schema"), dict) and feature["schema"]
        assert feature.get("implementation")
        assert feature.get("tier") in {"P0", "P1", "P2"}
        assert feature.get("mode") in {"p0", "p1", "p2", "staged", "events"}


@pytest.mark.parametrize("limit,expected_pages,expected_sizes", [
    (8, 7, [8, 8, 8, 8, 8, 8, 3]),
    (16, 4, [16, 16, 16, 3]),
])
def test_raw_catalog_pagination_limit_8_and_16(stack, limit, expected_pages, expected_sizes):
    scan = stack.catalog_scan(limit)
    pages, ids = scan["pages"], scan["featureIds"]
    assert scan["pageCount"] == expected_pages
    assert [len(page["features"]) for page in pages] == expected_sizes
    assert len(ids) == len(set(ids)) == 51
    assert [page["nextCursor"] for page in pages] == \
        ([limit * (index + 1) for index in range(expected_pages - 1)] + [None])
    assert all(page["total"] == 51 for page in pages)
    assert all(page["version"] == "echo-features-1" for page in pages)


def test_raw_catalog_limit_1_walks_every_entry(stack):
    scan = stack.catalog_scan(1)
    assert scan["pageCount"] == 51
    assert len(scan["featureIds"]) == len(set(scan["featureIds"])) == 51
    assert scan["pages"][0]["nextCursor"] == 1
    assert scan["pages"][-1]["nextCursor"] is None


@pytest.mark.parametrize("limit", [0, 17, 99])
def test_catalog_invalid_limits_rejected(stack, limit):
    with pytest.raises(BackendError) as excinfo:
        stack.raw_request("feature.list", {"cursor": 0, "limit": limit})
    assert excinfo.value.code in {"bad_args", "bad_state"}
    harness.record_artifact("catalog_pagination", {
        "catalogVersion": "echo-features-1",
        "featureCount": 51,
        "pagination": {"limit8": {"pages": 7, "sizes": [8, 8, 8, 8, 8, 8, 3]},
                       "limit16": {"pages": 4, "sizes": [16, 16, 16, 3]},
                       "limit1Pages": 51},
        "invalidLimits": [0, 17, 99],
        "fixture": stack.fixture_note(),
    })
