"""Numeric surface integrity and constrained common-component layout regression."""
from __future__ import annotations

from pathlib import Path
import json
import os

os.environ.setdefault('QT_QUICK_CONTROLS_STYLE', 'Basic')

import pytest
from PySide6.QtCore import (QCoreApplication, QEvent, QObject, Property, QPoint, QPointF,
                            QSize, Qt, QUrl, Signal, Slot)
from PySide6.QtGui import QMouseEvent
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression
from PySide6.QtQuick import QQuickItem

from conftest import pump
from ui.viewmodels.theme_source import ThemeSource

QML = Path(__file__).resolve().parents[2] / 'ui/qml'


class AppLabels(QObject):
    @Slot(str, str, result=str)
    def iconSource(self, name, color):
        return ''

    @Slot(str, result=str)
    def t(self, key):
        return key

    pageTitle = Property(str, lambda self: '声学频谱分析 / Acoustic frequency analysis' * 3, constant=True)
    pageSubtitle = Property(str, lambda self: '', constant=True)
    dataSource = Property(str, lambda self: 'none', constant=True)
    dataSourceLabel = Property(str, lambda self: '未连接 / Disconnected', constant=True)


@pytest.fixture
def scene(qapp):
    # Configure the same process-wide style as the production entry point before
    # this component-only harness loads Controls; later shell tests reuse it.
    import main as appmain
    if not appmain._STYLE_CONFIGURED:
        from PySide6.QtQuickControls2 import QQuickStyle
        QQuickStyle.setStyle('Basic')
        appmain._STYLE_CONFIGURED = True
    engines = []
    keep = []

    def load(content):
        engine = QQmlApplicationEngine()
        theme, labels = ThemeSource('dark'), AppLabels()
        keep.extend((theme, labels))
        engine.rootContext().setContextProperty('Theme', theme)
        engine.rootContext().setContextProperty('App', labels)
        warnings = []
        engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
        engine.loadData(('import QtQuick\nimport QtQuick.Layouts\nimport "components"\n'
                         'import "components/charts"\nWindow { width: 900; height: 540; visible: true; '
                         + content + '}').encode(), QUrl.fromLocalFile(str(QML/'test-presentation.qml')))
        engines.append(engine)
        assert engine.rootObjects(), warnings
        pump(qapp, 0.1)
        return engine, engine.rootObjects()[0], warnings

    yield load
    for engine in engines:
        for window in engine.rootObjects():
            window.close()
        engine.deleteLater()
    pump(qapp, 0.05)


def assign(engine, obj, expression):
    js = QQmlExpression(engine.rootContext(), obj, expression)
    js.evaluate()
    assert not js.hasError(), js.error().toString()


def test_surface_preserves_gaps_and_matches_frequency_bins(scene, qapp):
    engine, win, warnings = scene('''WaterfallChart { objectName: "surface"; anchors.fill: parent
        frequencyAxis: ({min:20, max:200, scale:"log"})
        timeAxis: ({min:0, max:0.3}) }''')
    surface = win.findChild(QQuickItem, 'surface')
    assert surface.property('validCellCount') == 0
    frames = [{'time': r * 0.1, 'points': [[20, -60], [100, -40], [200, -50]]} for r in range(4)]
    assign(engine, surface, 'frames = '+json.dumps(frames))
    assert surface.property('validCellCount') == 6  # Includes floating-point 0.3 endpoint.
    frames[1]['points'][1][1] = None
    assign(engine, surface, 'frames = '+json.dumps(frames))
    assert surface.property('validCellCount') == 2  # No faces cross a missing sample.
    frames[1]['points'][1] = [110, -40]
    assign(engine, surface, 'frames = '+json.dumps(frames))
    assert surface.property('validCellCount') == 2  # No invented frequency interpolation.
    assign(engine, surface, 'frames = []')
    pump(qapp, 0.1)
    assert surface.property('validCellCount') == 0
    assert warnings == []


def test_surface_work_budget_and_invalid_domains(scene):
    engine, win, warnings = scene('WaterfallChart { objectName: "surface"; anchors.fill: parent }')
    surface = win.findChild(QQuickItem, 'surface')
    frames = [{'time': r / 47, 'points': [[20 * 1000**(b/127), -50] for b in range(128)]} for r in range(48)]
    assign(engine, surface, 'frames = '+json.dumps(frames))
    assert surface.property('validCellCount') == 47 * 127
    assign(engine, surface, 'frames = '+json.dumps(frames + [frames[-1]]))
    assert surface.property('validCellCount') == 0
    assign(engine, surface, 'frames = '+json.dumps(frames[:2]))
    assign(engine, surface, 'frequencyAxis = ({min:0, max:20000, scale:"log"})')
    assert surface.property('validCellCount') >= 0  # Log guard never evaluates zero.
    assert warnings == []


def test_step_trace_preserves_explicit_db_zoom(scene):
    engine, win, warnings = scene('''BarChart { objectName: "bands"; anchors.fill: parent
        displayMode: "steps"; yAxis: ({min:-80, max:-20, scale:"linear"})
        categories: [{label:"125",value:-40,valid:true}, {label:"250",value:-50,valid:true}]
    }''')
    bands = win.findChild(QQuickItem, 'bands')
    query = QQmlExpression(engine.rootContext(), bands, 'resolvedAxis([-40,-50],5).max')
    assert query.evaluate()[0] == -20
    assert warnings == []


def test_narrow_log_axis_keeps_frequency_decades(qapp):
    from PySide6.QtQml import QJSEngine
    engine = QJSEngine()
    source = (QML / 'components/charts/ChartUtil.js').read_text(encoding='utf-8')
    result = engine.evaluate(source.replace('.pragma library', '') + '\nlogTicks(20,20000,3).ticks;')
    assert not result.isError()
    assert result.toVariant() == [20,100,1000,10000,20000]


@pytest.mark.parametrize('width', [420, 640, 900])
def test_titles_actions_and_statistics_stay_inside_layout(scene, qapp, width):
    engine, win, warnings = scene('''ColumnLayout {
        width: parent.width; spacing: 10
        PageHeader {
            objectName: "header"; Layout.fillWidth: true
            ChoiceChips { options: [{value:1,label:"Logarithmic frequency"}, {value:2,label:"Linear"}] }
            ChoiceChips { options: [{value:1,label:"Frequency resolution"}, {value:2,label:"Window function"}] }
        }
        RowLayout {
            Layout.fillWidth: true
            StatTile { objectName: "stat"; Layout.fillWidth: true; label:"Source"; value:"Very long device source name that must elide" }
            StatTile { Layout.fillWidth: true; label:"Level"; value:"-32.5"; unit:"dBFS" }
        }
        RowLayout {
            Layout.fillWidth: true
            SectionTitle { objectName: "section"; text:"Frequency response and accumulated spectral decay with a long title" }
            SourceBadge {}
        }
    }''')
    win.setWidth(width)
    pump(qapp, 0.15)
    title = win.findChild(QQuickItem, 'pageHeaderTitle')
    actions = win.findChild(QQuickItem, 'pageHeaderActions')
    assert 0 < title.width() <= width
    if width < 760:
        assert actions.y() >= title.parentItem().height()
    if width == 420:
        assert actions.childItems()[1].y() > actions.childItems()[0].y()
    for name in ('header', 'stat', 'section'):
        item = win.findChild(QQuickItem, name)
        assert item.width() <= width + 1, (name, item.width(), width)
        for child in item.childItems():
            if child.isVisible():
                assert child.x() >= -1
                assert child.x() + child.width() <= item.width() + 1, (name, child.x(), child.width(), item.width())
    assert warnings == []


# ============================================================================
# FeatureChart payload routing / presentation contract (feature charts)
# ============================================================================
import re
import time
from pathlib import Path as _Path

APP_ROOT = QML.parents[1]
SPEC_PATH = APP_ROOT / "ui/config/feature_view_spec.json"
CHARTS_DIR = QML / "components/charts"

FEATURE_HARNESS = (
    'import QtQuick\nimport QtQuick.Window\nimport "components"\n'
    'Window { width: 1120; height: 640; visible: true; color: "#000000"\n'
    '    FeatureChart { objectName: "featureChart"; anchors.fill: parent } }'
)

