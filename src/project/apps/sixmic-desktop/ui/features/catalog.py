"""Static echo-features-1 view catalog (read-only spec) + device catalog validation.

Pure Python, no Qt imports.  The generated JSON spec is the authority for the
51 feature entries, the 8-category page layout and the fixed-hidden launch
parameters; the device ``feature.list`` response is validated/merged here so the
runtime can label entries as available / blocked without ever exposing params.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

SPEC_VERSION = 1
INTERFACE_VERSION = "echo-features-1"
EXPECTED_FEATURE_COUNT = 45
CATALOG_PAGE_SIZE = 8
CATALOG_MAX_PAGE_SIZE = 16
MAX_RESULT_WORDS_PER_PAGE = 1024
MAX_JOB_SLOTS = 8

DEFAULT_SAMPLE_RATE_HZ = 48009.775390625
FFT_SIZE = 2048

SPEC_PATH = Path(__file__).resolve().parents[1] / "config" / "feature_view_spec.json"

# Bilingual reasons are the only UI-visible explanation for a disabled entry.
REASONS: dict[str, dict[str, str]] = {
    "not-connected": {
        "zh": "设备未连接；连接设备并取得控制权后可用。",
        "en": "Device not connected; connect and claim control first.",
    },
    "feature-api-missing": {
        "zh": "设备软件需要更新：未检测到 echo-features-1 的 featureApi，PC 不会用计算代替 PL 结果。",
        "en": "Device software update required: echo-features-1 featureApi is missing. "
              "PC-side computation is never substituted for PL results.",
    },
    "feature-api-disabled": {
        "zh": "设备 featureApi 未启用；禁止退回 PC 计算或假装成功。",
        "en": "Device featureApi is disabled; PC computation / fake success is not allowed.",
    },
    "old-gateway": {
        "zh": "设备网关版本过旧；需要升级到 echo-features-1。",
        "en": "Device gateway is too old; upgrade to echo-features-1 is required.",
    },
    "catalog-pending": {
        "zh": "功能目录尚未取得（feature.list 未完成）。",
        "en": "Feature catalog not fetched yet (feature.list incomplete).",
    },
    "catalog-incomplete": {
        "zh": "设备功能目录不完整或校验失败；请重新刷新目录。",
        "en": "Device feature catalog is incomplete or failed validation; refresh it.",
    },
    "not-in-device-catalog": {
        "zh": "设备功能目录不包含此功能。",
        "en": "The device feature catalog does not contain this feature.",
    },
    "layout-pending": {
        "zh": "结果字段映射尚未确认；仅显示原始字，不猜浮点值。",
        "en": "Result field mapping is not confirmed; raw words are shown and floats are never guessed.",
    },
}


def reason(key: str) -> dict[str, str]:
    """Return a copy of a bilingual reason (empty text when unknown)."""
    item = REASONS.get(str(key))
    return dict(item) if item else {"zh": "", "en": ""}


class CatalogError(ValueError):
    """Raised when the static spec or the device catalog violates the contract."""


@dataclass
class CatalogReport:
    """Validation result for one merged device ``feature.list`` response."""

    version: str = ""
    total: int = 0
    features: dict[str, dict[str, Any]] = field(default_factory=dict)
    duplicates: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    next_cursor: Any = None
    pages_seen: int = 0
    page_sizes: list[int] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return (not self.errors and not self.duplicates and not self.missing
                and not self.extra and len(self.features) == EXPECTED_FEATURE_COUNT)


def load_spec(path: str | Path | None = None) -> dict[str, Any]:
    """Load and structurally validate the generated feature view spec."""
    target = Path(path) if path is not None else SPEC_PATH
    try:
        spec = json.loads(target.read_text(encoding="utf-8"))
    except OSError as exc:  # pragma: no cover - defensive
        raise CatalogError(f"feature spec cannot be read: {exc}") from exc
    except ValueError as exc:
        raise CatalogError(f"feature spec is not valid JSON: {exc}") from exc
    if not isinstance(spec, dict):
        raise CatalogError("feature spec must be an object")
    features = spec.get("features")
    pages = spec.get("pages")
    if not isinstance(features, dict) or len(features) != EXPECTED_FEATURE_COUNT:
        raise CatalogError(f"feature spec needs {EXPECTED_FEATURE_COUNT} features")
    if not isinstance(pages, dict) or not pages:
        raise CatalogError("feature spec needs pages")
    seen: list[str] = []
    for page_id, page in pages.items():
        if not isinstance(page, dict) or not isinstance(page.get("groups"), list):
            raise CatalogError(f"page {page_id!r} has no groups")
        for group in page["groups"]:
            if not isinstance(group, dict) or not isinstance(group.get("features"), list):
                raise CatalogError(f"page {page_id!r} group is malformed")
            for fid in group["features"]:
                if fid not in features:
                    raise CatalogError(f"page {page_id!r} references unknown feature {fid!r}")
                seen.append(str(fid))
    if len(seen) != EXPECTED_FEATURE_COUNT or len(set(seen)) != EXPECTED_FEATURE_COUNT:
        raise CatalogError("each feature must appear exactly once in the page layout")
    if sorted(seen) != sorted(features):
        raise CatalogError("page layout and feature table disagree")
    for fid, feature in features.items():
        if not isinstance(feature, dict):
            raise CatalogError(f"feature {fid!r} is malformed")
        launch = feature.get("launch")
        if not isinstance(launch, dict):
            raise CatalogError(f"feature {fid!r} has no launch block")
        if str(launch.get("policy") or "") != "fixed-hidden":
            raise CatalogError(f"feature {fid!r} must use fixed-hidden launch policy")
        if bool(launch.get("userEditable")):
            raise CatalogError(f"feature {fid!r} must not expose editable params")
    return spec


class FeatureCatalog:
    """Spec-backed feature/page catalog with a device-catalog overlay."""

    def __init__(self, spec: dict[str, Any] | None = None, *,
                 spec_path: str | Path | None = None) -> None:
        self.spec = spec if spec is not None else load_spec(spec_path)
        self.features: dict[str, dict[str, Any]] = dict(self.spec.get("features") or {})
        self.pages: dict[str, dict[str, Any]] = dict(self.spec.get("pages") or {})
        self.device_default: dict[str, Any] = dict(self.spec.get("deviceDefault") or {})
        self.interface_version = str(self.spec.get("interfaceVersion") or INTERFACE_VERSION)
        device = self.device_default
        self.sample_rate_hz = float(device.get("sampleRateHz") or DEFAULT_SAMPLE_RATE_HZ)
        self.fft_size = int(device.get("fftSize") or FFT_SIZE)
        self.max_slots = int(device.get("maxJobSlots") or MAX_JOB_SLOTS)
        self.result_page_words = int(device.get("maxResultWordsPerPage")
                                     or MAX_RESULT_WORDS_PER_PAGE)
        self.device: dict[str, dict[str, Any]] = {}
        self.device_report = CatalogReport()
        self.device_catalog_complete = False
        self.device_version = ""

    # -- static lookups ----------------------------------------------------
    def feature(self, feature_id: str) -> dict[str, Any]:
        return self.features.get(str(feature_id)) or {}

    def feature_ids(self) -> list[str]:
        return list(self.features)

    def page_ids(self) -> list[str]:
        return list(self.pages)

    def page_features(self, page_id: str) -> list[dict[str, Any]]:
        """Ordered feature specs for a page (group order from the spec)."""
        page = self.pages.get(str(page_id))
        if not page:
            return []
        out: list[dict[str, Any]] = []
        for group in page.get("groups") or []:
            for fid in group.get("features") or []:
                feature = self.features.get(str(fid))
                if feature is None:
                    continue
                out.append({"feature": feature, "group": str(group.get("id") or "")})
        return out

    def page_meta(self, page_id: str) -> dict[str, Any]:
        return dict(self.pages.get(str(page_id)) or {})

    # -- device catalog ----------------------------------------------------
    def merge_device_catalog(self, result: Any) -> CatalogReport:
        """Validate a merged ``feature.list`` result and merge it.

        Accepts either one merged response (``features`` list) or a sequence of
        raw pages so that 8/16-item pagination can be verified before merging.
        """
        if isinstance(result, (list, tuple)):
            report = validate_feature_list_pages(
                result, expected_ids=list(self.features))
        else:
            report = _validate_merged(result, expected_ids=list(self.features))
        self.device_report = report
        self.device_catalog_complete = report.complete
        self.device_version = report.version
        self.device = dict(report.features) if report.features else {}
        return report

    def clear_device_catalog(self) -> None:
        self.device = {}
        self.device_report = CatalogReport()
        self.device_catalog_complete = False
        self.device_version = ""

    def device_feature(self, feature_id: str) -> dict[str, Any]:
        return self.device.get(str(feature_id)) or {}

    def availability(self, feature_id: str) -> tuple[bool, dict[str, str]]:
        """Entry-level availability under the current catalog state."""
        if str(feature_id) not in self.features:
            return False, reason("not-in-device-catalog")
        if self.device_catalog_complete and self.device:
            if str(feature_id) in self.device:
                return True, {"zh": "", "en": ""}
            return False, reason("not-in-device-catalog")
        return False, reason("catalog-pending")

    # -- summary -----------------------------------------------------------
    def summary(self) -> dict[str, Any]:
        return {
            "version": str(self.spec.get("version") or SPEC_VERSION),
            "interfaceVersion": self.interface_version,
            "featureCount": len(self.features),
            "pageCount": len(self.pages),
            "catalogComplete": bool(self.device_catalog_complete),
            "deviceVersion": self.device_version,
        }


def _normalise_feature(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    fid = row.get("featureId")
    if not isinstance(fid, str) or not fid:
        return None
    return dict(row)


def validate_feature_list_pages(pages: Iterable[Any], *,
                                expected_total: int = EXPECTED_FEATURE_COUNT,
                                expected_ids: Sequence[str] | None = None) -> CatalogReport:
    """Validate raw ``feature.list`` pages: version, cursor chain, duplicates, total.

    Rules from the interface contract: 8 items per page by default, at most 16,
    follow ``nextCursor`` until null, every page repeats the catalog version, a
    repeated cursor or a repeated feature is a protocol error, and the merged
    catalog must contain the 51 unique primary entries.
    """
    report = CatalogReport()
    expected = list(expected_ids or [])
    expected_set = set(expected)
    seen_ids: set[str] = set()
    collected: list[dict[str, Any]] = []
    cursor: Any = 0
    visited: set[Any] = set()
    page_list = list(pages)
    report.total = expected_total
    for index, page in enumerate(page_list):
        report.pages_seen = index + 1
        if not isinstance(page, dict):
            report.errors.append(f"page {index}: not an object")
            break
        features = page.get("features")
        if not isinstance(features, list):
            report.errors.append(f"page {index}: missing features array")
            break
        size = len(features)
        report.page_sizes.append(size)
        if size < 1 or size > CATALOG_MAX_PAGE_SIZE:
            report.errors.append(f"page {index}: size {size} outside 1..{CATALOG_MAX_PAGE_SIZE}")
        version = str(page.get("version") or "")
        if index == 0:
            report.version = version
        elif version != report.version:
            report.errors.append(f"page {index}: catalog version changed")
        cursor_in = page.get("cursor", cursor)
        if index and cursor_in is not None and cursor_in != cursor:
            report.errors.append(f"page {index}: cursor {cursor_in!r} != expected {cursor!r}")
        if cursor in visited:
            report.errors.append(f"page {index}: repeated cursor {cursor!r}")
            break
        visited.add(cursor)
        for row in features:
            item = _normalise_feature(row)
            if item is None:
                report.errors.append(f"page {index}: malformed feature row")
                continue
            fid = str(item["featureId"])
            if fid in seen_ids:
                report.duplicates.append(fid)
                continue
            seen_ids.add(fid)
            collected.append(item)
        next_cursor = page.get("nextCursor")
        if next_cursor is not None and not isinstance(next_cursor, (int, str)):
            report.errors.append(f"page {index}: malformed nextCursor")
            break
        if next_cursor is not None:
            # The gateway cursor is the next catalog offset; it must equal the
            # number of entries already collected by this page.
            try:
                numeric_cursor = int(next_cursor)
            except (TypeError, ValueError):
                numeric_cursor = -1
            if numeric_cursor != len(collected):
                report.errors.append(
                    f"page {index}: nextCursor {next_cursor!r} != collected {len(collected)}")
        if next_cursor is None:
            if index != len(page_list) - 1:
                report.errors.append("pages continue after nextCursor=null")
            break
        cursor = next_cursor
    else:
        report.errors.append("nextCursor chain did not terminate with null")
    total_in_pages = None
    if page_list and isinstance(page_list[0], dict):
        total_in_pages = page_list[0].get("total")
    if isinstance(total_in_pages, int) and total_in_pages and total_in_pages != len(collected):
        report.errors.append(f"catalog total {total_in_pages} != collected {len(collected)}")
    if len(collected) != expected_total:
        report.errors.append(f"collected {len(collected)} features, expected {expected_total}")
    report.features = {str(item["featureId"]): item for item in collected}
    if expected_set:
        report.missing = sorted(expected_set - set(report.features))
        report.extra = sorted(set(report.features) - expected_set)
    return report


def _validate_merged(result: Any, *, expected_ids: Sequence[str]) -> CatalogReport:
    """Validate the already-paginated ``feature.list`` result from the bridge."""
    report = CatalogReport()
    expected_set = set(expected_ids)
    report.total = len(expected_ids)
    if not isinstance(result, dict):
        report.errors.append("feature.list result is not an object")
        return report
    report.version = str(result.get("version") or "")
    if report.version != INTERFACE_VERSION:
        report.errors.append(f"catalog version {report.version!r} != {INTERFACE_VERSION!r}")
    features = result.get("features")
    if not isinstance(features, list):
        report.errors.append("feature.list result has no features array")
        return report
    report.pages_seen = -1  # merged by the bridge; raw page sizes not available
    seen: set[str] = set()
    collected: list[dict[str, Any]] = []
    for row in features:
        item = _normalise_feature(row)
        if item is None:
            report.errors.append("malformed feature row")
            continue
        fid = str(item["featureId"])
        if fid in seen:
            report.duplicates.append(fid)
            continue
        seen.add(fid)
        collected.append(item)
    next_cursor = result.get("nextCursor")
    report.next_cursor = next_cursor
    if next_cursor is not None:
        report.errors.append("merged catalog still has nextCursor")
    report.features = {str(item["featureId"]): item for item in collected}
    if len(report.features) != EXPECTED_FEATURE_COUNT:
        report.errors.append(f"catalog has {len(report.features)} features, "
                             f"expected {EXPECTED_FEATURE_COUNT}")
    report.missing = sorted(expected_set - set(report.features))
    report.extra = sorted(set(report.features) - expected_set)
    total = result.get("total")
    if isinstance(total, int) and total and total != len(report.features):
        report.errors.append(f"catalog total {total} != {len(report.features)}")
    return report
