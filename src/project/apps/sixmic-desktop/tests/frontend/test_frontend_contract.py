"""Frontend contract checks: feature map coverage, forbidden constants, app facade."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[2]
FEATURE_CATALOG = APP_ROOT.parents[1] / "interfaces" / "pc_backend_v1" / "features" / "FEATURE_CATALOG.json"
FEATURE_MAP = APP_ROOT / "ui" / "config" / "feature_ui_map.json"
QML_ROOT = APP_ROOT / "ui" / "qml"


def test_feature_ui_map_covers_every_catalog_row():
    catalog = json.loads(FEATURE_CATALOG.read_text(encoding="utf-8"))
    mapping = json.loads(FEATURE_MAP.read_text(encoding="utf-8"))
    catalog_ids = {row["featureId"] for row in catalog["features"]}
    mapped_ids = set(mapping["features"].keys())
    assert catalog_ids == mapped_ids, (
        f"missing={sorted(catalog_ids - mapped_ids)} extra={sorted(mapped_ids - catalog_ids)}")
    assert len(catalog_ids) == 46
    for feature_id, entry in mapping["features"].items():
        assert entry["page"] in mapping["pages"], (feature_id, entry["page"])
    removed = mapping["features"]["srpdnn_main"]
    assert removed["role"] == "removed"
    assert removed["page"] == "overview"


def test_no_hardware_internals_or_legacy_port_in_qml():
    forbidden = [
        r"0x43[cC]20000", r"0x43C2", r"\b48110\b", r"\bDDR\b", r"\bMMIO\b",
        r"0x1c\b", r"SM_C_", r"runtime_control", r"microprogram",
    ]
    problems = []
    for path in QML_ROOT.rglob("*.qml"):
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden:
            if re.search(pattern, text):
                problems.append(f"{path.relative_to(APP_ROOT)}: {pattern}")
    assert problems == [], problems


def test_no_52_independent_navigation_buttons():
    shell = (QML_ROOT / "main.qml").read_text(encoding="utf-8")
    assert "NavRail" in shell
    nav = (QML_ROOT / "components" / "NavRail.qml").read_text(encoding="utf-8")
    assert "App.navPages" in nav and "App.bottomPages" in nav
    source = (APP_ROOT / "ui" / "viewmodels" / "app_view_model.py").read_text(encoding="utf-8")
    assert 'PAGES = [' in source and 'BOTTOM_PAGES = [' in source
    assert source.count('{"id":') >= 11


def test_language_switch_is_single_auditable_layer():
    source = (APP_ROOT / "ui" / "viewmodels" / "app_view_model.py").read_text(encoding="utf-8")
    assert "def t(self, key: str)" in source
    i18n_files = list((APP_ROOT / "ui" / "i18n").glob("*.json"))
    assert i18n_files, "translation JSON files missing"
    for path in i18n_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert "zh" in payload and "en" in payload
    # no inline zh/en ternary translation in QML
    offenders = []
    for path in QML_ROOT.rglob("*.qml"):
        text = path.read_text(encoding="utf-8")
        if re.search(r"App\.language\s*===?\s*\"zh\"", text) and "App.t(" not in text:
            offenders.append(str(path))
    assert offenders == [], offenders


def test_chart_data_contract_references_units_and_source():
    contract = (APP_ROOT / "docs" / "frontend" / "CHART_DATA_CONTRACT.md").read_text(encoding="utf-8")
    for keyword in ("sourceKind", "offline-reference", "gap", "unit"):
        assert keyword in contract or keyword.lower() in contract.lower()
    assert "empty" in contract.lower() or "无数据" in contract


def _wait(application, predicate, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        application.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture()
def app_fixture(qapp, protocol_root, user_dirs):
    from sixmic_backend.qt.adapter import create_bridge
    from ui.viewmodels.app_view_model import AppViewModel
    from ui.viewmodels.plot_images import PlotImageProvider
    from ui.viewmodels.theme_source import ThemeSource

    bridge = create_bridge(protocol_root=str(protocol_root))
    images = PlotImageProvider()
    theme = ThemeSource()
    vm = AppViewModel(bridge, theme, images, None)
    yield qapp, bridge, vm
    try:
        vm.prepareExit()
        bridge.shutdown()
    except Exception:
        pass


def test_fixture_demo_flows_through_real_backend(app_fixture):
    application, bridge, vm = app_fixture
    vm.startFixtureDemo()
    assert _wait(application, lambda: vm.dataSource == "test-fixture", 12.0)
    assert vm.frameCount >= 1
    assert vm.capabilities.get("livePcm") == "not_ready"
    assert vm.t("source.test_fixture") != "source.test_fixture"
    vm.listEvents()
    assert _wait(application, lambda: len(vm.eventsData["events"]) >= 1, 6.0)
    vm.stopFixtureDemo()
    assert _wait(application, lambda: vm.connectionState in ("disconnected", "failed"), 6.0)


def test_offline_reference_removed_from_product():
    """PC-side offline analysis was removed from the product scope."""
    app_source = (APP_ROOT / "ui" / "viewmodels" / "app_view_model.py").read_text(encoding="utf-8")
    assert "offline_reference" not in app_source
    assert not (APP_ROOT / "ui" / "viewmodels" / "offline_reference.py").exists()
    assert (APP_ROOT / "tests" / "research" / "offline_reference_research.py").exists()
    qml = "\n".join(p.read_text(encoding="utf-8") for p in (QML_ROOT / "pages").rglob("*.qml"))
    assert "runOfflineAnalysis" not in qml
    assert "App.openRecording(" not in qml
def test_language_switch_persists(app_fixture, user_dirs):
    application, bridge, vm = app_fixture
    zh = vm.t("nav.overview")
    vm.setLanguage("en")
    english = vm.t("nav.overview")
    assert zh != english
    config = json.loads((user_dirs / "ui" / "ui_settings.json").read_text(encoding="utf-8"))
    assert config["language"] == "en"
    vm.setLanguage("zh")