FEATURE_WORKSPACE_HARNESS = (
    'import QtQuick\nimport QtQuick.Window\nimport "components"\n'
    'Window { width: 1120; height: 640; visible: true; color: "#000000"\n'
    '    FeatureWorkspace { objectName: "featureWorkspace"; anchors.fill: parent } }'
)


class FeatureApp(QObject):
    """Minimal AppViewModel surface for FeatureChart; PL slots record calls."""

    changed = Signal()

    def __init__(self, capture_path: str) -> None:
        super().__init__()
        self.capture_path = capture_path
        self.view_options: list[tuple[str, str, str]] = []
        self.notified: list[str] = []
        self.pl_calls: list[str] = []
        self._workspace: dict = {
            "featureId": "fft", "name": "FFT", "shortName": "FFT", "icon": "activity",
            "sourceKind": "test-fixture", "sourceLabel": "test fixture / non-measured",
            "validity": "valid", "available": True, "notes": ["fixture source"],
            "chart": {},
        }

    @Property("QVariantMap", notify=changed)
    def featureWorkspace(self) -> dict:  # noqa: N802
        return dict(self._workspace)

    def set_chart(self, payload: dict) -> None:
        self._workspace = dict(self._workspace)
        self._workspace["chart"] = payload
        self.changed.emit()

    def set_workspace(self, **updates) -> None:
        self._workspace = dict(self._workspace)
        self._workspace.update(updates)
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

    # Minimal page surface used by FeatureWorkspace (status row, language, tone).
    language = Property(str, lambda self: "en", constant=True)
    connectionState = Property(str, lambda self: "disconnected", constant=True)
    exportBusy = Property(bool, lambda self: False, constant=True)

    @Property("QVariantMap", constant=True)
    def featureStatus(self) -> dict:  # noqa: N802
        return {}


def _walk_visual(item):
    try:
        children = list(item.childItems())
    except AttributeError:
        return
    for child in children:
        yield child
        yield from _walk_visual(child)


def find_visual(root, name, limit=4000):
    if root is None:
        return None
    try:
        if root.objectName() == name:
            return root
    except AttributeError:
        pass
    for index, child in enumerate(_walk_visual(root)):
        if index > limit:
            return None
        if child.objectName() == name:
            return child
    return None


def qv(value):
    """Convert a QML JS value (QJSValue) into plain Python containers."""
    if hasattr(value, "toVariant"):
        return value.toVariant()
    return value


def find_visual_all(root, name):
    found = []
    if root is None:
        return found
    for child in _walk_visual(root):
        if child.objectName() == name:
            found.append(child)
    return found


class FeatureScene:
    def __init__(self, engine, window, chart, app, warnings):
        self.engine = engine
        self.window = window
        self.chart = chart
        self.app = app
        self.warnings = warnings

    def set_payload(self, payload, qapp, wait=0.12):
        self.app.set_chart(payload)
        pump(qapp, wait)
        return self.item()

    def item(self):
        return self.chart.property("contentItem")

    def find(self, name):
        found = find_visual(self.chart, name)
        if found is None:
            found = self.window.findChild(QQuickItem, name)
        return found

    def invoke(self, expression, scope=None):
        js = QQmlExpression(self.engine.rootContext(), scope or self.chart, expression)
        result = js.evaluate()
        assert not js.hasError(), js.error().toString()
        return result


@pytest.fixture
def feature_scene(qapp, tmp_path):
    engines = []
    keep = []

    def load(payload=None, workspace=None):
        import main as appmain
        if not appmain._STYLE_CONFIGURED:
            from PySide6.QtQuickControls2 import QQuickStyle
            QQuickStyle.setStyle("Basic")
            appmain._STYLE_CONFIGURED = True
        engine = QQmlApplicationEngine()
        app = FeatureApp(str(tmp_path / "chart-capture.png"))
        if workspace:
            app.set_workspace(**workspace)
        if payload is not None:
            app.set_chart(payload)
        theme = ThemeSource("dark")
        keep.extend((app, theme))
        engine.rootContext().setContextProperty("Theme", theme)
        engine.rootContext().setContextProperty("App", app)
        warnings: list[str] = []
        engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
        engine.loadData(FEATURE_HARNESS.encode(),
                        QUrl.fromLocalFile(str(QML / "test-featurechart.qml")))
        assert engine.rootObjects(), warnings
        engines.append(engine)
        pump(qapp, 0.15)
        window = engine.rootObjects()[0]
        chart = window.findChild(QQuickItem, "featureChart")
        assert chart is not None, warnings
        return FeatureScene(engine, window, chart, app, warnings)

    yield load
    for engine in engines:
        for window in engine.rootObjects():
            window.close()
        engine.deleteLater()
    pump(qapp, 0.05)


class FeatureWorkspaceScene:
    def __init__(self, engine, window, workspace, app, warnings):
        self.engine = engine
        self.window = window
        self.workspace = workspace
        self.app = app
        self.warnings = warnings

    def find(self, name):
        found = find_visual(self.workspace, name)
        if found is None:
            found = self.window.findChild(QQuickItem, name)
        return found

    def invoke(self, expression, scope=None):
        js = QQmlExpression(self.engine.rootContext(), scope or self.workspace, expression)
        result = js.evaluate()
        assert not js.hasError(), js.error().toString()
        return result


@pytest.fixture
def feature_workspace_scene(qapp, tmp_path):
    engines = []
    keep = []

    def load(workspace=None):
        import main as appmain
        if not appmain._STYLE_CONFIGURED:
            from PySide6.QtQuickControls2 import QQuickStyle
            QQuickStyle.setStyle("Basic")
            appmain._STYLE_CONFIGURED = True
        engine = QQmlApplicationEngine()
        app = FeatureApp(str(tmp_path / "workspace-capture.png"))
        if workspace:
            app.set_workspace(**workspace)
        theme = ThemeSource("dark")
        keep.extend((app, theme))
        engine.rootContext().setContextProperty("Theme", theme)
        engine.rootContext().setContextProperty("App", app)
        warnings: list[str] = []
        engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
        engine.loadData(FEATURE_WORKSPACE_HARNESS.encode(),
                        QUrl.fromLocalFile(str(QML / "test-featureworkspace.qml")))
        assert engine.rootObjects(), warnings
        engines.append(engine)
        pump(qapp, 0.25)
        window = engine.rootObjects()[0]
        item = window.findChild(QQuickItem, "featureWorkspace")
        assert item is not None, warnings
        return FeatureWorkspaceScene(engine, window, item, app, warnings)

    yield load
    for engine in engines:
        for window in engine.rootObjects():
            window.close()
        engine.deleteLater()
    pump(qapp, 0.05)


def _stipa_workspace(**updates):
    """Workspace payload shaped like FeatureRuntime.workspace() for STIPA."""
    workspace = {
        "open": True,
        "featureId": "stipa_experimental",
        "available": True,
        "state": "running",
        "hasResult": False,
        "resultValid": True,
        "message": "computing",
        "measurementMode": "complete",
        "measurementProgress": {"completedStages": 34, "totalStages": 101,
                                "currentStageIndex": 37, "phase": "computing"},
        "chart": FEATURE_PAYLOADS["stipa"],
        "flow": {"actions": [], "steps": [], "confirmations": []},
        "references": {"hasReference": True},
        "freshness": {}, "notes": [], "variants": [],
    }
    workspace.update(updates)
    return workspace


def _spectrum_payload():
    return {
        "kind": "spectrum", "title": "FFT", "subtitle": "test fixture",
        "chartRevision": 1,
        "xAxis": {"min": 20, "max": 20000, "scale": "log", "label": "Frequency", "unit": "Hz"},
        "yAxis": {"min": -120, "max": 0, "scale": "linear", "label": "Level", "unit": "dBFS"},
        "series": [{"name": "CH1", "color": "#B9E7ED",
                    "points": [[20, -80], [100, -60], [1000, -40], [10000, -70], [20000, -90]]}],
        "markers": [{"x": 1000, "y": -40, "label": "peak", "kind": "peak"}],
        "referenceLines": [{"y": -60, "label": "limit", "dashed": True}],
    }


