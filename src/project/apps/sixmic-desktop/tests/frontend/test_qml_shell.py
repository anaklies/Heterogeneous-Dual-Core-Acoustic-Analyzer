"""Lightweight GUI acceptance: real QML shell, all pages, language/theme, report."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[2]
# Left navigation: the prompt's eight logical categories + overview/records/bottom.
PAGES = ["overview", "time", "spectrum", "bands", "periodic", "multichannel",
         "events", "room", "recording", "diagnostics", "settings",
         "about"]


def _pump(application, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        application.processEvents()
        time.sleep(0.02)


@pytest.fixture()
def gui(qapp, user_dirs, protocol_root):
    import main as appmain
    from PySide6.QtCore import qInstallMessageHandler

    messages: list[str] = []

    def handler(mode, context, message):
        text = str(message)
        if text.startswith(("QFontDatabase", "Context2D: The font families specified",
                            "FT_New_Face failed")):
            return
        messages.append(text)

    previous = qInstallMessageHandler(handler)
    created = appmain.create_application()
    application, engine, bridge, vm, theme, images, qml = created
    window = engine.rootObjects()[0]
    window.resize(1600, 1000)
    _pump(application, 0.5)
    yield {"app": application, "engine": engine, "window": window, "vm": vm,
           "bridge": bridge, "theme": theme, "messages": messages}
    try:
        vm.prepareExit()
    except Exception:
        pass
    try:
        bridge.shutdown()
    except Exception:
        pass
    qInstallMessageHandler(previous)


def test_qml_shell_and_all_pages_load(gui):
    application = gui["app"]
    vm = gui["vm"]
    for page in PAGES:
        vm.setCurrentPage(page)
        _pump(application, 0.35)
        assert vm.currentPage == page
        assert vm.pageTitle not in ("", "page." + page + ".subtitle")
    assert gui["messages"] == [], gui["messages"][:5]


def test_theme_and_language_switch_without_errors(gui):
    application = gui["app"]
    vm = gui["vm"]
    vm.setThemeMode("dark")
    _pump(application, 0.3)
    assert gui["theme"].resolved == "dark"
    vm.setLanguage("en")
    _pump(application, 0.9)
    assert vm.language == "en"
    assert vm.t("nav.overview") == "Overview"
    roots = gui["engine"].rootObjects()
    assert roots, "QML reload lost the window"
    assert len(roots) == 1, f"duplicate windows after reload: {len(roots)}"
    vm.setCurrentPage("settings")
    _pump(application, 0.4)
    vm.setLanguage("zh")
    _pump(application, 0.9)
    assert vm.t("nav.overview") == "总览"
    vm.setThemeMode("light")
    _pump(application, 0.3)
    assert gui["messages"] == [], gui["messages"][:8]


def test_setting_slot_arity_from_qml(gui):
    from PySide6.QtCore import QMetaObject, Q_ARG
    vm = gui["vm"]
    QMetaObject.invokeMethod(vm, "setSetting", Q_ARG(str, "windowWidth"),
                             Q_ARG("QVariant", 1234))
    assert int(vm.settings["windowWidth"]) == 1234


def test_report_generation_with_authors_and_pdf(gui, tmp_path):
    vm = gui["vm"]
    vm.generateReport("测试报告 / Test report", "自动 GUI 测试生成，数据为测试夹具/离线参考。", "[]")
    reports = list((vm.user_root / "reports").glob("report-*.html"))
    assert reports, "report HTML not generated"
    latest = max(reports, key=lambda path: path.stat().st_mtime)
    body = latest.read_text(encoding="utf-8")
    assert "刘珉志" in body and "孟德旭" in body and "黑龙江大学" in body
    assert "offline" in body.lower() or "离线参考" in body
    pdf = latest.with_suffix(".pdf")
    assert pdf.is_file() and pdf.stat().st_size > 200


def test_product_scope_has_no_pc_offline_analysis(gui):
    source = (APP_ROOT / "ui" / "viewmodels" / "app_view_model.py").read_text(encoding="utf-8")
    assert "offline_reference" not in source
    assert "OfflineReference" not in source
    assert not (APP_ROOT / "ui" / "viewmodels" / "offline_reference.py").exists()
    vm = gui["vm"]
    vm.openRecording(str(APP_ROOT / "tests" / "frontend" / "fixtures" / "demo-recording"))
    assert vm.recordingData["replay"] is None
    assert vm.runOfflineAnalysis("fft") is None
    from ui.viewmodels.app_view_model import PAGES as APP_PAGES
    pages = [p["id"] for p in APP_PAGES]
    # Eight logical categories are the primary navigation; the old advanced
    # wrapper and the removed report page are no longer navigation entries.
    assert "report" not in pages and "advanced" not in pages
    for category in ("time", "spectrum", "bands", "periodic", "multichannel",
                     "events", "room"):
        assert category in pages
    assert len(pages) == 9


def test_pl_only_ui_and_chart_source_boundary(gui):
    qml = APP_ROOT / "ui" / "qml"
    for path in (qml / "pages").rglob("*.qml"):
        source = path.read_text(encoding="utf-8")
        assert "App.openRecording(" not in source, path
        assert "App.runOfflineAnalysis(" not in source, path
    vm = gui["vm"]
    vm._fixture_active = False
    vm._analysis = {"spectrum": {"available": True, "sourceKind": "offline-reference"},
                    "plots": {"xy": {"available": True}, "matrix": {"available": True}}}
    assert vm.spectrumData["available"] is False
    assert vm.plPlotCards == []
    vm._analysis["spectrum"] = {"available": True, "sourceKind": "pl-live", "series": []}
    assert [card["id"] for card in vm.plPlotCards] == ["fft"]


def test_live_subscription_uses_runtime_capabilities(gui, monkeypatch):
    vm = gui["vm"]
    sent = []
    monkeypatch.setattr(gui["bridge"], "subscribe", lambda payload: sent.append(json.loads(payload)))
    vm._fixture_active = False
    vm._capabilities = {"liveResults": "available", "livePcm": "not_ready",
                        "serviceSnapshots": ["header16"]}
    vm.subscribeLive()
    assert sent == [["resultWords", "serviceSnapshot"]]
    vm._capabilities = {"liveResults": "not_ready", "livePcm": "not_ready"}
    vm.subscribeLive()
    assert len(sent) == 1


def test_control_is_confirmed_by_backend_and_bad_services_are_ignored(gui, monkeypatch):
    vm = gui["vm"]
    monkeypatch.setattr(gui["bridge"], "claimControl", lambda: "pending")
    vm.claimControl()
    assert vm._control_held is False
    vm._on_operation(json.dumps({"control":"claimed"}))
    assert vm._control_held is True
    vm._on_operation(json.dumps({"control":"released"}))
    assert vm._control_held is False
    vm._on_service(json.dumps({"sourceKind":"pl-live", "validity":{"done":True,"error":5}}))
    assert vm._service_snapshot == {}


def test_failed_subscription_can_retry_on_capability_refresh(gui, monkeypatch):
    vm = gui["vm"]
    sent = []
    monkeypatch.setattr(gui["bridge"], "subscribe", lambda payload: sent.append(json.loads(payload)))
    vm._connection["state"] = "connected"
    caps = json.dumps({"liveResults":"available", "livePcm":"not_ready"})
    vm._on_capabilities(caps)
    vm._on_capabilities(caps)
    assert len(sent) == 1
    vm._on_backend_error(json.dumps({"op":"subscribe", "error":{"code":"io_error"}}))
    assert vm._live_subscription_requested is False
    vm._on_capabilities(caps)
    assert len(sent) == 2


def test_device_export_button_calls_the_real_bridge_slot(gui, monkeypatch):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest
    vm = gui["vm"]
    sent = []
    monkeypatch.setattr(gui["bridge"], "exportData", lambda directory: sent.append(directory))
    vm._connection["state"] = "connected"
    vm._recording = {"state":"stopped", "records":"2", "bytes":"64"}
    vm.dataChanged.emit()
    vm.setCurrentPage("recording")
    window = gui["window"]
    window.showNormal()
    window.resize(1280, 800)
    _pump(gui["app"], 0.3)
    button = window.findChild(QQuickItem, "exportDeviceRecording")
    assert button is not None and button.isEnabled()
    point = button.mapToScene(QPointF(button.width() / 2, button.height() / 2))
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(round(point.x()), round(point.y())))
    _pump(gui["app"], 0.1)
    assert len(sent) == 1 and sent[0].endswith("/exports")
    assert gui["messages"] == []


def test_inspector_collapse_button_has_normal_target_and_works(gui):
    """Redesigned responsive shell: under 1320 px the info panel is a drawer.

    The legacy assertion that the inline panel is visible at 1280 px no longer
    applies; the contract is now: open the drawer, the 44x44 / 26 px icon close
    control is present, and activating it really closes the drawer and updates
    App.inspectorCollapsed.
    """
    from PySide6.QtCore import QObject, QPoint, QPointF, Qt
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest
    vm = gui["vm"]
    window = gui["window"]
    window.showNormal()
    window.resize(1280, 800)
    _pump(gui["app"], 0.3)
    # Drawer is a Qt Quick Controls Popup (QObject), not a QQuickItem.
    drawer = window.findChild(QObject, "measurementDrawer")
    assert drawer is not None, "measurement drawer missing in narrow layout"
    drawer.open()
    _pump(gui["app"], 0.35)
    assert drawer.property("opened") is True
    button = drawer.findChild(QQuickItem, "collapseInspectorButton")
    assert button is not None and button.width() >= 44 and button.height() >= 44
    assert button.property("iconSize") == 26
    point = button.mapToScene(QPointF(button.width()/2, button.height()/2))
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(round(point.x()), round(point.y())))
    _pump(gui["app"], 0.35)
    assert drawer.property("opened") is False, "collapse control must close the drawer"
    assert vm.inspectorCollapsed is True
    # Wide layout keeps the inline panel (>=1320 px) and the same control state.
    window.resize(1600, 900)
    vm.setInspectorCollapsed(False)
    _pump(gui["app"], 0.35)
    inline = window.findChild(QQuickItem, "collapseInspectorButton")
    assert inline is not None and inline.width() >= 44
    assert gui["messages"] == []


def test_eight_category_pages_load_without_errors(gui):
    """The prompt's eight logical-category pages replace the old advanced wrapper."""
    from PySide6.QtQuick import QQuickItem
    vm = gui["vm"]
    categories = ["time", "spectrum", "bands", "periodic", "multichannel",
                  "events", "room"]
    for page_id in categories:
        vm.setCurrentPage(page_id)
        _pump(gui["app"], 0.25)
        assert vm.currentPage == page_id
        title = vm.pageTitle
        assert title and not title.startswith("nav.category_")
    # periodic/room are now first-class pages with a feature row
    vm.setCurrentPage("room")
    _pump(gui["app"], 0.3)
    row = gui["window"].findChild(QQuickItem, "featureEntryRow")
    assert row is not None
    assert gui["messages"] == []

