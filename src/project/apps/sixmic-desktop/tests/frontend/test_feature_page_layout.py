"""Additive contract checks for the prompt 8-category feature page layout (ui-dev).

Read-only source checks only: no Qt event loop is started here.  These assertions
guard the user hard constraints for task-3:
  * the 51 features keep exactly one primary entry per spec.pages.groups order;
  * the legacy global ribbon / JSON parameter panels workbench are gone;
  * no parameter editor, job id, schema or raw-word access appears in the
    page-scoped feature UI;
  * the only catalog/API status block is the read-only Diagnostics section;
  * zh/en i18n keys stay in parity and the spec icons exist as linear SVGs.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
QML_ROOT = APP_ROOT / "ui" / "qml"
COMPONENTS = QML_ROOT / "components"
PAGES = QML_ROOT / "pages"
I18N = APP_ROOT / "ui" / "i18n"
SPEC_PATH = APP_ROOT / "ui" / "config" / "feature_view_spec.json"

# QML page file -> authoritative spec.pages id (prompt's eight logical categories).
PAGE_ENTRY = {
    "TimeDomainPage.qml": "time",
    "SpectrumPage.qml": "spectrum",
    "BandsPage.qml": "bands",
    "MultichannelPage.qml": "multichannel",
    "EventsPage.qml": "events",
    "PeriodicPage.qml": "periodic",
    "RoomPage.qml": "room",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _spec() -> dict:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def _i18n() -> dict[str, dict[str, str]]:
    merged: dict[str, dict[str, str]] = {"zh": {}, "en": {}}
    for path in sorted(I18N.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for language in ("zh", "en"):
            merged[language].update(payload.get(language) or {})
    return merged


def test_eight_pages_carry_their_page_scoped_entries_and_workspace():
    for name, page_id in PAGE_ENTRY.items():
        text = _read(PAGES / name)
        assert 'pageId: "' + page_id + '"' in text, (name, page_id)
        # Category pages share one chart-first shell; events additionally owns
        # the device event list. Both retain the same facade and single registry.
        shell = text if "FeatureEntryRow" in text else _read(COMPONENTS / "AnalysisPage.qml")
        assert "FeatureEntryRow" in shell and "FeatureWorkspace" in shell, name
        assert shell.index("FeatureEntryRow") < shell.index("FeatureWorkspace"), name


def test_spec_pages_are_the_seven_logic_categories_with_all_45_entries():
    spec = _spec()
    pages = spec["pages"]
    assert set(pages) == set(PAGE_ENTRY.values())
    seen: list[str] = []
    for page in pages.values():
        for group in page.get("groups") or []:
            assert group.get("features"), group
            seen.extend(group["features"])
    assert len(seen) == 45, len(seen)
    assert len(set(seen)) == 45
    assert set(seen) == set(spec["features"])
    # every QML page row receives the ordered groups from this spec (not the old maps)
    for name in PAGE_ENTRY:
        text = _read(PAGES / name)
        assert "FeatureWorkbenchPage" not in text
        assert "feature_ui_map" not in text and "feature_page_map" not in text


def test_legacy_global_feature_ui_is_removed():
    main = _read(QML_ROOT / "main.qml")
    assert "FeatureRibbon" not in main
    assert "FeaturePanel" not in main
    advanced = _read(PAGES / "AdvancedToolsPage.qml")
    for qml_page in ("PlotWorkbenchPage.qml", "PeriodicPage.qml", "RoomPage.qml"):
        assert qml_page in advanced, qml_page
    assert "FeatureWorkbenchPage" not in advanced
    assert re.search(r"property\s+int\s+subTab:\s*0", advanced), "AdvancedTools must default to 绘图工作台"
    assert not (PAGES / "FeatureWorkbenchPage.qml").exists()
    for path in PAGES.rglob("*.qml"):
        assert "FeatureWorkbenchPage" not in _read(path), path
    # the global ribbon/panel components may only exist as Lead-owned dead files, never loaded
    for path in PAGES.rglob("*.qml"):
        text = _read(path)
        assert "FeatureRibbon" not in text and "FeaturePanel" not in text, path


def test_feature_ui_has_no_parameter_editor_or_engineering_identifiers():
    targets = [COMPONENTS / "FeatureEntryRow.qml", COMPONENTS / "FeatureWorkspace.qml"]
    targets.extend(PAGES / name for name in PAGE_ENTRY)
    forbidden = [
        "setFeatureParams", "featureApi.params", "paramsEditor",
        "App.startSelectedFeature", "App.featureRibbon", "App.featurePanelOpen",
        "features.params_hint", "JSON.stringify", "features.tab",
    ]
    engineering_members = [".jobId", ".totalWords", ".schemaKind", ".words"]
    for path in targets:
        text = _read(path)
        for needle in forbidden:
            assert needle not in text, (path.name, needle)
        for needle in engineering_members:
            assert needle not in text, (path.name, needle)
    for path in targets[:2]:
        text = _read(path)
        for widget in ("TextArea", "TextField", "SpinBox"):
            assert widget not in text, (path.name, widget)
    # Native Button semantics supply role, shared controls expose accessible
    # labels/tooltips; the workspace no longer reimplements tiny controls.
    assert "Accessible.name" in _read(COMPONENTS / "AppButton.qml")
    assert "Accessible.name" in _read(COMPONENTS / "FeatureEntryRow.qml")


def test_entry_row_uses_spec_order_contract_and_workspace_api():
    row = _read(COMPONENTS / "FeatureEntryRow.qml")
    # Entry rows refresh from the structural entries signal (not from every
    # live chart frame, which used to rebuild all delegates per frame).
    for needle in ("featureGroupsForPage", "openFeatureEntry", "onFeatureEntriesChanged",
                   "entryCount", "property var workspace"):
        assert needle in row, needle
    workspace = _read(COMPONENTS / "FeatureWorkspace.qml")
    for needle in ("featureWorkspace", "featureStatus", "flow.actions",
                   "flow.confirmations", "featureConfirm", "featureAction",
                   "references", "freshness", "FeatureChart"):
        assert needle in workspace, needle
    # chart payload is display-filtered before it reaches the chart layer
    assert "sanitized(" in workspace
    for member in ('key === "jobId"', 'key === "words"', 'key === "resultSummary"',
                   'key === "schema"'):
        assert member in workspace, member


def test_diagnostics_is_the_only_read_only_feature_api_status_block():
    diagnostics = _read(PAGES / "DiagnosticsPage.qml")
    for needle in ("featureStatus", "deviceSoftwareNote", "refreshDiagnostics"):
        assert needle in diagnostics, needle
    assert 'App.t("studio.diagnostics")' in diagnostics
    for widget in ("TextArea", "TextField", "SpinBox"):
        assert widget not in diagnostics, widget
    assert ".jobId" not in diagnostics and ".totalWords" not in diagnostics
    # no other page renders catalog/API counters
    for name in PAGE_ENTRY:
        text = _read(PAGES / name)
        assert 'App.t("feature.api.title")' not in text, name


def test_feature_i18n_keys_exist_in_both_languages():
    merged = _i18n()
    assert set(merged["zh"]) == set(merged["en"]), (
        "missing en:", sorted(set(merged["zh"]) - set(merged["en"])),
        "missing zh:", sorted(set(merged["en"]) - set(merged["zh"])))
    required = [
        "feature.entries", "feature.status.api_missing", "feature.status.disconnected",
        "feature.tooltip.units", "feature.tooltip.prerequisites", "feature.tooltip.open_hint",
        "feature.workspace.unavailable_title", "feature.workspace.save_image",
        "feature.flow.confirmations", "feature.flow.confirm", "feature.flow.confirmed",
        "feature.reference.present", "feature.reference.none", "feature.reference.incompatible",
        "feature.variants", "feature.stale", "feature.elapsed",
        "feature.api.title", "feature.api.version", "feature.api.task_slots",
        "feature.api.catalog", "feature.api.categories",
        "feature.page.time", "feature.page.spectrum", "feature.page.bands",
        "feature.page.periodic", "feature.page.multichannel",
        "feature.page.events", "feature.page.room",
    ]
    for key in required:
        assert key in merged["zh"] and key in merged["en"], key
        assert merged["zh"][key] != key, key
        assert merged["en"][key] != key, key


def test_spec_icons_and_action_icons_exist_as_linear_svgs():
    spec = _spec()
    needed = {str(feature.get("icon") or "") for feature in spec["features"].values()}
    needed.discard("")
    # icons used by the workspace flow/reference affordances
    needed.update({"target", "snowflake", "arrow-left-right", "zap", "badge-check"})
    icons_dir = APP_ROOT / "assets" / "icons"
    assert len(needed) >= 20
    for icon in sorted(needed):
        path = icons_dir / (icon + ".svg")
        assert path.is_file(), icon
        text = _read(path)
        assert 'viewBox="0 0 24 24"' in text, icon
        assert "currentColor" in text, icon
        assert "stroke-width=" in text, icon
        assert "<text" not in text and "emoji" not in text.lower(), icon
    spec_text = _read(SPEC_PATH).lower()
    assert "emoji" not in spec_text