def _line_payload(kind, **extra):
    payload = {
        "kind": kind, "title": kind, "chartRevision": 1,
        "xAxis": {"min": 0, "max": 2048, "scale": "linear", "label": "Lag", "unit": "samples"},
        "yAxis": {"min": -60, "max": 0, "scale": "linear", "label": "Level", "unit": "dBFS"},
        "series": [{"name": "trace", "color": "#B9E7ED",
                    "points": [[0, -10], [512, -30], [1024, -20], [2048, -50]]}],
        "markers": [{"x": 512, "y": -30, "label": "peak", "kind": "peak"}],
    }
    payload.update(extra)
    return payload


PAIR_PANELS = [
    {"title": "Sxx / Syy", "series": [
        {"name": "Sxx", "points": [[20, -40], [1000, -60], [20000, -80]]},
        {"name": "Syy", "points": [[20, -42], [1000, -62], [20000, -82]]}]},
    {"title": "CSD", "series": [
        {"name": "Re", "points": [[20, 0.1], [1000, -0.2], [20000, 0.3]]},
        {"name": "Im", "points": [[20, -0.05], [1000, 0.15], [20000, -0.25]], "dashed": True}]},
]

COHERENCE_PANELS = [
    {"title": "Coherence", "yAxis": {"min": 0, "max": 1, "label": "Coherence", "unit": ""},
     "series": [{"name": "coh", "points": [[20, 0.4], [1000, 0.95], [20000, 0.6]]}]},
    {"title": "Phase", "yAxis": {"min": -3.2, "max": 3.2, "label": "Phase", "unit": "rad"},
     "series": [{"name": "phase", "points": [[20, 0.0], [1000, -1.2], [20000, 2.4]], "unit": "rad"}]},
]

WEIGHTING_PANELS = [
    {"title": "A/C/Z frequency weighting",
     "series": [{"name": "A", "points": [[20, -50], [1000, 0], [20000, -9]]},
                {"name": "C", "points": [[20, -6], [1000, 0], [20000, -11]]},
                {"name": "Z", "points": [[20, 0], [1000, 0], [20000, 0]]}]},
    {"title": "Z time weighting",
     "series": [{"name": "FAST", "points": [[0, -30], [0.5, -25], [1, -28]]},
                {"name": "SLOW", "points": [[0, -32], [0.5, -28], [1, -30]], "dashed": True},
                {"name": "LeqFS", "points": [[0, -31], [0.5, -27], [1, -29]]}]},
]

STAT_PANELS = [
    {"title": "Level distribution",
     "series": [{"name": "CDF", "points": [[-60, 0], [-40, 0.1], [-30, 0.5], [-20, 0.9]]}],
     "markers": [{"x": -30, "y": 0.5, "label": "L50", "kind": "peak"}]},
    {"title": "Trend",
     "series": [{"name": "Leq", "points": [[0, -35], [1, -33], [2, -34]]}]},
]

STFT_FRAMES = [
    {"time": 0.0, "points": [[20, -80], [100, -60], [1000, -40], [20000, -90]]},
    {"time": 0.1, "points": [[20, -70], [100, -50], [1000, -30], [20000, -80]]},
    {"time": 0.2, "points": [[20, -60], [100, -40], [1000, -20], [20000, -70]]},
]

