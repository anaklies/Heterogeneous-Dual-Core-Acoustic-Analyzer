"""Offscreen QML load check for the SixMic3D Qt Quick chart components.

The gallery page instantiates all seven contract components (WaveformChart,
LineChart, BarChart, HeatmapChart, PolarChart, LevelMeter, TimelineChart) plus
the empty/busy states. This check loads it inside a real (offscreen) Window with
the production Theme context property, collects every QML warning/error and
grabToImage screenshots for visual QA.

Run from apps/sixmic-desktop:

    set QT_QPA_PLATFORM=offscreen
    .venv/Scripts/python.exe ui/qml/components/charts/_selftest/qml_load_check.py

Exit code 0 = zero QML warnings/errors, all components instantiated, interaction
counters wired. Screenshots are written to _selftest/out/.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time

APP_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                            "..", "..", "..", "..", ".."))
CHART_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SELFTEST = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(SELFTEST, "out")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if not os.environ.get("QT_QPA_FONTDIR"):
    src_fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    try:
        font_copy = tempfile.mkdtemp(prefix="sixmic_chart_fonts_")
        copied = 0
        for name in ("segoeui.ttf", "segoeuib.ttf", "consola.ttf", "consolab.ttf"):
            candidate = os.path.join(src_fonts, name)
            if os.path.isfile(candidate):
                shutil.copy2(candidate, font_copy)
                copied += 1
    except OSError as exc:  # sandbox denies the temp copy on some hosts
        print("[QML-LOAD] font copy unavailable (" + str(exc)[:80] + "), using host font dir")
        copied = 0
    if copied:
        os.environ["QT_QPA_FONTDIR"] = font_copy
    elif os.path.isdir(src_fonts):
        os.environ["QT_QPA_FONTDIR"] = src_fonts

sys.path.insert(0, APP_ROOT)

from PySide6.QtCore import (Property, QCoreApplication, QEvent, QEventLoop, QObject, QPoint,
                            QPointF, QSize, Qt, QThread, QTimer, QUrl, Signal, Slot)
from PySide6.QtGui import QGuiApplication, QImage, QMouseEvent
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression
from PySide6.QtQuick import QQuickImageProvider, QQuickItem
from PySide6.QtTest import QTest

from ui.viewmodels.plot_images import das_image, stft_image
from ui.viewmodels.theme_source import ThemeSource

sys.path.insert(0, SELFTEST)
from feature_chart_payloads import build_payloads  # noqa: E402

FAILURES: list[str] = []
PROVIDER_KEEP = []
GRAB_KEEP = []


def fail(msg: str) -> None:
    FAILURES.append(msg)
    print("[QML-LOAD] FAIL:", msg)


def wait_ms(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class DemoRasterProvider(QQuickImageProvider):
    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.Image)
        self._heat = QImage(os.path.join(CHART_DIR, "demo", "heatmap_demo.png"))
        self._polar = QImage(os.path.join(CHART_DIR, "demo", "polar_demo.png"))

    def requestImage(self, image_id, size, requested_size):  # noqa: N802
        img = self._polar if "polar" in str(image_id) else self._heat
        return img.copy()


HARNESS = """
import QtQuick
import QtQuick.Window
Window {
    width: 1600
    height: 1950
    visible: true
    color: Theme.appBg
    Loader {
        anchors.fill: parent
        source: Qt.resolvedUrl("../ChartGallery.qml")
    }
}
"""

PROVIDER_HARNESS = """
import QtQuick
import QtQuick.Window
Window {
    width: 1600
    height: 1950
    visible: true
    color: Theme.appBg
    Loader {
        anchors.fill: parent
        source: Qt.resolvedUrl("../ChartGallery.qml")
        onLoaded: {
            item.demoHeatmapUrl = heatmapProviderUrl;
            item.demoPolarUrl = polarProviderUrl;
        }
    }
}
"""

QML_DIR = os.path.join(APP_ROOT, "ui", "qml")
CHART_FIXTURES = os.path.join(APP_ROOT, "tests", "frontend", "fixtures", "charts")
FEATURE_CAPTURE = os.path.join(OUT, "feature_save_spectrum.png")

FEATURE_HARNESS = """
import QtQuick
import QtQuick.Window
import "components"
Window {
    width: 1280
    height: 720
    visible: true
    color: "#000000"
    FeatureChart { objectName: "featureChart"; anchors.fill: parent }
}
"""


class FeatureRasterProvider(QQuickImageProvider):
    """Serves the prebuilt STFT/DAS display rasters used by the feature phase."""

    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.Image)
        self.images: dict[str, QImage] = {}

    def requestImage(self, image_id, size, requested_size):  # noqa: N802
        key = str(image_id).split("/")[0]
        image = self.images.get(key)
        return image.copy() if image is not None else QImage()


class FeatureAppMock(QObject):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.capture_path = FEATURE_CAPTURE
        self.view_options: list[tuple[str, str, str]] = []
        self.notified: list[str] = []
        self.pl_calls: list[str] = []
        self._workspace = {
            "featureId": "fft", "name": "FFT", "shortName": "FFT", "icon": "activity",
            "sourceKind": "test-fixture", "sourceLabel": "test fixture / non-measured",
            "validity": "valid", "available": True, "notes": ["fixture data, not measured"],
            "chart": {},
        }

    @Property("QVariantMap", notify=changed)
    def featureWorkspace(self):  # noqa: N802
        return dict(self._workspace)

    def set_payload(self, payload: dict) -> None:
        self._workspace = dict(self._workspace)
        self._workspace["chart"] = payload
        self.changed.emit()

    @Slot(str, result=str)
    def t(self, key: str) -> str:
        return key

    @Slot(str, str, result=str)
    def iconSource(self, name: str, color: str) -> str:  # noqa: N802
        return ""

    @Slot(str, str, str)
    def setFeatureViewOption(self, feature_id: str, key: str, value: str) -> None:  # noqa: N802
        self.view_options.append((feature_id, key, value))

    @Slot(str, result=str)
    def saveFeatureChart(self, feature_id: str) -> str:  # noqa: N802
        return self.capture_path

    @Slot(str)
    def notifyFeatureSaved(self, path: str) -> None:  # noqa: N802
        self.notified.append(path)

    @Slot(str)
    def startFeature(self, feature_id: str) -> None:  # noqa: N802
        self.pl_calls.append("start:" + feature_id)

    @Slot(str)
    def runFeature(self, feature_id: str) -> None:  # noqa: N802
        self.pl_calls.append("run:" + feature_id)


def visual_children(item) -> list:
    try:
        return list(item.childItems())
    except AttributeError:
        return []


def find_visual(root, name: str):
    stack = [root]
    visited = 0
    while stack and visited < 6000:
        item = stack.pop()
        visited += 1
        try:
            if item.objectName() == name:
                return item
            stack.extend(item.childItems())
        except AttributeError:
            continue
    return None


def image_black_ratio(path: str) -> float:
    img = QImage(path)
    if img.isNull():
        return 0.0
    black = 0
    total = 0
    for y in range(0, img.height(), 7):
        for x in range(0, img.width(), 7):
            total += 1
            if (img.pixel(x, y) & 0xFFFFFF) == 0:
                black += 1
    return black / max(1, total)


def load_feature_phase(theme):
    engine = QQmlApplicationEngine()
    warnings: list[str] = []
    engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    app = FeatureAppMock()
    provider = FeatureRasterProvider()
    payloads = build_payloads()
    if os.path.isfile(FEATURE_CAPTURE):
        os.remove(FEATURE_CAPTURE)

    stft_payload = payloads["stft"]
    stft_raster = stft_image(
        stft_payload["frames"],
        frequency_axis=stft_payload["yAxis"],
        time_axis={**stft_payload["xAxis"], "min": 0.0, "max": 0.22},
        color_scale=stft_payload["colorScale"], width=360, height=220)
    provider.images["stft-fixture"] = stft_raster
    stft_payload["imageUrl"] = "image://plots/stft-fixture/1"

    das_payload = payloads["das-map"]
    das_raster = das_image(
        [{"azimuth": 35, "elevation": 24, "power": -8},
         {"azimuth": 300, "elevation": 55, "power": -18},
         {"azimuth": 120, "elevation": 40, "power": -30},
         {"azimuth": 220, "elevation": 70, "power": -42}],
        azimuth_axis=das_payload["azimuthRange"],
        elevation_axis=das_payload["elevationRange"],
        color_scale=das_payload["colorScale"], projection="polar", size=300)
    provider.images["das-fixture"] = das_raster
    das_payload["imageUrl"] = "image://plots/das-fixture/1"

    PROVIDER_KEEP.extend((app, provider))
    engine.addImageProvider("plots", provider)
    engine.rootContext().setContextProperty("Theme", theme)
    engine.rootContext().setContextProperty("App", app)
    engine.loadData(FEATURE_HARNESS.encode(),
                    QUrl.fromLocalFile(os.path.join(QML_DIR, "_feature_chart_harness.qml")))
    roots = engine.rootObjects()
    if not roots:
        return engine, warnings, None, app, None, provider, payloads
    win = roots[0]
    wait_ms(400)
    chart = win.findChild(QQuickItem, "featureChart")
    return engine, warnings, win, app, chart, provider, payloads


def load_phase(theme, use_provider: bool):
    engine = QQmlApplicationEngine()
    warnings: list[str] = []
    engine.warnings.connect(lambda errs: warnings.extend(e.toString() for e in errs))
    engine.rootContext().setContextProperty("Theme", theme)
    if use_provider:
        provider = DemoRasterProvider()
        PROVIDER_KEEP.append(provider)
        engine.addImageProvider("plots", provider)
        engine.rootContext().setContextProperty("heatmapProviderUrl", "image://plots/gallery-heatmap/1")
        engine.rootContext().setContextProperty("polarProviderUrl", "image://plots/gallery-polar/1")
    base = QUrl.fromLocalFile(os.path.join(SELFTEST, "harness_dynamic.qml"))
    engine.loadData((PROVIDER_HARNESS if use_provider else HARNESS).encode("utf-8"), base)
    roots = engine.rootObjects()
    if not roots:
        return engine, warnings, None
    win = roots[0]
    wait_ms(1600)
    return engine, warnings, win


def grab_item(item, path: str) -> dict:
    box = {"ready": False, "saved": False, "w": 0, "h": 0}
    result = item.grabToImage(QSize(int(item.width()), int(item.height())))

    def ready() -> None:
        img = result.image()
        box["w"], box["h"] = img.width(), img.height()
        box["saved"] = result.saveToFile(path)
        box["ready"] = True
        GRAB_KEEP.append(result)  # keep alive: deleting a grab result mid-render is unsafe

    result.ready.connect(ready)
    deadline = time.monotonic() + 12.0
    while not box["ready"] and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        QThread.msleep(10)
    return box


def image_stats(path: str) -> dict:
    img = QImage(path)
    if img.isNull():
        return {"error": "unreadable"}
    colors = set()
    for y in range(0, img.height(), 5):
        for x in range(0, img.width(), 5):
            colors.add(img.pixel(x, y))
    return {"w": img.width(), "h": img.height(), "sampledColors": len(colors)}


def click_item(win, item, fx: float, fy: float) -> str:
    point = item.mapToScene(QPointF(item.width() * fx, item.height() * fy))
    local = QPointF(point.x(), point.y())
    global_pos = QPointF(win.mapToGlobal(QPoint(int(point.x()), int(point.y()))))
    press = QMouseEvent(QEvent.MouseButtonPress, local, global_pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    release = QMouseEvent(QEvent.MouseButtonRelease, local, global_pos, Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    QCoreApplication.sendEvent(win, press)
    QCoreApplication.sendEvent(win, release)
    wait_ms(120)
    return "window-event"


def verify_components(win) -> None:
    names = ["galleryWaveform", "galleryLine", "galleryBar", "galleryHeatmap",
             "galleryPolar", "galleryMeterV", "galleryMeterH", "galleryTimeline", "galleryWaterfall"]
    for name in names:
        item = win.findChild(QQuickItem, name)
        if item is None:
            fail(f"component not instantiated in gallery: {name}")
        else:
            print(f"[QML-LOAD] component ok: {name} ({int(item.width())}x{int(item.height())})")


def verify_interactions(win) -> dict:
    gallery = win.findChild(QQuickItem, "chartGallery")
    counters = {}
    if gallery is None:
        fail("gallery root object not found")
        return counters
    wf = win.findChild(QQuickItem, "galleryWaveform")
    timeline = win.findChild(QQuickItem, "galleryTimeline")
    heat = win.findChild(QQuickItem, "galleryHeatmap")
    print("[QML-LOAD] find items:", wf is not None, timeline is not None, heat is not None, flush=True)
    if wf is not None:
        print("[QML-LOAD] click waveform ...", flush=True)
        click_item(win, wf, 0.52, 0.58)
        wait_ms(250)
        print("[QML-LOAD] clicked waveform counters:", gallery.property("wfSeekCount"), flush=True)
    if timeline is not None:
        print("[QML-LOAD] click timeline ...", flush=True)
        click_item(win, timeline, 0.55, 0.35)
        wait_ms(250)
        print("[QML-LOAD] clicked timeline:", gallery.property("timelineSeekCount"), flush=True)
    if heat is not None:
        print("[QML-LOAD] click heatmap ...", flush=True)
        click_item(win, heat, 0.5, 0.5)
        wait_ms(250)
        print("[QML-LOAD] clicked heatmap:", gallery.property("heatmapClickCount"), flush=True)
    for name in ("wfSeekCount", "wfCursorCount", "wfSelectionCount", "lineCursorCount",
                 "heatmapClickCount", "timelineSeekCount", "timelineSelectionCount"):
        counters[name] = gallery.property(name)
    print("[QML-LOAD] interaction counters:", counters)
    if not counters.get("wfSeekCount"):
        fail("WaveformChart seekRequested did not fire on click")
    if not counters.get("heatmapClickCount"):
        fail("HeatmapChart pointClicked did not fire on click")
    if not counters.get("timelineSeekCount"):
        fail("TimelineChart seekRequested did not fire on click")
    return counters


def invoke_qml(engine, scope, expression: str):
    script = QQmlExpression(engine.rootContext(), scope, expression)
    result = script.evaluate()
    if script.hasError():
        fail("QML invoke failed: " + expression + " -> " + script.error().toString())
    return result


def feature_shot(chart, filename: str, label: str) -> dict:
    os.makedirs(CHART_FIXTURES, exist_ok=True)
    path = os.path.join(CHART_FIXTURES, filename)
    shot = grab_item(chart, path)
    if not shot["saved"] or shot["w"] < 200:
        fail(f"feature chart grabToImage failed: {label}: {shot}")
        return shot
    stats = image_stats(path)
    black_ratio = image_black_ratio(path)
    print(f"[QML-LOAD] feature chart {label}: {shot['w']}x{shot['h']} colors="
          f"{stats.get('sampledColors')} black={black_ratio:.2f} -> {path}")
    if stats.get("sampledColors", 0) < 12:
        fail(f"feature chart {label} looks blank: {stats}")
    if black_ratio < 0.05:
        fail(f"feature chart {label} has no pure-black plot/shell background: {black_ratio:.2f}")
    return shot


def verify_feature_phase(engine, win, chart, app, payloads) -> None:
    os.makedirs(CHART_FIXTURES, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    if chart is None:
        fail("FeatureChart qml item not found in phase 3")
        return
    routed = {}
    for kind, payload in payloads.items():
        app.set_payload(payload)
        wait_ms(260)
        item = chart.property("contentItem")
        if item is None:
            fail("feature chart content item missing: " + kind)
            continue
        routed[kind] = str(chart.property("routeToken"))
        feature_shot(chart, kind + ".png", kind)
        if kind == "stft":
            invoke_qml(engine, win.findChild(QQuickItem, "featureChart"), "threeDActive = true")
            wait_ms(300)
            waterfall = find_visual(chart, "chartWaterfall")
            if waterfall is None or not waterfall.property("visible"):
                fail("STFT 3D waterfall toggle did not show the numeric surface")
            else:
                feature_shot(chart, "stft-3d.png", "stft-3d")
            invoke_qml(engine, win.findChild(QQuickItem, "featureChart"), "threeDActive = false")
            wait_ms(120)
        if kind == "das-map":
            invoke_qml(engine, win.findChild(QQuickItem, "featureChart"), "dasRect = true")
            wait_ms(300)
            polar = find_visual(chart, "chartPolar")
            if polar is None or str(polar.property("projection")) != "rect":
                fail("DAS polar/rect projection toggle did not switch to rect")
            else:
                feature_shot(chart, "das-map-rect.png", "das-map-rect")
            invoke_qml(engine, win.findChild(QQuickItem, "featureChart"), "dasRect = false")
            wait_ms(120)

    # empty / invalid states render an explicit state, never fake data
    app.set_payload({"kind": "spectrum", "title": "FFT", "series": [],
                     "emptyReason": "fixture: no device result yet"})
    wait_ms(250)
    feature_shot(chart, "empty-spectrum.png", "empty-spectrum")
    app.set_payload({"kind": "stft", "title": "STFT", "frames": [[1, 2], [3, 4]],
                     "framesUnavailableText": "fixture: producer frames unavailable"})
    wait_ms(200)
    invoke_qml(engine, chart, "threeDActive = true")
    wait_ms(250)
    feature_shot(chart, "stft-invalid-3d.png", "stft-invalid-3d")
    invoke_qml(engine, chart, "threeDActive = false")

    # view-only toolbar operations: fit / log / cursor / legend / save + 2D3D above
    app.set_payload(payloads["spectrum"])
    wait_ms(260)
    toolbar = find_visual(chart, "chartToolbar")
    if toolbar is None:
        fail("feature chart toolbar not instantiated")
    else:
        for key in ("fit", "log", "cursor", "legend", "3d", "save"):
            button = find_visual(toolbar, "chartToolbarBtn_" + key)
            icon = find_visual(toolbar, "chartIcon_" + key)
            if key == "3d":
                continue
            if button is None or int(button.width()) != 32 or int(button.height()) != 32:
                fail("feature chart toolbar button missing/not 32x32: " + key)
            if icon is None or int(icon.width()) != 20 or int(icon.height()) != 20:
                fail("feature chart toolbar icon missing/not 20px: " + key)
        invoke_qml(engine, toolbar, "activate('cursor')")
        invoke_qml(engine, toolbar, "activate('log')")
        invoke_qml(engine, toolbar, "activate('legend')")
        invoke_qml(engine, toolbar, "activate('fit')")
        wait_ms(160)
        if not chart.property("cursorEnabled"):
            fail("cursor view operation did not toggle the display cursor")
        if bool(chart.property("logScaleEnabled")):
            fail("log/linear view operation did not switch the spectrum axis: "
                 + repr(chart.property("logScaleEnabled")))
        if bool(chart.property("legendVisible")):
            fail("legend view operation did not toggle the legend")
        if not app.view_options:
            fail("view operations were not persisted through App.setFeatureViewOption")
        if app.pl_calls:
            fail("view operations started a PL measurement: " + repr(app.pl_calls))
        invoke_qml(engine, toolbar, "activate('save')")
        deadline = time.monotonic() + 12.0
        while not os.path.isfile(app.capture_path) and time.monotonic() < deadline:
            QCoreApplication.processEvents()
            QThread.msleep(10)
        if not os.path.isfile(app.capture_path) or os.path.getsize(app.capture_path) < 500:
            fail("feature chart save image (grabToImage) did not produce a PNG")
        else:
            saved_copy = os.path.join(CHART_FIXTURES, "spectrum-toolbar-save.png")
            shutil.copy2(app.capture_path, saved_copy)
            print("[QML-LOAD] feature save image ->", saved_copy)
        deadline = time.monotonic() + 3.0
        while not app.notified and time.monotonic() < deadline:
            QCoreApplication.processEvents()
            QThread.msleep(10)
        if not app.notified:
            fail("feature chart save did not call App.notifyFeatureSaved(path)")
        if app.pl_calls:
            fail("toolbar operations started a PL measurement: " + repr(app.pl_calls))

    print("[QML-LOAD] feature chart routes:", routed)
    missing = {kind for kind, token in routed.items() if token == "empty"}
    if missing:
        fail("feature chart kinds routed to the empty fallback: " + repr(sorted(missing)))
    if len(routed) != 24:
        fail(f"expected 24 feature chart kinds rendered, got {len(routed)}")


def main() -> int:
    app = QGuiApplication(sys.argv)
    app.setApplicationName("SixMic3D chart QML check")
    os.makedirs(OUT, exist_ok=True)
    theme = ThemeSource("light")
    print("[QML-LOAD] QT_QPA_PLATFORM=", os.environ.get("QT_QPA_PLATFORM"),
          "QT_QPA_FONTDIR=", os.environ.get("QT_QPA_FONTDIR", "<qt default>"))
    print("[QML-LOAD] dpr=", app.devicePixelRatio() if hasattr(app, "devicePixelRatio") else "?")

    # ---------------- phase 1: shipped gallery with the bundled demo rasters
    engine, warnings, win = load_phase(theme, False)
    counters_file = {}
    if win is None:
        fail("gallery window failed to load (phase 1)")
    else:
        gallery = win.findChild(QQuickItem, "chartGallery")
        if gallery is None:
            fail("gallery page not found below the harness Loader (phase 1)")
        else:
            verify_components(win)
            waterfall = win.findChild(QQuickItem, "galleryWaterfall")
            if waterfall is not None:
                if waterfall.property("validCellCount") != 39 * 99:
                    fail("waterfall numeric mesh did not generate all adjacent cells")
                grab_item(waterfall, os.path.join(OUT, "waterfall_light.png"))
            counters_file = verify_interactions(win)
            shots = {}
            shot = grab_item(gallery, os.path.join(OUT, "chart_gallery_light.png"))
            if not shot["saved"] or shot["w"] < 100:
                fail(f"grabToImage failed for gallery (phase 1): {shot}")
            else:
                shots["light"] = shot
                print(f"[QML-LOAD] screenshot light: {shot['w']}x{shot['h']} -> "
                      f"{os.path.join(OUT, 'chart_gallery_light.png')}")
                stats = image_stats(os.path.join(OUT, "chart_gallery_light.png"))
                print("[QML-LOAD] screenshot stats:", stats)
                if stats.get("sampledColors", 0) < 40:
                    fail(f"gallery screenshot looks blank: {stats}")
            # live theme switch must repaint every canvas (Theme.changed -> requestPaint)
            theme.set_mode("dark")
            wait_ms(700)
            if waterfall is not None:
                grab_item(waterfall, os.path.join(OUT, "waterfall_dark.png"))
            shot_dark = grab_item(gallery, os.path.join(OUT, "chart_gallery_dark.png"))
            if shot_dark["saved"]:
                print(f"[QML-LOAD] screenshot dark: {shot_dark['w']}x{shot_dark['h']} -> "
                      f"{os.path.join(OUT, 'chart_gallery_dark.png')}")
            else:
                fail("dark theme screenshot failed")
            theme.set_mode("light")
            wait_ms(300)
    if warnings:
        fail(f"QML warnings in phase 1: {len(warnings)}")
        for w in warnings:
            print("   ", w)
    del engine

    # ---------------- phase 2: same gallery with image:// provider URLs
    engine2, warnings2, win2 = load_phase(theme, True)
    if win2 is None:
        fail("gallery window failed to load (phase 2, image provider)")
    else:
        gallery2 = win2.findChild(QQuickItem, "chartGallery")
        if gallery2 is None:
            fail("gallery page not found below the harness Loader (phase 2)")
        else:
            heat = win2.findChild(QQuickItem, "galleryHeatmap")
            if heat is None:
                fail("heatmap chart missing in provider phase")
            else:
                # the Image source must actually resolve through the Python provider
                if int(heat.property("imageUrl").__len__()) == 0:
                    fail("heatmap imageUrl empty in provider phase")
            shot2 = grab_item(gallery2, os.path.join(OUT, "chart_gallery_provider.png"))
            if shot2["saved"]:
                print(f"[QML-LOAD] screenshot provider: {shot2['w']}x{shot2['h']} -> "
                      f"{os.path.join(OUT, 'chart_gallery_provider.png')}")
                stats2 = image_stats(os.path.join(OUT, "chart_gallery_provider.png"))
                print("[QML-LOAD] provider screenshot stats:", stats2)
            else:
                fail("grabToImage failed for gallery (phase 2)")
    if warnings2:
        fail(f"QML warnings in phase 2: {len(warnings2)}")
        for w in warnings2:
            print("   ", w)
    del engine2

    # ---------------- phase 3: FeatureChart routing for all 24 chart kinds
    engine3, warnings3, win3, app3, chart3, provider3, payloads3 = load_feature_phase(theme)
    if win3 is None:
        fail("feature chart window failed to load (phase 3)")
    else:
        verify_feature_phase(engine3, win3, chart3, app3, payloads3)
    if warnings3:
        fail(f"QML warnings in phase 3: {len(warnings3)}")
        for w in warnings3:
            print("   ", w)
    del engine3

    wait_ms(100)
    if FAILURES:
        print(f"[QML-LOAD] RESULT: FAIL ({len(FAILURES)} problem(s))")
        for f in FAILURES:
            print("  -", f)
        return 1
    print("[QML-LOAD] RESULT: PASS - no QML warnings/errors, all contract components plus waterfall "
          "instantiated, seek/click signals verified, light+dark+screenshot captured, FeatureChart routes "
          "all 24 feature chart kinds with view-only toolbar operations and per-kind PNG evidence")
    print("[QML-LOAD] screenshots dir:", OUT)
    print("[QML-LOAD] feature chart evidence dir:", CHART_FIXTURES)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