def test_event_monitor_workspace(gui):
    """Monitoring workspace: learning -> lock -> polling, real backend events."""
    import time as _time
    application = gui["app"]
    vm = gui["vm"]
    vm.startFixtureDemo()
    end = _time.monotonic() + 12
    while _time.monotonic() < end and vm.dataSource != "test-fixture":
        application.processEvents()
        _time.sleep(0.02)
    assert vm.connectionState == "connected"
    vm.setCurrentPage("events")
    _pump(application, 0.3)
    vm.startMonitor()
    assert vm.monitorData["active"] is True
    end = _time.monotonic() + 10
    while _time.monotonic() < end and vm.monitorData["phase"] in ("idle", "learning"):
        application.processEvents()
        _time.sleep(0.03)
    assert vm.monitorData["phase"] in ("locked", "monitoring")
    # Allow the local background model to lock and enter monitoring.
    end = _time.monotonic() + 10
    while _time.monotonic() < end and vm.monitorData["phase"] != "monitoring":
        application.processEvents()
        _time.sleep(0.03)
    assert vm.monitorData["phase"] == "monitoring"
    assert vm.monitorData["eventsSeen"] >= 0
    vm.setMonitorSetting("thresholdDb", -42)
    assert abs(float(vm.monitorData["settings"]["thresholdDb"]) + 42) < 1e-6
    vm.stopMonitor()
    assert vm.monitorData["active"] is False
    assert gui["messages"] == [], gui["messages"][:5]