FEATURE_PAYLOADS = {
    "spectrum": _spectrum_payload(),
    "zoom-spectrum": {**_spectrum_payload(), "kind": "zoom-spectrum",
                      "xAxis": {"min": 900, "max": 1100, "scale": "linear", "label": "Frequency", "unit": "Hz"}},
    "spectral-decay": {
        "kind": "spectral-decay", "title": "Spectral decay", "chartRevision": 1,
        "xAxis": {"min": 0, "max": 2, "scale": "linear", "label": "Time", "unit": "s"},
        "yAxis": {"min": -60, "max": 0, "scale": "linear", "label": "Level", "unit": "dB"},
        "series": [{"name": "1 kHz", "points": [[0, 0], [0.5, -20], [1, -40], [2, -60]]},
                   {"name": "2 kHz", "points": [[0, 0], [0.5, -24], [1, -46], [2, -62]], "dashed": True}],
        "scalarRows": [{"label": "EDT", "value": 0.45, "unit": "s", "valid": True}],
    },
    "lag-series": _line_payload("lag-series"),
    "bands": {
        "kind": "bands", "title": "Octave bands", "chartRevision": 1,
        "xAxis": {"min": 63, "max": 8000, "label": "Band", "unit": "Hz"},
        "yAxis": {"min": -80, "max": -20, "scale": "linear", "label": "Level", "unit": "dBFS"},
        "categories": [
            {"label": "63", "value": -50, "valid": True, "centerFrequency": 63},
            {"label": "125", "value": -45, "valid": True, "centerFrequency": 125},
            {"label": "250", "value": -40, "valid": True, "centerFrequency": 250},
            {"label": "500", "value": None, "valid": False, "centerFrequency": 500},
            {"label": "1k", "value": -35, "valid": True, "centerFrequency": 1000}],
    },
    "harmonic-bars": {
        "kind": "harmonic-bars", "title": "Harmonics", "chartRevision": 1,
        "yAxis": {"min": -80, "max": 0, "scale": "linear", "label": "Power", "unit": "FS^2"},
        "categories": [{"label": "H1", "value": -10, "valid": True},
                       {"label": "H2", "value": -30, "valid": True},
                       {"label": "H3", "value": -45, "valid": False}],
        "referenceValues": [{"value": -20, "label": "THD ref", "color": "#E2E649"}],
        "scalarRows": [{"label": "THD", "value": 0.08, "valid": True}],
    },
    "insulation-bars": {
        "kind": "insulation-bars", "title": "Relative insulation", "chartRevision": 1,
        "yAxis": {"min": -10, "max": 40, "scale": "linear", "label": "Difference", "unit": "dB"},
        "categories": [{"label": "125", "value": 5, "valid": True},
                       {"label": "250", "value": 12, "valid": True},
                       {"label": "500", "value": -3, "valid": True},
                       {"label": "1k", "value": None, "valid": False}],
        "limitLine": {"value": 0, "label": "no difference"},
    },
    "stft": {
        "kind": "stft", "title": "STFT", "chartRevision": 1, "imageUrl": "",
        "xAxis": {"min": 0, "max": 0.2, "scale": "linear", "label": "Time", "unit": "s"},
        "yAxis": {"min": 20, "max": 20000, "scale": "log", "label": "Frequency", "unit": "Hz"},
        "colorScale": {"min": -90, "max": -20, "palette": "viridis", "label": "Level", "unit": "dBFS"},
        "frames": STFT_FRAMES,
    },
    "pair-spectra": {
        "kind": "pair-spectra", "title": "Sxx / Syy / CSD", "chartRevision": 1,
        "xAxis": {"min": 20, "max": 20000, "scale": "log", "label": "Frequency", "unit": "Hz"},
        "panels": PAIR_PANELS,
    },
    "coherence-phase": {
        "kind": "coherence-phase", "title": "Coherence and phase", "chartRevision": 1,
        "xAxis": {"min": 20, "max": 20000, "scale": "log", "label": "Frequency", "unit": "Hz"},
        "panels": COHERENCE_PANELS,
    },
    "weighting": {
        "kind": "weighting", "title": "Weighting", "chartRevision": 1,
        "xAxis": {"min": 20, "max": 20000, "scale": "log", "label": "Frequency", "unit": "Hz"},
        "panels": WEIGHTING_PANELS,
    },
    "room-decay": {
        "kind": "room-decay", "title": "Room decay", "chartRevision": 1,
        "xAxis": {"min": 0, "max": 2, "scale": "linear", "label": "Time", "unit": "s"},
        "yAxis": {"min": -60, "max": 0, "scale": "linear", "label": "Level", "unit": "dB"},
        "series": [{"name": "IR decay", "points": [[0, 0], [0.5, -20], [1, -40], [2, -60]]}],
        "referenceBands": [{"y0": -25, "y1": -5, "label": "T20 PL fit", "opacity": 0.12}],
        "markers": [{"x": 0.0, "y": 0, "label": "onset", "kind": "onset"}],
        "scalarRows": [{"label": "EDT", "value": 0.48, "unit": "s", "valid": True},
                       {"label": "T20", "value": 0.51, "unit": "s", "valid": True},
                       {"label": "T30", "value": None, "unit": "s", "valid": False}],
    },
    "room-clarity": {
        "kind": "room-clarity", "title": "Clarity", "chartRevision": 1,
        "xAxis": {"min": 125, "max": 4000, "scale": "log", "label": "Band", "unit": "Hz"},
        "yAxis": {"min": -10, "max": 20, "scale": "linear", "label": "Value", "unit": "dB"},
        "series": [{"name": "C50", "points": [[125, 2], [500, 5], [4000, 8]]},
                   {"name": "C80", "points": [[125, 4], [500, 7], [4000, 10]], "dashed": True}],
        "scalarRows": [{"label": "C50", "value": 5.2, "unit": "dB", "valid": True},
                       {"label": "C80", "value": 7.1, "unit": "dB", "valid": True},
                       {"label": "D50", "value": 42, "unit": "%", "valid": True}],
    },
    "statistics": {
        "kind": "statistics", "title": "Level statistics", "chartRevision": 1,
        "xAxis": {"min": -60, "max": -20, "scale": "linear", "label": "Level", "unit": "dBFS"},
        "yAxis": {"min": 0, "max": 1, "scale": "linear", "label": "Fraction", "unit": ""},
        "panels": STAT_PANELS,
        "scalarRows": [{"label": "L10", "value": -26, "unit": "dBFS", "valid": True},
                       {"label": "L50", "value": -31, "unit": "dBFS", "valid": True},
                       {"label": "L90", "value": -38, "unit": "dBFS", "valid": True},
                       {"label": "Leq", "value": -33.5, "unit": "dBFS", "valid": True}],
    },
    "noise-rating": {
        "kind": "noise-rating", "title": "NC / NR", "chartRevision": 1,
        "xAxis": {"min": 63, "max": 8000, "scale": "log", "label": "Band", "unit": "Hz"},
        "yAxis": {"min": 0, "max": 80, "scale": "linear", "label": "Level", "unit": "dB"},
        "series": [{"name": "measured", "points": [[63, 40], [125, 35], [250, 30], [500, 25]]}],
        "referenceFamilies": [{"name": "NC-30", "points": [[63, 57], [125, 48], [250, 41], [500, 35]],
                              "color": "#72D6C9", "dashed": True}],
        "scalarRows": [{"label": "NC", "value": 30, "valid": True}],
        "note": "reference estimate, not certified",
    },
    "ab-spectrum": {
        "kind": "ab-spectrum", "title": "A/B spectrum", "chartRevision": 1,
        "xAxis": {"min": 20, "max": 20000, "scale": "log", "label": "Frequency", "unit": "Hz"},
        "yAxis": {"min": -100, "max": 0, "scale": "linear", "label": "Level", "unit": "dBFS"},
        "deltaYAxis": {"min": -20, "max": 20, "scale": "linear", "label": "Delta", "unit": "dB"},
        "series": [
            {"name": "A reference", "role": "a", "points": [[20, -60], [1000, -40], [20000, -80]]},
            {"name": "B current", "role": "b", "points": [[20, -62], [1000, -38], [20000, -78]]},
            {"name": "B - A", "role": "delta", "points": [[20, -2], [1000, 2], [20000, 2]]}],
        "referenceLines": [{"y": 3, "label": "threshold", "dashed": True}],
        "referenceBands": [{"y0": -3, "y1": 3, "label": "tolerance", "opacity": 0.12}],
    },
    "level-bars": {
        "kind": "level-bars", "title": "Channel levels", "chartRevision": 1,
        "meters": [
            {"label": "CH1", "color": "#B9E7ED", "value": -20, "peak": -10, "valid": True},
            {"label": "CH2", "color": "#E2E649", "value": -30, "peak": -22, "valid": True, "clip": True},
            {"label": "CH3", "color": "#C74BDA", "value": None, "valid": False}],
        "scale": {"min": -60, "max": 0, "label": "Level", "unit": "dBFS"},
    },
    "waveform": {
        "kind": "waveform", "title": "PCM", "chartRevision": 1, "sampleRate": 48000,
        "channels": [{"name": "CH1", "color": "#B9E7ED",
                      "values": [0.0, 0.5, -0.5, 0.2, -0.2, 0.9, -0.9, 0.1]}],
        "gaps": [{"start": 3, "end": 4}],
        "xAxis": {"label": "Time", "unit": "s"},
        "yAxis": {"label": "Amplitude", "unit": "FS"},
    },
    "scalars": {
        "kind": "scalars", "title": "Scalars", "chartRevision": 1,
        "scalarRows": [{"label": "frames", "value": 12, "valid": True},
                       {"label": "samples", "value": 2048, "valid": True},
                       {"label": "valid", "value": None, "valid": False}],
    },
    # Runtime history kind: runtime._store_result turns trend features (energy
    # change, band/frequency tracking, drift, centroid, flatness) into this chart.
    "scalar-trend": {
        "kind": "scalar-trend", "title": "Scalar trend", "chartRevision": 1,
        "xAxis": {"min": 0, "max": 2, "scale": "linear", "label": "Time", "unit": "s"},
        "yAxis": {"min": -40, "max": 0, "scale": "linear", "label": "Level", "unit": "dBFS"},
        "series": [{"name": "previous_power_FS2", "points": [[0, -30], [1, -28], [2, -32]]}],
        "scalarRows": [{"label": "power_FS2", "value": -30, "unit": "FS^2", "valid": True},
                       {"label": "delta_FS2", "value": 1.5, "unit": "FS^2", "valid": True}],
    },
    "events": {
        "kind": "events", "title": "Events", "chartRevision": 1,
        "timeAxis": {"min": 0, "max": 10, "label": "Time", "unit": "s"},
        "events": [
            {"position01": 0.2, "label": "event A", "kind": "info", "downloadState": "downloaded"},
            {"position01": 0.5, "label": "event B", "kind": "warn", "downloadState": "pending"},
            {"position01": 0.8, "label": "event C", "kind": "error", "downloadState": "failed"}],
        "downloadLabels": {"downloaded": "downloaded", "pending": "pending", "failed": "failed"},
    },
    # STIPA stage: completed=34, current=37 and legacy index=40 deliberately differ
    # so the test proves stageIndex reads current and progressValue reads completed.
    "stipa": {
        "kind": "stipa", "title": "Experimental STIPA", "chartRevision": 1,
        "stage": {"completed": 34, "total": 101, "current": 37, "index": 40, "label": "stage 37"},
        "indexValue": 0.72, "indexLabel": "STI", "indexUnit": "", "indexValid": True,
        "scalarRows": [{"label": "index", "value": 0.72, "valid": True},
                       {"label": "validity", "value": 1, "valid": True},
                       {"label": "certified", "value": 0, "valid": True}],
        "caption": "experimental, not certified STIPA",
    },
}

TOKEN_BY_KIND = {
    # FeaturePayload.KIND_TOKENS routes these readout-bearing line charts through
    # the readout-line presentation (the line token plus scalar rows resolves too).
    "spectrum": "line", "zoom-spectrum": "line", "spectral-decay": "readout-line",
    "lag-series": "readout-line",
    "bands": "bars-readout", "insulation-bars": "bars-readout", "harmonic-bars": "bars-readout",
    "stft": "stft",
    "pair-spectra": "panel", "coherence-phase": "panel", "weighting": "panel",
    "room-decay": "readout-line", "room-clarity": "readout-line", "statistics": "readout-line",
    "ab-spectrum": "ab", "stipa": "stipa", "waveform": "waveform", "level-bars": "level",
    "scalars": "scalars", "scalar-trend": "readout-line",
    "events": "events",
    "noise-rating": "noise",
}

CONTENT_BY_TOKEN = {
    "line": "chartLine", "bars-readout": "chartBarsReadout", "stft": "chartStftHost",
    "panel": "chartPanel", "readout-line": "chartReadoutLine",
    "ab": "chartAbSpectrum", "stipa": "chartStipa", "waveform": "chartWaveform",
    "level": "chartLevelMeter", "scalars": "chartScalars",
    "events": "chartEvents", "noise": "chartNoiseRating", "empty": "chartEmptyState",
}


def _spec_chart_kinds():
    import json as _json
    spec = _json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    return {str(item.get("chart")) for item in spec["features"].values()}


def test_every_spec_chart_kind_has_a_feature_payload():
    # 21 static chart kinds in the 45-feature spec (the six spatial features and
    # their capability/beam-spectrum/das-map charts were removed) plus the
    # runtime-history "scalar-trend" kind.
    assert len(FEATURE_PAYLOADS) == 22
    spec_kinds = _spec_chart_kinds()
    assert spec_kinds == set(FEATURE_PAYLOADS) - {"scalar-trend"}, (
        spec_kinds - set(FEATURE_PAYLOADS),
        set(FEATURE_PAYLOADS) - {"scalar-trend"} - spec_kinds)


def test_featurechart_routes_all_supported_kinds_without_warnings(feature_scene, qapp):
    scene = feature_scene()
    seen = {}
    for kind, payload in FEATURE_PAYLOADS.items():
        scene.set_payload(payload, qapp)
        token = scene.chart.property("routeToken")
        item = scene.item()
        assert token == TOKEN_BY_KIND[kind], (kind, token)
        assert item is not None, kind
        name = item.objectName()
        if not name:
            # Das host wraps its PolarChart plus a readout strip in an unnamed Item.
            inner = find_visual(item, CONTENT_BY_TOKEN[token])
            name = inner.objectName() if inner is not None else ""
        assert name == CONTENT_BY_TOKEN[token], (kind, token, name)
        assert item.width() > 20 and item.height() > 20, (kind, item.width(), item.height())
        seen[kind] = name
    assert len(seen) == 22
    # The retired spatial chart kinds are no longer routed: a device that still
    # sends them must render the empty state, not a stale capability/beam/DAS view.
    for removed in ("das-map", "beam-spectrum", "capability"):
        scene.set_payload({"kind": removed, "title": removed, "chartRevision": 1}, qapp)
        assert scene.chart.property("routeToken") == "empty", removed
        assert scene.find("chartEmptyState") is not None, removed
    assert scene.warnings == [], scene.warnings


def test_featurechart_empty_invalid_and_unavailable_states(feature_scene, qapp):
    scene = feature_scene()
    empty_spectrum = {"kind": "spectrum", "title": "FFT", "series": [],
                      "emptyReason": "waiting for device result"}
    scene.set_payload(empty_spectrum, qapp)
    line = scene.find("chartLine")
    assert line is not None
    assert len(qv(line.property("series"))) == 0
    assert line.property("emptyReason") == "waiting for device result"
    assert scene.warnings == []

    scene.set_payload({"kind": "not-a-chart", "title": "unknown"}, qapp)
    assert scene.find("chartEmptyState") is not None

    scene.app.set_workspace(available=False, disabledReason="device software needs echo-features-1")
    scene.app.set_chart({"kind": "spectrum", "series": [{"points": [[1, 2]]}]})
    pump(qapp, 0.12)
    state = scene.find("chartEmptyState")
    assert state is not None
    assert "echo-features-1" in state.property("reason")

    scene.app.set_workspace(available=True, disabledReason="")
    scene.set_payload(FEATURE_PAYLOADS["stft"], qapp)
    heat = scene.find("chartHeatmap")
    assert heat is not None and heat.property("imageUrl") == ""

    scene.set_payload({"kind": "stft", "frames": [[1, 2], [3, 4]]}, qapp)
    scene.chart.setProperty("threeDActive", True)
    pump(qapp, 0.12)
    waterfall = scene.find("chartWaterfall")
    assert waterfall is not None
    assert len(qv(waterfall.property("frames"))) == 0
    assert scene.warnings == []


def test_featurechart_toolbar_layout_and_view_operations(feature_scene, qapp):
    # Two series: the toolbar only offers the legend button when a legend exists.
    payload = _spectrum_payload()
    payload["series"].append({"name": "CH2", "color": "#E2E649",
                              "points": [[20, -70], [1000, -50], [20000, -80]]})
    scene = feature_scene(payload)
    toolbar = scene.find("chartToolbar")
    assert toolbar is not None
    # ChartToolbar targets are 34 px tall; the reset/fit target is 48 px wide (it
    # carries a text label) and the icon-only targets are 36 px wide.
    expected_sizes = {"fit": (48, 34)}
    for key in ("fit", "log", "cursor", "legend", "save"):
        button = scene.find("chartToolbarBtn_" + key)
        assert button is not None, key
        width, height = expected_sizes.get(key, (36, 34))
        assert (int(button.width()), int(button.height())) == (width, height), key
        icon = scene.find("chartIcon_" + key)
        assert icon is not None, key
        assert int(icon.width()) == 20 and int(icon.height()) == 20, key
    assert scene.find("chartToolbarBtn_3d") is None
    title = scene.find("chartTitle")
    assert title is not None
    assert title.x() < toolbar.width() / 2.0
    assert title.x() + title.width() <= toolbar.width() + 1

    scene.invoke("activate('log')", toolbar)
    assert scene.chart.property("logScaleEnabled") is False
    assert ("fft", "logX", "false") in scene.app.view_options
    scene.invoke("activate('log')", toolbar)

    scene.invoke("activate('cursor')", toolbar)
    assert scene.chart.property("cursorEnabled") is True
    assert scene.chart.property("lineCursorA") is not None
    assert scene.app.pl_calls == []
    scene.invoke("activate('cursor')", toolbar)

    scene.invoke("activate('legend')", toolbar)
    assert scene.chart.property("legendVisible") is False
    line = scene.find("chartLine")
    assert line is not None and line.property("showLegend") is False
    scene.invoke("activate('legend')", toolbar)

    before = scene.chart.property("fitCounter")
    scene.invoke("activate('fit')", toolbar)
    assert scene.chart.property("fitCounter") == before + 1

    scene.invoke("activate('save')", toolbar)
    deadline = time.monotonic() + 6.0
    capture = _Path(scene.app.capture_path)
    while not capture.is_file() and time.monotonic() < deadline:
        pump(qapp, 0.05)
    assert capture.is_file(), "grabToImage did not save the chart PNG"
    assert capture.stat().st_size > 500
    assert scene.app.notified == [scene.app.capture_path]
    assert scene.app.pl_calls == []
    assert scene.warnings == [], scene.warnings


def test_stft_2d3d_projection_toggle(feature_scene, qapp):
    # DAS polar-rect projection died with the six spatial features; the STFT
    # 2D/3D toggle is the remaining projection-style view and stays covered.
    scene = feature_scene(FEATURE_PAYLOADS["stft"])
    heat = scene.find("chartHeatmap")
    waterfall = scene.find("chartWaterfall")
    assert heat is not None and waterfall is not None
    assert heat.property("visible") is True and waterfall.property("visible") is False
    scene.chart.setProperty("threeDActive", True)
    pump(qapp, 0.12)
    assert heat.property("visible") is False and waterfall.property("visible") is True
    assert len(qv(waterfall.property("frames"))) == 3
    assert scene.warnings == []


def test_spectrum_log_axis_excludes_nonpositive_and_linear_switch(feature_scene, qapp):
    payload = _spectrum_payload()
    payload["series"][0]["points"] = [[0, -50], [20, -80], [1000, -40], [20000, -90]]
    scene = feature_scene(payload)
    line = scene.find("chartLine")
    assert line is not None
    assert line.property("clippedLog") >= 1
    assert qv(line.property("xAxis")).get("scale") == "log"
    scene.invoke("activate('log')", scene.find("chartToolbar"))
    pump(qapp, 0.12)
    assert qv(line.property("xAxis")).get("scale") == "linear"
    assert scene.warnings == []


def test_bands_shared_ramp_and_invalid_category(feature_scene, qapp):
    scene = feature_scene(FEATURE_PAYLOADS["bands"])
    bar = scene.find("readoutBarChart")
    assert bar is not None
    ramp = qv(bar.property("bandRamp"))
    assert len(ramp) == 7
    assert str(ramp[0]).lower() == "#6a5acd" and str(ramp[-1]).lower() == "#e2e649"
    scale = qv(bar.property("colorScale"))
    assert scale is not None and scale.get("locked") is True
    assert scale.get("max") > scale.get("min")
    assert len(qv(bar.property("categories"))) == 5
    assert qv(bar.property("categories"))[3].get("valid") is False
    assert bar.property("xMode") == "centerFrequency"
    assert scene.warnings == []