def test_settings_apply_and_restart_flag(gui):
    vm = gui["vm"]
    vm.setSetting("fontScale", 1.0)
    assert vm.settingsDirty is True
    assert vm.applySettings() is True
    assert vm.settingsDirty is False
    assert vm.settingsApplyMessage != ""
    assert vm.restartRequired is False
    assert "windowMaximized" in vm.settings

def test_fullscreen_and_adaptive_window(gui):
    window = gui["window"]
    vm = gui["vm"]
    assert vm.settings["windowWidth"] >= 1280
    assert vm.settings["windowHeight"] >= 800
    window.visibility = 5  # Window.FullScreen
    _pump(gui["app"], 0.2)
    window.visibility = 4  # Window.Maximized
    _pump(gui["app"], 0.2)
    assert window.visibility == 4
    window.visibility = 2  # Window.Windowed
    _pump(gui["app"], 0.2)
    assert window.visibility == 2


def test_settings_device_address_stays_user_edited_and_persists(gui, monkeypatch):
    """Regression: the address field must not be reset to the preset by telemetry.

    The legacy field was bound to App.settings.host; every dataChanged/telemetry
    notification re-evaluated that binding and overwrote what the user typed.
    """
    from PySide6.QtCore import QMetaObject, Qt
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest
    vm = gui["vm"]
    window = gui["window"]
    app = gui["app"]
    window.showNormal()
    window.resize(1600, 900)
    vm.setCurrentPage("settings")
    _pump(app, 0.35)
    field = window.findChild(QQuickItem, "deviceAddressField")
    assert field is not None, "settings address field missing"
    field.forceActiveFocus()
    window.requestActivate()
    _pump(app, 0.15)
    # QTest key events are delivered to the QWindow's focused item.
    field.setProperty("text", "")
    for ch in "10.20.30.40":
        key = Qt.Key.Key_Period if ch == "." else getattr(Qt.Key, "Key_" + ch)
        QTest.keyClick(window, key)
    _pump(app, 0.2)
    assert field.property("text").strip() == "10.20.30.40"
    # Simulate frequent status/telemetry updates: they must not reset the field.
    for _ in range(6):
        vm.dataChanged.emit()
        _pump(app, 0.03)
    assert field.property("text").strip() == "10.20.30.40",         "telemetry dataChanged must not overwrite the address being edited"
    QTest.keyClick(window, Qt.Key.Key_Return)
    _pump(app, 0.25)
    assert str(vm.settings["host"]) == "10.20.30.40"
    # The Connect button must use and persist exactly this address.
    seen = []
    monkeypatch.setattr(gui["bridge"], "connectDevice",
                        lambda host, control_port, binary_port: seen.append(
                            (host, control_port, binary_port)))
    button = window.findChild(QQuickItem, "settingsConnectButton")
    assert button is not None
    assert QMetaObject.invokeMethod(button, "clicked")
    _pump(app, 0.25)
    assert seen and seen[-1][0] == "10.20.30.40"
    import json
    saved = json.loads(vm.settings_path.read_text(encoding="utf-8"))
    assert saved["host"] == "10.20.30.40"
    assert gui["messages"] == []