def test_dual_panel_kinds_keep_two_separate_charts(feature_scene, qapp):
    for kind in ("pair-spectra", "coherence-phase", "weighting"):
        scene = feature_scene(FEATURE_PAYLOADS[kind])
        panel = scene.find("chartPanel")
        assert panel is not None, kind
        assert int(panel.property("panelCount")) == 2, kind
        lines = find_visual_all(panel, "panelLineChart")
        assert len(lines) == 2, (kind, len(lines))
        assert scene.warnings == [], (kind, scene.warnings)

    scene = feature_scene(FEATURE_PAYLOADS["coherence-phase"])
    line = scene.find("panelLineChart")
    assert line is not None
    assert qv(line.property("yAxis")).get("min") == 0
    assert qv(line.property("yAxis")).get("max") == 1
    assert scene.warnings == []


def test_statistics_readout_and_panel_trend(feature_scene, qapp):
    scene = feature_scene(FEATURE_PAYLOADS["statistics"])
    readout = scene.find("readoutStrip")
    assert readout is not None
    assert len(qv(readout.property("rows"))) == 4
    panel = scene.find("chartPanel")
    assert panel is not None and int(panel.property("panelCount")) == 2
    assert scene.warnings == []


def test_ab_spectrum_keeps_a_b_delta_distinct(feature_scene, qapp):
    scene = feature_scene(FEATURE_PAYLOADS["ab-spectrum"])
    ab = scene.find("chartAbSpectrum")
    assert ab is not None
    top = qv(ab.property("abSeries"))
    delta = qv(ab.property("deltaSeries"))
    assert len(top) == 2 and len(delta) == 1
    assert top[0].get("color") != top[1].get("color")
    assert delta[0].get("color") not in (top[0].get("color"), top[1].get("color"))
    top_chart = scene.find("abTopChart")
    delta_chart = scene.find("abDeltaChart")
    assert top_chart is not None and delta_chart is not None
    assert qv(delta_chart.property("yAxis")).get("max") == 20
    assert scene.warnings == []


def test_stipa_stage_progress_and_readouts(feature_scene, qapp):
    scene = feature_scene(FEATURE_PAYLOADS["stipa"])
    stipa = scene.find("chartStipa")
    assert stipa is not None
    # stageTotal = total; stageIndex = current stage index (37), never completed
    # (34) and never the legacy index (40); progressValue only uses completed.
    assert int(stipa.property("stageTotal")) == 101
    assert int(stipa.property("stageIndex")) == 37
    assert abs(float(stipa.property("progressValue")) - 34 / 101) < 1e-6
    bars = find_visual_all(stipa, "stipaProgressBar")
    assert len(bars) == 1
    assert int(bars[0].property("to")) == 101
    assert abs(float(bars[0].property("value")) - 34) < 1e-6
    values = find_visual_all(stipa, "stipaProgressValue")
    assert len(values) == 1  # the progress digits are formatted by exactly one Text
    assert values[0].property("text") == "34 / 101"
    labels = find_visual_all(stipa, "stipaStageLabel")
    assert len(labels) == 1 and labels[0].property("text") == "stage 37"
    readout = scene.find("stipaReadout")
    assert readout is not None and len(qv(readout.property("rows"))) == 3
    assert scene.warnings == []


def test_stipa_legacy_index_only_stage_still_falls_back(feature_scene, qapp):
    payload = dict(FEATURE_PAYLOADS["stipa"])
    payload["stage"] = {"index": 37, "total": 101, "label": "stage 37"}
    scene = feature_scene(payload)
    stipa = scene.find("chartStipa")
    assert int(stipa.property("stageTotal")) == 101
    assert int(stipa.property("stageIndex")) == 37
    assert abs(float(stipa.property("progressValue")) - 37 / 101) < 1e-6
    values = find_visual_all(stipa, "stipaProgressValue")
    assert values[0].property("text") == "37 / 101"
    assert scene.warnings == []

    # Legacy stage payload with neither current nor index: current falls back to
    # the completed count, and progressValue is still completed/total.
    completed_only = dict(FEATURE_PAYLOADS["stipa"])
    completed_only["stage"] = {"completed": 34, "total": 101, "label": "stage"}
    scene = feature_scene(completed_only)
    stipa = scene.find("chartStipa")
    assert int(stipa.property("stageIndex")) == 34
    assert abs(float(stipa.property("progressValue")) - 34 / 101) < 1e-6
    assert scene.warnings == []


def test_stipa_progress_area_stays_inside_narrow_layout(scene, qapp):
    # In-flight scenario (50 / 101): the progress area is still displayed, so this
    # keeps testing the narrow-window layout of the progress rows.
    engine, win, warnings = scene('''StipaChart { objectName: "stipaNarrow"; anchors.fill: parent
        stage: ({completed: 50, total: 101, current: 50,
                 label: "a very long stage label that must elide instead of covering the progress digits"})
        indexLabel: "a very long experimental index label that must elide"
        indexUnit: "STI"
        scalarRows: [{label: "index", value: 0.72, valid: true}]
        caption: "experimental, not certified STIPA" }''')
    win.setWidth(420)
    pump(qapp, 0.2)
    stipa = win.findChild(QQuickItem, "stipaNarrow")
    area = win.findChild(QQuickItem, "stipaProgressArea")
    assert stipa is not None and area is not None
    assert area.property("visible") is True
    assert area.property("clip") is True
    assert area.width() <= stipa.width() + 1
    bar = win.findChild(QQuickItem, "stipaProgressBar")
    value = win.findChild(QQuickItem, "stipaProgressValue")
    label = win.findChild(QQuickItem, "stipaStageLabel")
    for item in (bar, value, label):
        assert item is not None
        assert item.x() >= -1
        assert item.x() + item.width() <= area.width() + 1
    assert int(bar.height()) == 8
    assert value.property("text") == "50 / 101"
    # The elided stage label never overlaps the progress digits.
    assert label.x() + label.width() <= value.x() + 1
    assert warnings == []


def test_stipa_progress_visible_in_flight_and_hidden_after_result(feature_scene, qapp):
    scene = feature_scene(FEATURE_PAYLOADS["stipa"])
    stipa = scene.find("chartStipa")
    assert stipa is not None
    area = find_visual(stipa, "stipaProgressArea")
    bar = find_visual(stipa, "stipaProgressBar")
    digits = find_visual(stipa, "stipaProgressValue")
    readout = scene.find("stipaReadout")
    caption = find_visual(stipa, "stipaCaption")
    index_value = find_visual(stipa, "stipaIndexValue")
    assert area is not None and bar is not None and digits is not None
    assert readout is not None and caption is not None and index_value is not None
    # A running measurement keeps the stage progress (digits stay 34 / 101: the
    # completed count, never stageIndex or the legacy index).
    assert area.property("visible") is True
    assert bar.property("visible") is True
    assert digits.property("visible") is True
    assert digits.property("text") == "34 / 101"

    # Result presented by the page (valid) -> progress area/bar disappear, while
    # the index, readouts and caption remain.
    scene.app.set_workspace(state="completed", hasResult=True, resultValid=True)
    pump(qapp, 0.2)
    assert area.property("visible") is False
    assert bar.property("visible") is False
    assert readout.property("visible") is True and len(qv(readout.property("rows"))) == 3
    assert index_value.property("visible") is True
    assert index_value.property("text") == "0.72"
    assert caption.property("visible") is True
    assert caption.property("text") == "experimental, not certified STIPA"

    # A re-run still shows progress even though the previous result is retained in
    # the workspace (running state wins over hasResult).
    scene.app.set_workspace(state="running", hasResult=True)
    pump(qapp, 0.2)
    assert area.property("visible") is True
    assert bar.property("visible") is True
    assert scene.warnings == []