def test_fixture_demo_does_not_replace_saved_device_address(gui, monkeypatch):
    vm = gui["vm"]
    app = gui["app"]
    monkeypatch.setattr(gui["bridge"], "connectDevice", lambda *args: None)
    vm.setSetting("host", "10.20.30.41")
    vm._fixture_active = True
    try:
        vm.connectDevice("127.0.0.1", 12345, 12346)
        _pump(app, 0.1)
    finally:
        vm._fixture_active = False
    assert str(vm.settings["host"]) == "10.20.30.41"
    assert vm.connection["host"] == "127.0.0.1"
    # Empty/whitespace addresses are ignored instead of replacing a valid one.
    vm.setSetting("host", "   ")
    assert str(vm.settings["host"]) == "10.20.30.41"
    assert gui["messages"] == []


def test_settings_save_address_button_persists_manual_gateway(gui):
    """Manual address + explicit Save writes ui_settings.json; no auto-probe."""
    from PySide6.QtCore import QMetaObject, Qt
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest
    vm = gui["vm"]
    window = gui["window"]
    app = gui["app"]
    window.showNormal(); window.resize(1600, 900)
    vm.setCurrentPage("settings")
    _pump(app, 0.4)
    field = window.findChild(QQuickItem, "deviceAddressField")
    save = window.findChild(QQuickItem, "settingsSaveAddressButton")
    assert field is not None and save is not None
    field.forceActiveFocus(); window.requestActivate(); _pump(app, 0.15)
    field.setProperty("text", "")
    for ch in "10.77.1.9":
        key = Qt.Key.Key_Period if ch == "." else getattr(Qt.Key, "Key_" + ch)
        QTest.keyClick(window, key)
    _pump(app, 0.2)
    assert field.property("text").strip() == "10.77.1.9"
    assert QMetaObject.invokeMethod(save, "clicked") is True
    _pump(app, 0.2)
    assert str(vm.settings["host"]) == "10.77.1.9"
    saved = json.loads(vm.settings_path.read_text(encoding="utf-8"))
    assert saved["host"] == "10.77.1.9"
    assert gui["messages"] == []


def test_duplicate_connect_while_connecting_is_ignored(gui, monkeypatch):
    """A second connect during handshake must not surface a misleading busy error."""
    calls = []
    monkeypatch.setattr(gui["bridge"], "connectDevice",
                        lambda host, cp, bp: calls.append((host, cp, bp)))
    vm = gui["vm"]
    vm._connection["state"] = "connecting"
    vm._busy = True
    try:
        assert vm.connectDevice("10.9.8.7", 48120, 48121) == ""
        assert not calls
    finally:
        vm._busy = False
        vm._connection["state"] = "disconnected"