def test_stipa_progress_hidden_for_done_stage_and_completed_but_invalid_result(feature_scene, qapp):
    # Device progress payload on the result chart reports completed == total; the
    # chart hides the progress on its own (no page flag needed).
    done = json.loads(json.dumps(FEATURE_PAYLOADS["stipa"]))
    done["stage"] = {"completed": 101, "total": 101, "current": 101, "label": "done"}
    scene = feature_scene(done)
    stipa = scene.find("chartStipa")
    assert stipa is not None
    area = find_visual(stipa, "stipaProgressArea")
    bar = find_visual(stipa, "stipaProgressBar")
    assert area is not None and bar is not None
    assert area.property("visible") is False
    assert bar.property("visible") is False
    readout = scene.find("stipaReadout")
    assert readout is not None and readout.property("visible") is True
    assert len(qv(readout.property("rows"))) == 3

    # Completed-but-invalid result: progress stays hidden and every readout keeps
    # its place (invalid index renders as a dash, reason rows/caption are kept).
    invalid = json.loads(json.dumps(done))
    invalid["indexValid"] = False
    invalid["indexValue"] = None
    invalid["scalarRows"] = [{"label": "valid", "value": 0, "unit": "bool", "valid": True},
                             {"label": "reason_code", "value": 2, "valid": True}]
    invalid["invalidReason"] = "level too low for the reference"
    scene.set_payload(invalid, qapp)
    scene.app.set_workspace(state="completed", hasResult=True, resultValid=False)
    pump(qapp, 0.2)
    assert area.property("visible") is False
    assert bar.property("visible") is False
    assert readout.property("visible") is True
    assert len(qv(readout.property("rows"))) == 2
    index_value = find_visual(stipa, "stipaIndexValue")
    assert index_value is not None and index_value.property("visible") is True
    assert index_value.property("text") == "\u2014"
    caption = find_visual(stipa, "stipaCaption")
    assert caption is not None and caption.property("visible") is True
    assert caption.property("text") == "experimental, not certified STIPA"
    assert scene.warnings == []


def test_stipa_chart_has_no_canvas_or_hand_painted_progress_text():
    text = (CHARTS_DIR / "StipaChart.qml").read_text(encoding="utf-8")
    for needle in ("Canvas", "fillText", "getContext", "paintProgress", "requestPaint"):
        assert needle not in text, needle
    # The progress digits are formatted by exactly one Text, as completed / total.
    assert text.count('" / "') == 1
    assert text.count('objectName: "stipaProgressValue"') == 1
    for needle in ("ProgressBar", "clip: true", "Layout.minimumWidth: 0"):
        assert needle in text, needle


def test_feature_workspace_progress_and_invalid_result_contract():
    text = (QML / "components/FeatureWorkspace.qml").read_text(encoding="utf-8")
    # Progress numbers read the same completed/total fields the decoder exposes;
    # the legacy stage.index value must never feed the progress display.
    for needle in ("measurement.completedStages", "measurement.totalStages",
                   "measurement.currentStageIndex",
                   "(currentChart.stage || {}).completed",
                   "(currentChart.stage || {}).total"):
        assert needle in text, needle
    assert "stage || {}).index" not in text
    # Quick STIPA now records the 8 s reference.
    assert "①录制8秒参考" in text and "1. Record 8s reference" in text
    assert "①录制3秒参考" not in text and "1. Record 3s reference" not in text
    # Completed-but-invalid results are a warning, not the green success state.
    assert "workspace.resultValid === false ? Theme.warn : Theme.ok" in text
    assert "处理完成，但测量无效" in text
    # The run-progress digits are hidden as soon as a result (valid or completed-
    # but-invalid) is presented; the status message stays.
    assert 'objectName: "workspaceProgressValue"' in text
    assert "root.progressTotal > 1 && !root.resultPresent" in text
    for needle in ("root.workspace.state", "root.workspace.hasResult === true",
                   "running", "completed", "stopped"):
        assert needle in text, needle


def test_feature_workspace_status_digits_hide_once_result_is_presented(feature_workspace_scene, qapp):
    scene = feature_workspace_scene(_stipa_workspace())
    status = scene.find("workspaceStatusText")
    digits = scene.find("workspaceProgressValue")
    assert status is not None and digits is not None
    # Running: the status row shows the device progress digits.
    assert digits.property("visible") is True
    assert digits.property("text") == "34 / 101"
    chart = scene.find("chartStipa")
    assert chart is not None
    area = find_visual(chart, "stipaProgressArea")
    assert area is not None and area.property("visible") is True

    # Valid result presented: only the run progress disappears; status message,
    # chart readouts and index remain.
    scene.app.set_workspace(state="completed", hasResult=True, resultValid=True,
                            message="measurement finished")
    pump(qapp, 0.25)
    assert digits.property("visible") is False
    assert status.property("visible") is True
    assert status.property("text") == "measurement finished"
    assert area.property("visible") is False
    readout = scene.find("stipaReadout")
    assert readout is not None and readout.property("visible") is True
    assert len(qv(readout.property("rows"))) == 3
    assert scene.warnings == []

    # Completed-but-invalid result: same hiding, invalid reason/message kept.
    invalid = json.loads(json.dumps(FEATURE_PAYLOADS["stipa"]))
    invalid["stage"] = {"completed": 101, "total": 101, "current": 101, "label": "done"}
    invalid["indexValid"] = False
    invalid["indexValue"] = None
    invalid["scalarRows"] = [{"label": "valid", "value": 0, "unit": "bool", "valid": True},
                             {"label": "reason_code", "value": 2, "valid": True}]
    scene.app.set_workspace(state="running", hasResult=True, chart=invalid,
                            message="computing")
    pump(qapp, 0.25)
    # A re-run after a previous result must keep showing progress: the live job
    # progress in the workspace wins over the finished stage in the old payload.
    assert digits.property("visible") is True
    assert area.property("visible") is True
    live = find_visual(chart, "stipaProgressValue")
    assert live is not None and live.property("text") == "34 / 101"
    scene.app.set_workspace(state="completed", hasResult=True, resultValid=False,
                            message="processing finished, measurement invalid")
    pump(qapp, 0.25)
    assert digits.property("visible") is False
    assert status.property("text") == "processing finished, measurement invalid"
    assert area.property("visible") is False
    assert readout.property("visible") is True
    assert len(qv(readout.property("rows"))) == 2
    index_value = find_visual(chart, "stipaIndexValue")
    assert index_value is not None and index_value.property("visible") is True
    assert index_value.property("text") == "\u2014"
    assert scene.warnings == []


def test_events_timeline_reports_real_events(feature_scene, qapp):
    scene = feature_scene(FEATURE_PAYLOADS["events"])
    timeline = scene.find("chartEvents")
    assert timeline is not None
    assert int(timeline.property("eventCount")) == 3
    activated: list[int] = []
    scene.chart.eventActivated.connect(lambda index: activated.append(int(index)))
    px = 36 + 0.2 * (timeline.width() - 52)
    py = 24 + (timeline.height() - 58) * 0.6
    scene_coords = timeline.mapToScene(QPointF(px, py))
    local = QPointF(scene_coords.x(), scene_coords.y())
    for event_type in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
        buttons = Qt.LeftButton if event_type == QEvent.MouseButtonPress else Qt.NoButton
        event = QMouseEvent(event_type, local, local, Qt.LeftButton, buttons, Qt.NoModifier)
        QCoreApplication.sendEvent(scene.window, event)
    pump(qapp, 0.25)
    assert activated == [0], activated
    assert scene.app.pl_calls == []
    assert scene.warnings == []


def test_level_bars_invalid_and_clip(feature_scene, qapp):
    scene = feature_scene(FEATURE_PAYLOADS["level-bars"])
    meter = scene.find("chartLevelMeter")
    assert meter is not None
    meters = qv(meter.property("meters"))
    assert len(meters) == 3
    assert meters[1].get("clip") is True
    assert meters[2].get("valid") is False
    assert scene.warnings == []


def test_waveform_keeps_gaps_and_sample_rate(feature_scene, qapp):
    scene = feature_scene(FEATURE_PAYLOADS["waveform"])
    wave = scene.find("chartWaveform")
    assert wave is not None
    assert float(wave.property("sampleRate")) == 48000.0
    assert len(qv(wave.property("gaps"))) == 1
    assert wave.property("xMode") == "time"
    assert scene.warnings == []


def test_scalars_panel(feature_scene, qapp):
    scene = feature_scene(FEATURE_PAYLOADS["scalars"])
    scalars = scene.find("chartScalars")
    assert scalars is not None and len(qv(scalars.property("rows"))) == 3
    assert scene.warnings == []


def test_chart_layer_has_no_hardcoded_cjk_ui_text():
    cjk = re.compile(r"[\u3400-\u9fff]")
    offenders = []
    for path in sorted(CHARTS_DIR.glob("*.qml")) + sorted(CHARTS_DIR.glob("*.js")):
        if cjk.search(path.read_text(encoding="utf-8")):
            offenders.append(path.name)
    feature_chart = QML / "components/FeatureChart.qml"
    assert not cjk.search(feature_chart.read_text(encoding="utf-8"))
    assert offenders == [], offenders


def test_plot_images_peak_envelope_preserves_transients_and_gaps():
    from ui.viewmodels.plot_images import peak_envelope

    values = [0.1] * 10000
    values[4999] = 0.98
    values[5000] = -0.97
    values[7000:7200] = [None] * 200
    envelope = peak_envelope(values, 4096)
    assert len(envelope) == 4096
    assert 0.98 in envelope and -0.97 in envelope
    assert None in envelope
    assert envelope.count(None) >= 2
    assert peak_envelope([0.1, 0.2, None, 0.3], 4096) == [0.1, 0.2, None, 0.3]


def test_plot_images_heatmap_lock_and_invalid_cells():
    from ui.viewmodels.plot_images import BLACK, heatmap_image

    locked = heatmap_image([[0.0, 1.0]], locked_range=(-1.0, 1.0))
    assert not locked.isNull()
    assert (locked.pixel(0, 0) & 0xFFFFFF) != (locked.pixel(1, 0) & 0xFFFFFF)
    data_range = heatmap_image([[0.0, 1.0]])
    assert not data_range.isNull()
    invalid = heatmap_image([[None, 0.5, float("nan")]])
    assert not invalid.isNull()
    assert invalid.pixel(0, 0) == BLACK
    assert invalid.pixel(1, 0) != BLACK  # the one supplied value keeps its colour
    assert invalid.pixel(2, 0) == BLACK
    assert heatmap_image([[None, None]]).isNull()


def test_plot_images_stft_raster_keeps_missing_frames_empty():
    from ui.viewmodels.plot_images import BLACK, stft_image

    frames = [
        {"time": 0.0, "points": [[100, -60], [1000, -40]]},
        {"time": 0.1, "points": [[100, -55], [1000, -35]]},
        {"time": 0.3, "points": [[100, -50], [1000, -30]]},
    ]
    image = stft_image(frames, frequency_axis={"min": 100, "max": 1000, "scale": "log"},
                       time_axis={"min": 0.0, "max": 0.3},
                       color_scale={"min": -60, "max": -30}, width=24, height=30)
    assert not image.isNull()
    assert image.width() == 24 and image.height() == 30
    black = sum(1 for y in range(image.height()) for x in range(image.width())
                if image.pixel(x, y) == BLACK)
    assert black > 0
    middle_rows = [image.pixel(x, y) for y in (11, 12, 13, 14) for x in range(image.width())]
    assert all(pixel == BLACK for pixel in middle_rows)
    assert stft_image([]).isNull()
    assert stft_image([{"time": 0.0, "points": []}]).isNull()


def test_plot_images_das_rect_and_polar_mapping():
    from ui.viewmodels.plot_images import BLACK, das_image

    points = [{"azimuth": 90.0, "elevation": 0.0, "power": -20.0},
              {"azimuth": 0.0, "elevation": 90.0, "power": -40.0}]
    axes = dict(azimuth_axis={"min": 0, "max": 360}, elevation_axis={"min": 0, "max": 90},
                color_scale={"min": -60, "max": 0})
    rect = das_image(points, projection="rect", size=64, **axes)
    assert not rect.isNull()
    assert rect.pixel(16, 63) != BLACK
    assert rect.pixel(0, 0) != BLACK
    polar = das_image(points, projection="polar", size=64, **axes)
    assert not polar.isNull()
    assert polar.pixel(32, 32) != BLACK  # azimuth 90 / elevation 0 => centre-right ray start
    assert polar.pixel(32, 0) != BLACK or polar.pixel(32, 1) != BLACK  # azimuth 0 at the top
    assert das_image([]).isNull()
    assert das_image([{"azimuth": None, "elevation": 1, "power": 2}]).isNull()


def test_plot_images_cache_is_bounded_and_revisioned():
    from PySide6.QtGui import QImage
    from ui.viewmodels.plot_images import BLACK, FeatureRasterCache, PlotImageProvider, image_url

    cache = FeatureRasterCache(max_entries=2)
    image = QImage(4, 4, QImage.Format.Format_RGB32)
    image.fill(0xFF112233)
    assert cache.put("a", image) == 1
    assert cache.put("a", image) == 2
    assert cache.revision("a") == 2
    assert image_url(cache, "a") == "image://plots/a/2"
    cache.put("b", image)
    cache.put("c", image)
    assert len(cache) == 2
    assert cache.keys() == ["b", "c"]
    assert cache.revision("a") == 0
    cache.invalidate("b")
    assert len(cache) == 1 and cache.revision("b") == 0

    provider = PlotImageProvider(max_entries=4)
    empty = provider.requestImage("missing/1", QSize(2, 2), None)
    assert empty.pixel(0, 0) == BLACK
    revision = provider.set_image("stft", image)
    assert revision == 1
    served = provider.requestImage("stft/" + str(revision), QSize(4, 4), None)
    assert served.pixel(0, 0) == 0xFF112233
    assert provider.revision("stft") == 1


def test_featurepayload_js_normalisation_and_kind_coverage():
    from PySide6.QtQml import QJSEngine

    util_source = (CHARTS_DIR / "ChartUtil.js").read_text(encoding="utf-8")
    util_source = util_source.replace(".pragma library", "")
    payload_source = (CHARTS_DIR / "FeaturePayload.js").read_text(encoding="utf-8")
    payload_source = payload_source.replace(".pragma library", "")
    payload_source = payload_source.replace('.import "ChartUtil.js" as U', "")
    payload_source = payload_source.replace("U.", "")
    engine = QJSEngine()
    result = engine.evaluate(util_source + "\n" + payload_source)
    assert not result.isError(), result.toString()

    kinds = engine.evaluate("kindList()")
    assert not kinds.isError(), kinds.toString()
    kind_set = set(kinds.toVariant())
    assert kind_set == set(FEATURE_PAYLOADS)
    # scalar-trend is a supported runtime-history kind without a static spec entry.
    assert kind_set - {"scalar-trend"} == _spec_chart_kinds()

    assert engine.evaluate("routeToken('spectrum')").toVariant() == "line"
    assert engine.evaluate("routeToken('unknown-kind')").toVariant() == "empty"
    assert engine.evaluate("routeToken('stipa')").toVariant() == "stipa"

    import json as _json
    frames = engine.evaluate(
        "JSON.stringify(frames({frames:[{time:0,points:[[100,-40]]},"
        "{time:0.1,points:[[100,-30]]}]}).frames)")
    assert _json.loads(frames.toVariant()) == [
        {"time": 0, "points": [[100, -40]]},
        {"time": 0.1, "points": [[100, -30]]}]
    unsupported = _json.loads(
        engine.evaluate("JSON.stringify(frames({frames:[[1,2],[3,4]]}))").toVariant())
    assert unsupported["supported"] is False
    assert unsupported["hadPayload"] is True

    split = _json.loads(engine.evaluate(
        "JSON.stringify(abSplit([{name:'a',role:'a'},{name:'b',role:'b'},{name:'d',role:'delta'}]))"
    ).toVariant())
    assert len(split["top"]) == 2 and len(split["delta"]) == 1

def test_stipa_quick_mode_idle_progress_defaults_to_15_stages(feature_scene, qapp):
    # Idle STIPA has no device stage payload yet; the selected measurement mode
    # must define the stage count (quick = 15, complete = 101) instead of a
    # hardcoded 101 that made the quick page look like the 101-stage mode.
    scene = feature_scene(
        {"kind": "stipa", "title": "Experimental STIPA", "chartRevision": 1,
         "scalarRows": []},
        workspace={"featureId": "stipa_experimental", "measurementMode": "quick"})
    stipa = scene.find("chartStipa")
    assert stipa is not None
    assert int(stipa.property("stageTotal")) == 15
    assert int(stipa.property("completedStages")) == 0
    assert float(stipa.property("progressValue")) == 0.0
    digits = scene.find("stipaProgressValue")
    area = find_visual(stipa, "stipaProgressArea")
    assert digits is not None and digits.property("text") == "0 / 15"
    # Idle keeps the existing 0 / total display: no result yet, so it stays visible.
    assert area is not None and area.property("visible") is True
    assert digits.property("visible") is True
    # Switching back to complete mode makes the same idle chart show 101 stages.
    scene.app.set_workspace(measurementMode="complete")
    pump(qapp, 0.2)
    assert int(stipa.property("stageTotal")) == 101
    assert digits.property("text") == "0 / 101"
    assert area.property("visible") is True
    assert scene.warnings == []