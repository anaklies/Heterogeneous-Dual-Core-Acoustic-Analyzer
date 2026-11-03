"""Application ViewModel for the SixMic3D acoustic analyzer (thin facade).

Chain: QML pages/charts -> AppViewModel -> BackendBridge (frozen adapter) -> DeviceSession -> PS gateway.

Responsibilities: presentation state, navigation, i18n, persisted UI settings,
developer-only fixture entry, PL measurement display, device recording,
report/export orchestration, diagnostics. It never re-implements backend
protocol/CRC/socket code and never fabricates live measurement values.
"""
from __future__ import annotations

import base64
import html
import json
import struct
import math
import re
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication, QImage
from PySide6.QtQml import QQmlApplicationEngine

from .plot_images import PlotImageProvider, heatmap_image

APP_ROOT = Path(__file__).resolve().parents[2]  # apps/sixmic-desktop
UI_DIR = APP_ROOT / "ui"
I18N_DIR = UI_DIR / "i18n"
CONFIG_DIR = UI_DIR / "config"
ASSETS_DIR = APP_ROOT / "assets"

# Left navigation is grouped by the prompt's EIGHT logical categories (the
# 频带、计权与统计 category is kept even though the recap omitted it: 5+9+5+12+5
# +6+4+5 = 51).  Each category is one page; its features are the page-scoped
# entry row, never an extra top-level menu.
# Features whose display is fed directly by the device liveFft stream.
LIVE_FRAME_FEATURES = {"fft", "io_pcm", "stft", "levels_core", "levels_extended"}

PAGES = [
    {"id": "overview", "icon": "device-desktop", "labelKey": "nav.overview"},
    {"id": "time", "icon": "audio-waveform", "labelKey": "nav.category_acq"},
    {"id": "spectrum", "icon": "chart-line", "labelKey": "nav.category_spectrum"},
    {"id": "bands", "icon": "chart-bar", "labelKey": "nav.category_bands"},
    {"id": "periodic", "icon": "wave-sine", "labelKey": "nav.category_periodic"},
    {"id": "multichannel", "icon": "git-compare", "labelKey": "nav.category_channels"},
    {"id": "events", "icon": "bell-ringing", "labelKey": "nav.category_events"},
    {"id": "room", "icon": "building", "labelKey": "nav.category_room"},
    {"id": "recording", "icon": "folder", "labelKey": "nav.recording"},
]

BOTTOM_PAGES = [
    {"id": "diagnostics", "icon": "activity", "labelKey": "nav.diagnostics"},
    {"id": "settings", "icon": "settings", "labelKey": "nav.settings"},
    {"id": "about", "icon": "info-circle", "labelKey": "nav.about"},
]

DEFAULT_SETTINGS = {
    "language": "zh",
    "themeMode": "dark",
    "host": "192.168.10.2",
    "controlPort": 48120,
    "binaryPort": 48121,
    "autoReconnect": True,
    "uiScale": 1.0,
    "fontScale": 1.0,
    "nativeInstrumentUiApplied": True,
    "presentation75Applied": False,
    "lineWidth": 1.6,
    "gridStrength": "normal",
    "timeWindowSeconds": 2.0,
    "frequencyAxis": "log",
    "refreshHz": 15,
    "stackedWaveform": True,
    "showChannelLabels": True,
    "lastOpenDirectory": "",
    "lastExportDirectory": "",
    "reportTitle": "",
    "reportNote": "",
    "reportAuthor": "",
    "navCollapsed": False,
    "inspectorCollapsed": True,
    "timelineVisible": True,
    "spectrumChannel": 0,
    "spectrumKind": "fft",
    "spectrumNfft": 2048,
    "stftPalette": "viridis",
    "pairFirst": 0,
    "pairSecond": 1,
    "windowX": 0,
    "windowY": 0,
    "windowWidth": 1920,
    "windowHeight": 1080,
    "windowMaximized": True,
}

APP_NAME_ZH = "echo"
APP_NAME_EN = "echo"
AUTHORS = "刘珉志、孟德旭"
SCHOOL = "黑龙江大学"
VERSION = "1.0.0-rc1"
BUILD_DATE = "2026-10-24"


def _now() -> float:
    return time.monotonic()


def _downsample(values: list[float], max_points: int) -> list[float]:
    """Peak-preserving display downsample (hot path for live telemetry).

    Avoids per-bucket slicing and max(key=abs) because this runs for six
    12000-sample rings on every telemetry refresh; a tight scan keeps it ~2x
    faster with identical output."""
    count = len(values)
    if not count:
        return []
    if count <= max_points:
        return [round(value, 6) for value in values]
    stride = count / max_points
    out: list[float] = []
    for index in range(max_points):
        start = int(index * stride)
        end = int((index + 1) * stride)
        if end <= start:
            end = start + 1
        best = values[start]
        best_abs = best if best >= 0 else -best
        position = start + 1
        while position < end:
            value = values[position]
            magnitude = value if value >= 0 else -value
            if magnitude > best_abs:
                best = value
                best_abs = magnitude
            position += 1
        out.append(round(best, 6))
    return out


def user_data_root() -> Path:
    import os
    override = os.environ.get("SIXMIC_USER_DATA_DIR")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return Path(base) / "SixMic3D"
    return Path.home() / "AppData" / "Local" / "SixMic3D"


class AppViewModel(QObject):
    dataChanged = Signal()
    featureChanged = Signal()
    featureEntriesChanged = Signal()
    pageChanged = Signal()
    languageChanged = Signal()
    navigationChanged = Signal()
    stateChanged = Signal()
    toastChanged = Signal()
    errorRaised = Signal(str)
    operationFinished = Signal(str)
    uiReloadRequested = Signal()
    screenshotRequested = Signal(str)
    reportImagesReady = Signal(str)
    _exportReady = Signal(str)
    _liveFftReady = Signal(object)
    _liveFftState = Signal(object)

    def __init__(self, bridge: Any, theme: Any,
                 image_provider: PlotImageProvider,
                 engine: QQmlApplicationEngine | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._live_fft_worker=None;self._live_fft_key=None;self._live_fft_retry=0.0
        self._live_fft_frames=0;self._live_fft_started=0.0;self._live_fft_max_dispatch_ms=0.0
        self._live_fft_coalesced=0
        self._live_fft_failures=0
        self._live_fft_fail_retry=0.0
        self._live_subscription_suspended=False
        self._wave_last_live_sample=None
        self._liveFftReady.connect(self._on_live_fft_ready);self._liveFftState.connect(self._on_live_fft_state)
        from concurrent.futures import ThreadPoolExecutor
        self._export_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="echo-export")
        self._pending_event_exports = set()
        self._export_pending = 0
        self._exports_closed = False
        self._exportReady.connect(self._on_export_ready)
        self.bridge = bridge
        self.theme = theme
        self.images = image_provider
        self.engine = engine
        self.user_root = user_data_root()
        for name in ("logs", "exports", "recordings", "events", "ui", "reports", "screenshots"):
            (self.user_root / name).mkdir(parents=True, exist_ok=True)
        self.settings_path = self.user_root / "ui" / "ui_settings.json"
        self._settings_migrated = False
        self._settings = self._load_settings()
        if self._settings_migrated:
            try:
                self._save_settings()
            except Exception:  # noqa: BLE001 - settings persist is best effort
                pass
        self._apply_theme_mode()
        self._language = str(self._settings.get("language", "zh"))
        self._translations = self._load_translations()
        self._current_page = "overview"
        self._nav_collapsed = bool(self._settings.get("navCollapsed", False))
        self._inspector_collapsed = bool(self._settings.get("inspectorCollapsed", False))
        self._timeline_visible = bool(self._settings.get("timelineVisible", True))
        self._inspector_tab = 0
        self._page_scroll = 0

        self._connection = {"state": "disconnected", "host": self._settings["host"],
                            "controlPort": self._settings["controlPort"],
                            "binaryPort": self._settings["binaryPort"],
                            "error": None, "since": _now()}
        self._capabilities: dict[str, Any] = {}
        self._device: dict[str, Any] = {}
        self._hello: dict[str, Any] = {}
        self._status: dict[str, Any] = {}
        self._source = "none"
        self._source_detail: dict[str, Any] = {}
        self._last_frame: dict[str, Any] | None = None
        self._frame_time = 0.0
        self._frame_count = 0
        self._audio_chunk_count = 0
        self._last_snapshot: dict[str, Any] | None = None
        self._audio_meta: dict[str, Any] = {}
        self._wave_ring: list[list[float]] = [[] for _ in range(6)]
        self._wave_indexes: list[int] = []
        # Bumped whenever the waveform rings change; timeDomainData is
        # rebuilt once per revision instead of once per QML binding read.
        self._wave_revision = 0
        self._time_domain_cache: tuple[Any, dict[str, Any]] | None = None
        self._wave_start = ""
        self._gaps: list[dict[str, Any]] = []
        self._jobs: dict[str, dict[str, Any]] = {}
        self._events: list[dict[str, Any]] = []
        self._event_selected = ""
        self._event_download_inflight = ""
        self._event_download_retry_at = 0.0
        self._event_clear_pending = False
        self._event_auto_download_suspended = False
        self._recording: dict[str, Any] = {"state": "idle", "records": 0, "bytes": 0}
        self._fixture = None
        self._fixture_active = False
        self._replay = None
        self._replay_manifest_path: str = ""
        self._replay_ring: list[list[float]] = [[] for _ in range(6)]
        self._replay_position = 0.0
        self._replay_duration = 0.0
        self._playback_state = "stopped"
        self._playback_timer = QTimer(self)
        self._playback_timer.setInterval(40)
        self._playback_timer.timeout.connect(self._pump_playback)
        self._analysis: dict[str, Any] = {}
        self._service_snapshot: dict[str, Any] = {}
        self._live_subscription_requested = False
        self._analysis_revision = 0
        self._monitor = {
            "active": False,
            "phase": "idle",          # idle | learning | locked | monitoring | stopped
            "learningProgress": 0.0,
            "backgroundLocked": False,
            "startedMonotonicNs": "0",
            "stoppedMonotonicNs": "0",
            "eventsSeen": 0,
            "newEventId": "",
            "settings": {
                "thresholdDb": -38.0,
                "bandLowHz": 300.0,
                "bandHighHz": 6000.0,
                "preSeconds": 2.0,
                "postSeconds": 3.0,
                "minEventGapSeconds": 1.5,
            },
            "settingsApplied": False,
            "noteKey": "events.monitor.local_only",
        }
        self._last_feature_event_poll=0.0
        self._monitor_timer = QTimer(self)
        self._monitor_timer.setInterval(500)
        self._monitor_timer.timeout.connect(self._tick_monitor)
        self._monitor_seen_ids: set[str] = set()
        self._monitor_learning_frames = 0
        self._toast = {"visible": False, "level": "info", "title": "", "detail": ""}
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._hide_toast)
        self._notifications: list[dict[str, Any]] = []
        self._busy = False
        self._busy_text = ""
        self._pending_ops: dict[str, str] = {}
        self._control_held = False
        self._settings_apply_message = ""
        self._feature_runtime: dict[str, dict[str, Any]] = {}
        self._feature_api: dict[str, Any] = {
            "available": False, "version": "", "features": [],
            "selected": "", "params": "{}", "job": None, "result": None,
            "words": [], "message": "", "busy": False,
        }
        self._feature_local: list[dict[str, Any]] = []
        self._feature_ui: dict[str, Any] = {"features": []}
        try:
            self._feature_ui = json.loads((CONFIG_DIR / "feature_page_map.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        self._feature_panel_open = False
        self._feature_chart: dict[str, Any] = {}
        self._feature_api_retry_count = 0
        self._feature_api_retry_pending = False

        try:
            local = json.loads((CONFIG_DIR / "feature_calls.json").read_text(encoding="utf-8"))
            self._feature_local = list(local.get("features") or [])
        except (OSError, ValueError):
            self._feature_local = []

        # echo-features-1 workspace facade (Lead-owned).  Measurement parameters
        # stay fixed and hidden; only documented workflow confirmations appear.
        self._feature_facade = None
        self._feature_facade_error = ""
        try:
            from .feature_workspace import FeatureWorkspaceFacade
            self._feature_facade = FeatureWorkspaceFacade(
                CONFIG_DIR / "feature_view_spec.json", self.bridge, self.images,
                language=lambda: self._language, notify=self._notify)
            self._feature_facade.attach_change_callback(self._on_feature_changed)
        except Exception as exc:  # noqa: BLE001 - degrade to explicit status
            self._feature_facade_error = f"{type(exc).__name__}: {exc}"[:240]
        self._feature_timer = QTimer(self)
        self._feature_timer.setInterval(50)
        self._feature_timer.timeout.connect(self._tick_feature_runtime)
        self._feature_timer.start()

        self._settings_dirty = False
        self._restart_required = False
        self._ui_scale_changed = False
        self._pending_count = 0
        self._req_counter = 0
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(500)
        self._status_timer.timeout.connect(self._tick_status)
        self._status_timer.start()
        self._emit_timer = QTimer(self)
        self._emit_timer.setSingleShot(True)
        self._emit_timer.setInterval(16)
        self._emit_timer.timeout.connect(self.dataChanged.emit)
        # Live frames arrive faster than the UI can (or should) redraw.
        # featureChanged is coalesced to the configured refresh budget while
        # structural changes still flush immediately (see _queue_feature_changed).
        self._feature_emit_timer = QTimer(self)
        self._feature_emit_timer.setSingleShot(True)
        self._feature_emit_timer.timeout.connect(self._flush_feature_changed)
        self._feature_emit_last = 0.0
        self._feature_emit_signature = None
        self._feature_entries_sig = None
        self._feature_emit_pending = False
        # Persist the last live charts occasionally so a page leave / app exit
        # can restore them as paused history next time.
        self._history_timer = QTimer(self)
        self._history_timer.setSingleShot(True)
        self._history_timer.setInterval(2500)
        self._history_timer.timeout.connect(self._persist_feature_history)
        self._features_json = self._read_bridge_features()
        self._features = self._load_feature_catalog()
        self._feature_map = self._load_feature_map()
        self._page_features = self._build_page_features()
        self._diagnostics_cache: dict[str, Any] = {}
        self._report_path = ""
        self._last_error: dict[str, Any] | None = None
        self._last_operation: dict[str, Any] | None = None
        self._wire_bridge()
        self._recompute_overview()
        self._restore_feature_history()

    # ------------------------------------------------------------------
    # bridge wiring
    # ------------------------------------------------------------------
    def _wire_bridge(self) -> None:
        bridge = self.bridge
        bridge.connectionChanged.connect(self._on_connection)
        bridge.capabilitiesChanged.connect(self._on_capabilities)
        bridge.operationUpdated.connect(self._on_operation)
        bridge.frameAvailable.connect(self._on_frame)
        bridge.audioChunkAvailable.connect(self._on_audio)
        bridge.serviceResultAvailable.connect(self._on_service)
        bridge.eventAdded.connect(self._on_event_added)
        bridge.jobUpdated.connect(self._on_job)
        bridge.recordingChanged.connect(self._on_recording)
        bridge.diagnosticAdded.connect(self._on_diagnostic)
        bridge.streamGap.connect(self._on_gap)
        bridge.playbackChunkAvailable.connect(self._on_playback_chunk)
        bridge.requestFinished.connect(self._on_request_finished)
        bridge.backendError.connect(self._on_backend_error)
        try:
            self._features_json = bridge.featureCatalogJson
        except Exception:
            self._features_json = ""

    # ------------------------------------------------------------------
    # i18n / settings
    # ------------------------------------------------------------------
    def _load_translations(self) -> dict[str, dict[str, str]]:
        merged: dict[str, dict[str, str]] = {"zh": {}, "en": {}}
        if I18N_DIR.is_dir():
            for path in sorted(I18N_DIR.glob("*.json")):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                for language in ("zh", "en"):
                    section = payload.get(language)
                    if isinstance(section, dict):
                        merged[language].update({str(k): str(v) for k, v in section.items()})
        return merged

    def _load_settings(self) -> dict[str, Any]:
        values = dict(DEFAULT_SETTINGS)
        try:
            payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                for key, value in payload.items():
                    if key in values:
                        values[key] = value
        except (OSError, ValueError):
            pass
        # Retain the old migration marker for settings compatibility. Native
        # system DPI is authoritative; no second75% font/app scale is applied.
        if not values.get("presentation75Applied"):
            values["uiScale"] = 1.0
            values["fontScale"] = 1.0
            values["presentation75Applied"] = True
            self._settings_migrated = True
        return values

    def _save_settings(self) -> bool:
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            self.settings_path.write_text(
                json.dumps(self._settings, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
            return True
        except OSError as exc:
            self._settings_apply_message = f"settings.write_failed: {exc}"
            self._restart_required = True
            self._notify("error", "settings.write_failed", str(exc))
            self._schedule_changed()
            return False

    def _apply_theme_mode(self) -> None:
        self.theme.set_mode(str(self._settings.get("themeMode", "dark")))
        try:
            self.theme.set_font_scale(float(self._settings.get("fontScale", 1.0)))
        except (TypeError, ValueError):
            pass

    def _read_bridge_features(self) -> str:
        try:
            return str(self.bridge.featureCatalogJson or "")
        except Exception:
            return ""

    def _load_feature_catalog(self) -> list[dict[str, Any]]:
        try:
            payload = json.loads(self._features_json or "{}")
            features = payload.get("features")
            if isinstance(features, list) and features:
                return features
        except ValueError:
            pass
        repo = APP_ROOT.parent.parent
        path = repo / "interfaces" / "pc_backend_v1" / "features" / "FEATURE_CATALOG.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return list(payload.get("features") or [])
        except (OSError, ValueError):
            return []

    def _load_feature_map(self) -> dict[str, Any]:
        path = CONFIG_DIR / "feature_ui_map.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"pages": {}, "features": {}}

    def _build_page_features(self) -> dict[str, list[dict[str, Any]]]:
        by_page: dict[str, list[dict[str, Any]]] = {page["id"]: [] for page in PAGES + BOTTOM_PAGES}
        features_map = self._feature_map.get("features") or {}
        catalog = {item.get("featureId"): item for item in self._features}
        for feature_id, mapping in features_map.items():
            page = str(mapping.get("page", "overview"))
            catalog_item = catalog.get(feature_id) or {}
            entry = {
                "featureId": feature_id,
                "page": page,
                "sectionKey": mapping.get("section", ""),
                "role": mapping.get("role", "primary"),
                "status": catalog_item.get("status", "not_ready"),
                "displayName": catalog_item.get("displayName", feature_id),
                "tier": catalog_item.get("tier", ""),
                "units": catalog_item.get("units", ""),
                "qualityNote": catalog_item.get("qualityNote", ""),
                "reason": catalog_item.get("statusReason", ""),
            }
            by_page.setdefault(page, []).append(entry)
        for page_id, entries in by_page.items():
            entries.sort(key=lambda item: (item["role"] != "primary", item["featureId"]))
        return by_page

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _notify(self, level: str, title: str, detail: str = "") -> None:
        self._toast = {"visible": True, "level": level, "title": title, "detail": detail}
        self._notifications.insert(0, {"level": level, "title": title,
                                       "detail": detail, "time": _now()})
        self._notifications = self._notifications[:200]
        self._toast_timer.start(4200)
        self.toastChanged.emit()

    def _hide_toast(self) -> None:
        self._toast = dict(self._toast, visible=False)
        self.toastChanged.emit()

    def _schedule_changed(self) -> None:
        if self._emit_timer.isActive():
            return
        # While live frames stream in, telemetry/status bindings do not need
        # 60 Hz refresh; cap the shared dataChanged rate to the display budget.
        live = self._live_fft_worker is not None and self._live_fft_worker.is_alive()
        self._emit_timer.start(66 if live else 16)

    def _next_request(self, op: str) -> str:
        self._req_counter += 1
        request_id = f"ui-{self._req_counter:06d}"
        self._pending_ops[request_id] = op
        return request_id

    def _set_busy(self, busy: bool, text: str = "") -> None:
        self._busy = busy
        self._busy_text = text
        self.stateChanged.emit()

    def _now_iso(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S")

    # ------------------------------------------------------------------
    # QML properties - shell
    # ------------------------------------------------------------------
    @Property(str, notify=dataChanged)
    def appName(self) -> str:  # noqa: N802
        return APP_NAME_ZH if self._language == "zh" else APP_NAME_EN

    @Property(str, notify=dataChanged)
    def version(self) -> str:
        return VERSION

    @Property(str, notify=dataChanged)
    def buildDate(self) -> str:  # noqa: N802
        return BUILD_DATE

    @Property(str, notify=dataChanged)
    def language(self) -> str:
        return self._language

    @Property(str, notify=dataChanged)
    def themeMode(self) -> str:  # noqa: N802
        return str(self._settings.get("themeMode", "dark"))

    @Property(bool, notify=dataChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=dataChanged)
    def busyText(self) -> str:  # noqa: N802
        return self._busy_text

    @Property("QVariantMap", notify=toastChanged)
    def toast(self) -> dict[str, Any]:
        return dict(self._toast)

    @Property("QVariantList", notify=dataChanged)
    def notifications(self) -> list[dict[str, Any]]:
        return list(self._notifications[:80])

    @Property(str, notify=pageChanged)
    def currentPage(self) -> str:  # noqa: N802
        return self._current_page

    @Property("QVariantList", notify=dataChanged)
    def navPages(self) -> list[dict[str, Any]]:  # noqa: N802
        entries = []
        for page in PAGES:
            entry = dict(page)
            entry["label"] = self.t(page["labelKey"])
            entry["enabled"] = True
            entry["badge"] = ""
            entries.append(entry)
        return entries

    @Property("QVariantList", notify=dataChanged)
    def bottomPages(self) -> list[dict[str, Any]]:  # noqa: N802
        entries = []
        for page in BOTTOM_PAGES:
            entry = dict(page)
            entry["label"] = self.t(page["labelKey"])
            entries.append(entry)
        return entries

    @Property(bool, notify=dataChanged)
    def navCollapsed(self) -> bool:  # noqa: N802
        return self._nav_collapsed

    @Property(bool, notify=dataChanged)
    def inspectorCollapsed(self) -> bool:  # noqa: N802
        return self._inspector_collapsed

    @Property(bool, notify=dataChanged)
    def timelineVisible(self) -> bool:  # noqa: N802
        return self._timeline_visible

    @Property(int, notify=dataChanged)
    def inspectorTab(self) -> int:  # noqa: N802
        return self._inspector_tab

    @Property(str, notify=dataChanged)
    def connectionStateLabel(self) -> str:  # noqa: N802
        return self.t("conn." + str(self._connection.get("state", "disconnected")))

    @Property(bool, notify=dataChanged)
    def controlHeld(self) -> bool:  # noqa: N802
        return self._control_held

    @Slot()
    def dismissToast(self) -> None:  # noqa: N802
        self._toast = dict(self._toast, visible=False)
        self._toast_timer.stop()
        self.toastChanged.emit()

    @Property(str, notify=dataChanged)
    def pageTitle(self) -> str:  # noqa: N802
        page = self._page_meta(self._current_page)
        return self.t(page["labelKey"]) if page else self.t("nav.overview")

    @Property(str, notify=dataChanged)
    def pageSubtitle(self) -> str:  # noqa: N802
        return self.t("page." + self._current_page + ".subtitle")

    @Property(str, notify=dataChanged)
    def connectionState(self) -> str:  # noqa: N802
        return str(self._connection.get("state", "disconnected"))

    @Property("QVariantMap", notify=dataChanged)
    def connection(self) -> dict[str, Any]:
        return dict(self._connection)

    @Property("QVariantMap", notify=dataChanged)
    def device(self) -> dict[str, Any]:
        return dict(self._device)

    @Property("QVariantMap", notify=dataChanged)
    def capabilities(self) -> dict[str, Any]:
        return dict(self._capabilities)

    @Property("QVariantMap", notify=dataChanged)
    def status(self) -> dict[str, Any]:
        return dict(self._status)

    @Property(str, notify=dataChanged)
    def dataSource(self) -> str:  # noqa: N802
        return self._source

    @Property(str, notify=dataChanged)
    def dataSourceLabel(self) -> str:  # noqa: N802
        return self.t("source." + self._source.replace("-", "_"))

    @Property("QVariantMap", notify=dataChanged)
    def streamMeta(self) -> dict[str, Any]:  # noqa: N802
        meta = dict(self._source_detail)
        age = (_now() - self._frame_time) if self._frame_time else None
        meta["freshnessSeconds"] = None if age is None else round(age, 2)
        meta["stale"] = bool(age is not None and age > 3.0)
        meta["frameCount"] = self._frame_count
        meta["gaps"] = list(self._gaps[-8:])
        return meta

    @Property(int, notify=dataChanged)
    def frameCount(self) -> int:  # noqa: N802
        return self._frame_count

    @Property(int, notify=dataChanged)
    def audioChunkCount(self) -> int:  # noqa: N802
        return self._audio_chunk_count

    @Property("QVariantMap", notify=dataChanged)
    def featureApi(self) -> dict[str, Any]:  # noqa: N802
        data = dict(self._feature_api)
        data["features"] = list(self._feature_api.get("features") or [])
        data["words"] = list(self._feature_api.get("words") or [])
        return data

    @Property("QVariantList", notify=dataChanged)
    def featureCatalogLocal(self) -> list[dict[str, Any]]:  # noqa: N802
        return list(self._feature_local)

    @Property("QVariantList", notify=dataChanged)
    def featureRibbon(self) -> list[dict[str, Any]]:  # noqa: N802
        page = str(self.currentPage)
        out = []
        ids = [f.get("featureId") for f in self._feature_ui.get("features", [])
               if f.get("page") == page]
        server = {str(f.get("featureId")): f for f in (self._feature_api.get("features") or [])}
        for fid in ids:
            local = next((f for f in self._feature_ui.get("features", [])
                          if f.get("featureId") == fid), {})
            meta = dict(local)
            if fid in server:
                meta["availableOnDevice"] = True
            out.append(meta)
        return out

    @Property(bool, notify=dataChanged)
    def featurePanelOpen(self) -> bool:  # noqa: N802
        return self._feature_panel_open

    @Property("QVariantMap", notify=dataChanged)
    def featureChart(self) -> dict[str, Any]:  # noqa: N802
        return dict(self._feature_chart)

    @Slot(str)
    def openFeature(self, featureId: str) -> None:  # noqa: N802
        self.selectFeature(str(featureId))
        self._feature_panel_open = True
        self._feature_chart = {}
        self._schedule_changed()

    @Slot()
    def closeFeaturePanel(self) -> None:  # noqa: N802
        self._feature_panel_open = False
        self._schedule_changed()

    @Property("QVariantList", notify=dataChanged)
    def featureCatalog(self) -> list[dict[str, Any]]:  # noqa: N802
        return list(self._features)

    @Property("QVariantMap", notify=dataChanged)
    def featureSummary(self) -> dict[str, Any]:  # noqa: N802
        summary = {"total": len(self._features), "available": 0, "experimental": 0,
                   "not_ready": 0, "unsupported": 0}
        for feature in self._features:
            status = str(feature.get("status", "not_ready"))
            if status in summary:
                summary[status] = summary.get(status, 0) + 1
        return summary

    @Property("QVariantList", notify=dataChanged)
    def pageFeatures(self) -> list[dict[str, Any]]:  # noqa: N802
        return list(self._page_features.get(self._current_page, []))

    @Property("QVariantMap", notify=dataChanged)
    def lastError(self) -> dict[str, Any]:  # noqa: N802
        return dict(self._last_error or {})

    @Property("QVariantMap", notify=dataChanged)
    def settings(self) -> dict[str, Any]:
        return dict(self._settings)

    @Property(float, notify=dataChanged)
    def uiScale(self) -> float:  # noqa: N802
        return float(self._settings.get("uiScale", 1.0))

    @Property(float, notify=dataChanged)
    def fontScale(self) -> float:  # noqa: N802
        return float(self._settings.get("fontScale", 1.0))

    @Property(bool, notify=dataChanged)
    def fixtureActive(self) -> bool:  # noqa: N802
        return self._fixture_active

    def _page_meta(self, page_id: str) -> dict[str, Any] | None:
        for page in PAGES + BOTTOM_PAGES:
            if page["id"] == page_id:
                return page
        return None

    # ------------------------------------------------------------------
    # i18n invokables
    # ------------------------------------------------------------------
    @Slot(str, result=str)
    def t(self, key: str) -> str:
        section = self._translations.get(self._language) or {}
        if key in section:
            return section[key]
        fallback = self._translations.get("zh", {})
        return fallback.get(key, key)

    @Slot("QVariant", result=str)
    def formatNumber(self, value: Any) -> str:  # noqa: N802
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "—"
        if math.isnan(number) or math.isinf(number):
            return "—"
        if number == 0:
            return "0"
        magnitude = abs(number)
        if magnitude >= 1e5 or magnitude < 1e-3:
            return f"{number:.3e}"
        if magnitude >= 100:
            return f"{number:.1f}"
        return f"{number:.3f}"

    @Slot(str, result=str)
    def formatDb(self, value: Any) -> str:  # noqa: N802
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "—"
        if math.isnan(number) or math.isinf(number):
            return "—"
        return f"{number:.1f} dB"

    @Slot(str)
    def setLanguage(self, language: str) -> None:  # noqa: N802
        if language not in ("zh", "en") or language == self._language:
            return
        self._language = language
        self._settings["language"] = language
        self._save_settings()
        self.languageChanged.emit()
        self.featureChanged.emit()
        self.uiReloadRequested.emit()

    @Slot(str)
    def toggleLanguage(self) -> None:
        self.setLanguage("en" if self._language == "zh" else "zh")

    @Slot(str)
    def setThemeMode(self, mode: str) -> None:  # noqa: N802
        if mode not in ("light", "dark", "system"):
            return
        self._settings["themeMode"] = mode
        self._save_settings()
        self._apply_theme_mode()
        self._schedule_changed()

    def _deactivate_page_features(self, page_id: str) -> None:
        """Stop work owned by a page without touching shared P0 subscriptions."""
        if page_id == "events" and self._monitor.get("active"):
            self.stopMonitor()
        for feature_id, state in list(self._feature_runtime.items()):
            if state.get("page") == page_id and state.get("state") in ("running", "starting"):
                state["state"] = "stopped"
                state["confirmed"] = True
        self._schedule_changed()

    def _activate_page_features(self, page_id: str) -> None:
        for item in self.pageFeatures:
            if item.get("page") == page_id:
                self._feature_runtime.setdefault(str(item.get("featureId")), {
                    "page": page_id, "state": "idle", "confirmed": False})
        self._schedule_changed()

    @Slot(str, result="QVariantMap")
    def activateFeature(self, featureId: str) -> dict[str, Any]:  # noqa: N802
        """Frontend-only lifecycle facade; does not imply a gateway command."""
        item = next((f for f in self.featureCatalog
                     if str(f.get("featureId")) == str(featureId)), None)
        if item is None:
            return {"ok": False, "reasonKey": "status.not_connected"}
        self._feature_runtime[str(featureId)] = {
            "page": self.currentPage, "state": "running", "confirmed": False}
        self._schedule_changed()
        return {"ok": True, "state": "running", "confirmed": False,
                "noteKey": "feature.frontend_facade_only"}

    @Slot(str, result=bool)
    def deactivateFeature(self, featureId: str) -> bool:  # noqa: N802
        state = self._feature_runtime.get(str(featureId))
        if state is None:
            return False
        state["state"] = "stopped"
        state["confirmed"] = True
        self._schedule_changed()
        return True

    @Slot(str)
    def setCurrentPage(self, page_id: str) -> None:  # noqa: N802
        if self._page_meta(page_id) is None or page_id == self._current_page:
            return
        previous_page = self._current_page
        self._deactivate_page_features(previous_page)
        self._current_page = page_id
        self._page_scroll = 0
        self.pageChanged.emit()
        self._activate_page_features(page_id)
        if self._feature_facade is not None:
            self._feature_facade.page_changed(page_id)
        self._schedule_changed()

    @Slot(bool)
    def setNavCollapsed(self, collapsed: bool) -> None:  # noqa: N802
        self._nav_collapsed = bool(collapsed)
        self._settings["navCollapsed"] = self._nav_collapsed
        self._save_settings()
        self._schedule_changed()

    @Slot(bool)
    def setInspectorCollapsed(self, collapsed: bool) -> None:  # noqa: N802
        self._inspector_collapsed = bool(collapsed)
        self._settings["inspectorCollapsed"] = self._inspector_collapsed
        self._save_settings()
        self._schedule_changed()

    @Slot(bool)
    def setTimelineVisible(self, visible: bool) -> None:  # noqa: N802
        self._timeline_visible = bool(visible)
        self._settings["timelineVisible"] = self._timeline_visible
        self._save_settings()
        self._schedule_changed()

    # ------------------------------------------------ feature API (echo-features-1)
    def _feature_message(self, text: str) -> None:
        self._feature_api["message"] = text
        self._schedule_changed()

    def _feature_bridge(self):
        for name in ("listFeatures", "startFeature", "stopFeature", "getFeature",
                     "getFeatureResult", "releaseFeatureResult"):
            if not hasattr(self.bridge, name):
                self._feature_api["message"] = self.t("features.api_missing")
                self._feature_api["available"] = False
                self._schedule_changed()
                return None
        return self.bridge

    @Slot()
    def listFeatures(self) -> None:  # noqa: N802
        bridge = self._feature_bridge()
        if bridge is None:
            return
        self._feature_api["busy"] = True
        self._feature_message(self.t("features.listing"))
        try:
            bridge.listFeatures()
        except RuntimeError:
            self._feature_api["busy"] = False
            self._feature_message(self.t("features.not_connected"))

    @Slot(str)
    def selectFeature(self, featureId: str) -> None:  # noqa: N802
        feature = next((f for f in (self._feature_api.get("features") or [])
                        if str(f.get("featureId")) == str(featureId)), None)
        if feature is None:
            feature = next((f for f in self._feature_local
                            if str(f.get("featureId")) == str(featureId)), None)
        if feature is None:
            return
        self._feature_api["selected"] = str(featureId)
        self._feature_api["selectedName"] = str(feature.get("name") or featureId)
        self._feature_chart = {}
        local = next((f for f in self._feature_ui.get("features", [])
                      if str(f.get("featureId")) == str(featureId)), None)
        defaults = (local or feature).get("defaultParams")
        self._feature_api["params"] = json.dumps(defaults or {}, ensure_ascii=False, indent=2)
        self._feature_api["message"] = ""
        self._schedule_changed()

    @Slot(str)
    def setFeatureParams(self, text: str) -> None:  # noqa: N802
        self._feature_api["params"] = str(text or "{}")
        self._schedule_changed()

    @Slot()
    def startSelectedFeature(self) -> None:  # noqa: N802
        bridge = self._feature_bridge()
        if bridge is None:
            return
        feature_id = str(self._feature_api.get("selected") or "")
        if not feature_id:
            self._feature_message(self.t("features.select_first"))
            return
        try:
            params = json.loads(self._feature_api.get("params") or "{}")
        except ValueError:
            self._feature_message(self.t("features.bad_params"))
            return
        if not isinstance(params, dict):
            self._feature_message(self.t("features.bad_params"))
            return
        self._feature_api["busy"] = True
        self._feature_message(self.t("features.starting"))
        try:
            bridge.startFeature(feature_id, json.dumps(params, ensure_ascii=False))
        except RuntimeError:
            self._feature_api["busy"] = False
            self._feature_message(self.t("features.not_connected"))

    @Slot()
    def stopActiveFeature(self) -> None:  # noqa: N802
        bridge = self._feature_bridge()
        job = self._feature_api.get("job") or {}
        job_id = str(job.get("jobId") or "")
        if bridge is None or not job_id:
            return
        self._feature_api["busy"] = True
        self._feature_message(self.t("features.stopping"))
        try:
            bridge.stopFeature(job_id)
        except RuntimeError:
            self._feature_api["busy"] = False

    @Slot()
    def refreshFeatureJob(self) -> None:  # noqa: N802
        bridge = self._feature_bridge()
        job = self._feature_api.get("job") or {}
        job_id = str(job.get("jobId") or "")
        if bridge is None or not job_id:
            return
        try:
            bridge.getFeature(job_id)
        except RuntimeError:
            pass

    @Slot()
    def fetchFeatureResult(self) -> None:  # noqa: N802
        bridge = self._feature_bridge()
        job = self._feature_api.get("job") or {}
        job_id = str(job.get("jobId") or "")
        if bridge is None or not job_id:
            return
        self._feature_api["busy"] = True
        self._feature_message(self.t("features.fetching"))
        try:
            bridge.getFeatureResult(job_id)
        except RuntimeError:
            self._feature_api["busy"] = False

    @Slot()
    def releaseFeatureResult(self) -> None:  # noqa: N802
        bridge = self._feature_bridge()
        result = self._feature_api.get("result") or {}
        ref = result.get("dataRef") or {}
        handle = str(ref.get("handleId") or "")
        if bridge is None or not handle:
            return
        try:
            bridge.releaseFeatureResult(handle)
        except RuntimeError:
            pass

    @Slot()
    def saveFeatureResult(self) -> None:  # noqa: N802
        result = self._feature_api.get("result") or {}
        if not result:
            return
        try:
            out_dir = self.user_root / "features"
            out_dir.mkdir(parents=True, exist_ok=True)
            job_id = str(result.get("jobId") or "feature")
            (out_dir / (job_id + ".json")).write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")
            words = self._feature_api.get("words") or []
            (out_dir / (job_id + "-words.csv")).write_text(
                "index,uint32" + chr(10) + chr(10).join(f"{i},{w}" for i, w in enumerate(words)) + chr(10),
                encoding="utf-8")
            self._notify("info", self.t("features.saved"), str(out_dir))
        except OSError as exc:
            self._notify("error", self.t("features.save_failed"), str(exc)[:180])
    # ------------------------------------------------ echo-features-1 workspace
    # Fixed, hidden parameters: QML never edits measurement parameters.  Only
    # workflow confirmations (stimulus/chain/test-signal/reference actions) are
    # exposed through featureWorkspace.flow.
    def _on_feature_changed(self) -> None:
        self._schedule_changed()
        self._queue_feature_changed()
        if not self._history_timer.isActive():
            self._history_timer.start()

    def _feature_emit_interval(self) -> float:
        """Seconds between chart refreshes; honors settings.refreshHz (5..30 Hz)."""
        try:
            hz = float(self._settings.get("refreshHz") or 15.0)
        except (TypeError, ValueError):
            hz = 15.0
        hz = max(5.0, min(30.0, hz))
        return 1.0 / hz

    def _feature_struct_signature(self) -> Any:
        """Cheap signature of workspace transitions that must show immediately.

        Only real lifecycle changes belong here (open/close, job state, error,
        references, confirmations, stream activity).  Chart payload, progress,
        frame counters and messages are intentionally excluded so the throttle
        keeps live updates at the configured refresh rate instead of firing on
        every device frame.
        """
        facade = self._feature_facade
        if facade is None:
            return None
        runtime = getattr(facade, "_runtime", None)
        if runtime is None:
            return ("unavailable", str(getattr(facade, "_runtime_error", "")))
        fid = str(getattr(runtime, "_open_feature", "") or "")
        job = None
        try:
            if fid:
                job = runtime._active_feature_job(fid) or runtime._last_feature_job(fid)
        except Exception:  # noqa: BLE001
            job = None
        error = (getattr(runtime, "_errors", {}) or {}).get(fid) or {}
        try:
            live_requested = getattr(runtime, "_live_requested", set()) or set()
            # Continuous measurement recreates a job per result frame; the user
            # visible lifecycle stays \"running\" for as long as the owner is in the
            # live-requested set, so report that phase instead of per-frame job churn.
            if fid and fid in live_requested:
                state_phase = "stopping" if (job is not None and getattr(job, "stop_requested", False)) else "running"
            else:
                state_phase = str(getattr(job, "state", "")) if job is not None else ""
            return (
                fid, str(getattr(runtime, "_page", "")), str(getattr(runtime, "_background_feature", "")),
                bool(getattr(runtime, "_stream_active", False)),
                state_phase,
                bool(getattr(job, "stop_requested", False)) if job is not None else False,
                str(error.get("code") or ""), str(error.get("reason") or ""),
                len((getattr(runtime, "_variants", {}) or {}).get(fid) or []),
                tuple(sorted(getattr(runtime, "_references", {}) or {})),
                tuple(sorted(getattr(runtime, "_auto_stopped", set()) or ())),
                len(getattr(runtime, "_confirmations", {}) or {}),
            )
        except Exception:  # noqa: BLE001 - notification must never break the UI
            return None

    def _feature_entries_signature(self) -> Any:
        """Signature of the data the feature tab row actually renders.

        The tab row is rebuilt only when the catalog/availability/language
        changes; rebuilding it on every live chart update destroyed and
        recreated the tab buttons several times per second and swallowed
        real mouse clicks.
        """
        facade = self._feature_facade
        if facade is None:
            return None
        runtime = getattr(facade, "_runtime", None)
        if runtime is None:
            return ("unavailable", str(getattr(facade, "_runtime_error", "")), self._language)
        catalog = getattr(runtime, "catalog", None)
        try:
            return (
                getattr(catalog, "device_version", ""),
                getattr(catalog, "interface_version", ""),
                len(getattr(catalog, "features", {}) or {}),
                bool(getattr(runtime, "_connected", False)),
                bool(getattr(runtime, "_api_enabled", False)),
                self._language,
            )
        except Exception:  # noqa: BLE001
            return None

    def _emit_entries_if_changed(self) -> None:
        signature = self._feature_entries_signature()
        if signature != self._feature_entries_sig:
            self._feature_entries_sig = signature
            self.featureEntriesChanged.emit()

    def _queue_feature_changed(self) -> None:
        """Coalesce live-frame notifications while keeping the UI responsive.

        Live device frames used to emit featureChanged synchronously for every
        frame and each emission re-evaluated the whole QML binding graph.  Chart
        updates are now merged and emitted once per refresh budget while real
        lifecycle changes still emit immediately.
        """
        now = _now()
        interval = self._feature_emit_interval()
        signature = self._feature_struct_signature()
        previous_signature = self._feature_emit_signature
        if signature != previous_signature or (now - self._feature_emit_last) >= interval:
            self._feature_emit_pending = False
            self._feature_emit_signature = signature
            self._feature_emit_last = now
            self.featureChanged.emit()
            self._emit_entries_if_changed()
            return
        self._feature_emit_pending = True
        if not self._feature_emit_timer.isActive():
            delay_ms = int(max(0.016, interval - (now - self._feature_emit_last)) * 1000.0)
            self._feature_emit_timer.start(max(1, delay_ms))

    def _flush_feature_changed(self) -> None:
        if not self._feature_emit_pending:
            return
        self._feature_emit_pending = False
        self._feature_emit_last = _now()
        previous_signature = self._feature_emit_signature
        self._feature_emit_signature = self._feature_struct_signature()
        self.featureChanged.emit()
        self._emit_entries_if_changed()

    def _feature_history_path(self) -> Path:
        return self.user_root / "data" / "feature_history.json"

    def _persist_feature_history(self) -> None:
        """Store the latest live charts so they survive a page leave/app exit."""
        runtime = getattr(self._feature_facade, "_runtime", None)
        if runtime is None:
            return
        features: dict[str, Any] = {}
        try:
            for feature_id in list(LIVE_FRAME_FEATURES):
                result = runtime._results.get(feature_id) or {}
                chart = result.get("chart")
                if not isinstance(chart, dict) or not chart:
                    continue
                features[feature_id] = {"chart": chart,
                                       "sourceKind": str(result.get("sourceKind") or "pl-live")}
            if not features:
                return
            last_by_page = getattr(runtime, "_last_feature_by_page", {}) or {}
            payload = {"version": 1, "savedAt": time.time(),
                       "features": features,
                       "lastByPage": {str(k): str(v) for k, v in last_by_page.items()}}
            path = self._feature_history_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(".json.tmp")
            temp.write_text(json.dumps(payload, ensure_ascii=False, default=str),
                            encoding="utf-8")
            temp.replace(path)
        except (OSError, TypeError, ValueError):
            pass

    def _restore_feature_history(self) -> None:
        runtime = getattr(self._feature_facade, "_runtime", None)
        if runtime is None:
            return
        path = self._feature_history_path()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        features = payload.get("features") if isinstance(payload, dict) else None
        if not isinstance(features, dict):
            return
        for feature_id, entry in features.items():
            if isinstance(entry, dict):
                try:
                    runtime.restore_result(str(feature_id), entry)
                except Exception:  # noqa: BLE001 - history must not block startup
                    pass
        last_by_page = payload.get("lastByPage") if isinstance(payload, dict) else None
        if isinstance(last_by_page, dict):
            for page_id, feature_id in last_by_page.items():
                try:
                    runtime._last_feature_by_page[str(page_id)] = str(feature_id)
                except Exception:  # noqa: BLE001
                    pass

    def _tick_feature_runtime(self) -> None:
        if self._feature_facade is not None:
            self._feature_facade.tick()
            runtime=getattr(self._feature_facade,"_runtime",None)
            monitor=runtime._active_feature_job("event_trigger") if runtime else None
            now=time.monotonic()
            if self._connection.get("state")=="connected" and monitor and now-self._last_feature_event_poll>=1.0:
                self._last_feature_event_poll=now;self.listEvents()
            self._sync_live_fft()

    def _sync_live_fft(self) -> None:
        """Keep the direct live-frame stream in sync with the open workspace.

        The current PS gateway accepts only one subscribed binary connection per
        client: the bridge's resultWords/serviceSnapshot subscription and the
        direct liveFft stream cannot be active at the same time (the second
        binary connection is reset by the device).  The live frame path is
        therefore exclusive while a live feature workspace is open, and the
        bridge telemetry subscription is restored as soon as it closes.
        """
        runtime=getattr(self._feature_facade,'_runtime',None)
        fid=getattr(runtime,'_open_feature','')
        connected=runtime is not None and self._connection.get('state')=='connected'
        # Only the five streaming display features consume the direct frame
        # path; any other workspace (events, room, ...) must keep the normal
        # bridge telemetry subscription alive.  The local fixture server has
        # no liveFft extension, so fixture mode keeps the bridge streams too.
        wanted=bool(connected and (fid in LIVE_FRAME_FEATURES or self._current_page=="overview") and not self._fixture_active)
        feature=runtime.catalog.feature(fid) if wanted and fid else {}
        channel=int(getattr(runtime,"_input_channels",{}).get(fid,{}).get("channel",(feature.get('launch') or {}).get('params',{}).get('channel',0)))
        key=(str(self._settings.get('host')),int(self._settings.get('controlPort',48120)),channel) if wanted else None
        if self._live_fft_worker and (key!=self._live_fft_key or not self._live_fft_worker.is_alive()):
            self._live_fft_worker.stop();self._live_fft_worker=None
            if runtime:runtime.set_live_stream_active(False)
        now=time.monotonic()
        if key and self._live_fft_worker is None and now>=self._live_fft_retry and now>=self._live_fft_fail_retry:
            self._suspend_bridge_streams()
            from pc_client.live_fft import LiveFFTWorker
            self._live_fft_key=key;self._live_fft_started=now;self._live_fft_frames=0
            self._live_fft_worker=LiveFFTWorker(*key,on_state=lambda s,k=key:self._liveFftState.emit((k,s)),on_frame_ready=lambda k=key:self._liveFftReady.emit(k))
            self._live_fft_worker.start();self._live_fft_retry=now+3
        elif key is None and self._live_fft_worker is None and self._live_subscription_suspended:
            self._resume_bridge_streams()

    def _suspend_bridge_streams(self) -> None:
        """Release the bridge binary subscription so the live stream can own the link."""
        if self._live_subscription_suspended:
            return
        self._live_subscription_suspended=True
        if self._live_subscription_requested:
            try:
                self.bridge.unsubscribe()
            except RuntimeError:
                pass
            self._live_subscription_requested=False

    def _resume_bridge_streams(self) -> None:
        self._live_subscription_suspended=False
        self._live_subscription_requested=True
        QTimer.singleShot(250, self.subscribeLive)

    @Slot(object)
    def _on_live_fft_state(self,payload) -> None:
        key,state=payload
        if key!=self._live_fft_key:return
        connected=bool(state.get('connected')) and self._connection.get('state')=='connected'
        runtime=getattr(self._feature_facade,'_runtime',None)
        if runtime:runtime.set_live_stream_active(connected)
        if connected:
            self._live_fft_failures=0
            return
        self._live_fft_failures+=1
        if self._live_fft_failures>=3:
            # The device refused the live stream repeatedly (e.g. older gateway
            # or a saturated link): restore the bridge telemetry subscription and
            # back off instead of leaving the app without any live data.
            self._live_fft_fail_retry=time.monotonic()+30.0
            if self._live_subscription_suspended:
                self._resume_bridge_streams()

    @Slot(object)
    def _on_live_fft_ready(self,key) -> None:
        """GUI-thread pull of the newest live frame (worker coalesces the rest)."""
        worker=self._live_fft_worker
        if key!=self._live_fft_key or worker is None or self._connection.get('state')!='connected':
            return
        processed=0
        while processed<6:
            item=worker.take_latest()
            if item is None:
                break
            meta,body=item
            self._process_live_frame(meta,body)
            processed+=1
        self._live_fft_coalesced=getattr(worker,'dropped',0)

    def _process_live_frame(self,meta,body) -> None:
        if self._current_page=='overview' and time.monotonic()-getattr(self,'_dashboard_updated',0)>=.20:
            self._dashboard_updated=time.monotonic();levels=struct.unpack_from('<48I',body,3075*4);lf=struct.unpack_from('<48f',body,3075*4)
            channels=[]
            for i in range(6):
                valid=bool(levels[i*8+7]) and math.isfinite(lf[i*8+4])
                channels.append({'label':f'MIC{i+1}','value':lf[i*8+4] if valid else None,'valid':valid,'color':self.theme.channelColors[i],'unit':'dBFS'})
            bins=struct.unpack_from('<3075f',body);fs=float(meta['sampleRateHz'])
            self._dashboard={'levels':channels,'sampleRateHz':fs,'channel':int(meta['channel'])+1,
                'spectrum':{'kind':'spectrum','title':'实时幅度频谱','series':[{'name':'MIC'+str(int(meta['channel'])+1),'points':[[i*fs/2048,bins[3*i]] for i in range(1025) if math.isfinite(bins[3*i])],'color':self.theme.channelColors[int(meta['channel'])]}],
                'xAxis':{'min':0,'max':fs/2,'label':'频率','unit':'Hz'},'yAxis':{'min':0,'max':.01,'label':'幅度','unit':'FS'},'available':True,'chartRevision':int(meta['frame'])}}
        self._live_fft_frames+=1;self._live_fft_max_dispatch_ms=max(self._live_fft_max_dispatch_ms,(time.monotonic_ns()-int(meta['receivedNs']))/1e6)
        raw=struct.unpack_from('<12288i',body,3123*4);first=int(meta['firstSampleIndex'])
        contiguous=self._wave_last_live_sample is not None and first==self._wave_last_live_sample+1
        if not contiguous:self._wave_ring=[[] for _ in range(6)]
        scale=1.0/8388608.0
        for c in range(6):
            ring=self._wave_ring[c];start=c*2048
            ring.extend([raw[start+i]*scale for i in range(2048)])
            if len(ring)>12000:
                del ring[:len(ring)-12000]
        self._wave_revision+=1
        self._wave_last_live_sample=int(meta['lastSampleIndex']);self._wave_start=str(self._wave_last_live_sample-len(self._wave_ring[0])+1)
        self._audio_meta={'sampleRateHz':meta['sampleRateHz'],'firstSampleIndex':self._wave_start,'sampleCount':len(self._wave_ring[0]),'gapBefore':not contiguous,'windowedLive':True,'sourceKind':'pl-live'}
        # The bridge telemetry subscription is suspended while this stream owns the
        # binary link; keep the shell counters/freshness live from the frames.
        self._frame_count+=1
        self._last_frame={'sourceKind':'pl-live','sampleRateHz':meta.get('sampleRateHz'),
                          'sampleIndex':meta.get('firstSampleIndex')}
        self._source_detail={'sourceKind':'pl-live','sampleIndex':meta.get('firstSampleIndex'),
                             'sampleRateHz':meta.get('sampleRateHz'),'note':'live frame stream'}
        self._source='pl-live';self._frame_time=_now();self._schedule_changed()
        runtime=getattr(self._feature_facade,'_runtime',None)
        if runtime:runtime.ingest_live_frame(meta,body)

    def _retry_refresh_feature_api(self) -> None:
        self._feature_api_retry_pending = False
        self._refresh_feature_api()

    def _refresh_feature_api(self) -> None:
        if self._feature_facade is None:
            return
        connected = str(self._connection.get("state")) == "connected"
        info: dict[str, Any] = {}
        getter = getattr(self.bridge, "featureApiInfo", None)
        if connected and callable(getter):
            try:
                info = json.loads(getter() or "{}")
            except (ValueError, TypeError, RuntimeError):
                info = {}
        if connected and not info:
            session = getattr(self.bridge, "_session_or_none", None)
            hello = getattr(session, "hello", None) if callable(session) else None
            capabilities = (hello or {}).get("capabilities") or {}
            info = dict((capabilities.get("gateway") or {}).get("featureApi") or {})
            info["connected"] = True
        if connected and "enabled" not in info:
            # Missing capability data during refresh is unknown, not disabled.
            if not self._feature_api_retry_pending:
                self._feature_api_retry_pending=True
                QTimer.singleShot(300,self._retry_refresh_feature_api)
            return
        if not connected:
            self._feature_api_retry_count = 0
            self._feature_api_retry_pending = False
        elif not info.get("enabled"):
            # The control connection event can arrive before hello/capabilities
            # are stored in the session.  Do not push a transient "featureApi
            # disabled" state to the facade (it would flash "功能接口不可用" on
            # every connect); retry briefly and only report a stable disabled
            # capability.
            if self._feature_api_retry_count < 6:
                self._feature_api_retry_count += 1
                if not self._feature_api_retry_pending:
                    self._feature_api_retry_pending = True
                    QTimer.singleShot(300, self._retry_refresh_feature_api)
                return
        else:
            self._feature_api_retry_count = 0
            self._feature_api_retry_pending = False
        self._feature_facade.set_connection(connected, info)

    @Property("QVariantList", notify=featureChanged)
    def featurePageFeatures(self):  # noqa: N802
        if self._feature_facade is None:
            return []
        return self._feature_facade.entries(self._current_page)

    @Property("QVariantList", notify=featureChanged)
    def featurePageGroups(self):  # noqa: N802
        if self._feature_facade is None:
            return []
        return self._feature_facade.page_groups(self._current_page)

    @Property("QVariantMap", notify=featureChanged)
    def featureWorkspace(self):  # noqa: N802
        if self._feature_facade is None:
            return {"open": False, "available": False,
                    "message": "功能工作区不可用",
                    "error": {"code": "feature-facade", "reason": self._feature_facade_error},
                    "chart": {"kind": "capability", "emptyReason": self._feature_facade_error},
                    "flow": {"actions": [], "confirmations": []}}
        return self._feature_facade.workspace()

    @Property("QVariantMap", notify=featureChanged)
    def featureStatus(self):  # noqa: N802
        if self._feature_facade is None:
            return {"featureApiEnabled": False, "connected": False,
                    "deviceSoftwareNote": "功能工作区不可用",
                    "runtimeError": self._feature_facade_error}
        status = self._feature_facade.status()
        status["facadeError"] = self._feature_facade_error
        return status

    @Slot(str, result="QVariantList")
    def featureGroupsForPage(self, pageId: str):  # noqa: N802
        return self._feature_facade.page_groups(str(pageId)) if self._feature_facade else []

    @Slot(str, result="QVariantList")
    def featureEntriesForPage(self, pageId: str):  # noqa: N802
        return self._feature_facade.entries(str(pageId)) if self._feature_facade else []

    @Slot()
    def refreshFeatureCatalog(self) -> None:  # noqa: N802
        if self._feature_facade is not None:
            self._feature_facade.refresh_catalog()

    @Slot(str)
    def openFeatureEntry(self, featureId: str) -> None:  # noqa: N802
        if self._feature_facade is not None:
            self._feature_facade.open(str(featureId))

    @Slot()
    def closeFeatureWorkspace(self) -> None:  # noqa: N802
        if self._feature_facade is not None:
            self._feature_facade.close()

    @Slot(str)
    def runFeature(self, featureId: str) -> None:  # noqa: N802
        if str(featureId)=='event_trigger':self._event_auto_download_suspended=False
        if self._feature_facade is not None:
            self._feature_facade.run(str(featureId))

    @Slot(str)
    def stopFeature(self, featureId: str) -> None:  # noqa: N802
        if self._feature_facade is not None:
            self._feature_facade.stop(str(featureId))

    @Slot(str)
    def refreshFeature(self, featureId: str) -> None:  # noqa: N802
        if self._feature_facade is not None:
            self._feature_facade.refresh(str(featureId))

    @Slot(str, str, "QVariant")
    def featureConfirm(self, featureId: str, key: str, value: Any) -> None:  # noqa: N802
        if self._feature_facade is not None:
            self._feature_facade.confirm(str(featureId), str(key), value)

    @Slot(str, str)
    def featureAction(self, featureId: str, actionId: str) -> None:  # noqa: N802
        if self._feature_facade is not None:
            self._feature_facade.action(str(featureId), str(actionId))

    @Slot(str, str, "QVariant")
    def setFeatureViewOption(self, featureId: str, key: str, value: Any) -> None:  # noqa: N802
        if self._feature_facade is not None:
            self._feature_facade.set_view_option(str(featureId), str(key), value)

    @Slot(str, str, result=str)
    def featureArtifactPath(self, featureId: str, suffix: str) -> str:  # noqa: N802
        if self._feature_facade is None:
            return ""
        return self._feature_facade.artifact_path(str(featureId), str(suffix or "png"),
                                                  self.user_root)

    @Slot(str, result=str)
    def saveFeatureChart(self, featureId: str) -> str:  # noqa: N802
        """Return the PNG target path; QML grabs the chart image and saves it."""
        if self._feature_facade is None:
            return ""
        return self._feature_facade.artifact_path(str(featureId), "png", self.user_root)

    @Slot(str)
    def notifyFeatureSaved(self, path: str) -> None:  # noqa: N802
        self._notify("info", self.t("features.saved"), str(path))
        self._schedule_changed()

    @Slot(str)
    def notifyFeatureSaveFailed(self, reason: str) -> None:  # noqa: N802
        self._notify("error", self.t("features.save_failed"), str(reason))
        self._schedule_changed()

    @Slot(str)
    def exportFeatureRaw(self, featureId: str) -> None:  # noqa: N802
        if self._exports_closed:
            return
        if self._export_pending:
            self._notify("info", self.t("studio.export_working"), "")
            return
        if self._feature_facade is None:
            return
        workspace = dict(self.featureWorkspace)
        raw = self._feature_facade.export_raw(str(featureId))
        if workspace.get("featureId") != str(featureId) or not raw:
            self._notify("warn", self.t("studio.export_wait"), "")
            return
        # Snapshot owned Python values before the UI may replace the result.
        workspace = json.loads(json.dumps(workspace, ensure_ascii=False))
        raw = json.loads(json.dumps(raw, ensure_ascii=False))
        def work():
            try:
                from ui.viewmodels.measurement_exports import export_feature
                files = export_feature(self.user_root / "exports", workspace, raw)
                self._exportReady.emit(json.dumps({"ok":True,"files":files}))
            except Exception as exc:
                self._exportReady.emit(json.dumps({"ok":False,"reason":str(exc)[:240]}))
        self._export_pending += 1
        self._notify("info", self.t("studio.export_working"), "")
        self._schedule_changed()
        self._export_executor.submit(work)

    @Slot(str)
    def exportEventData(self, eventId: str) -> None:  # noqa: N802
        if self._exports_closed:
            return
        if self._export_pending:
            self._notify("info", self.t("studio.export_working"), "")
            return
        event = next((dict(e) for e in self._events if str(e.get("eventId")) == str(eventId)), None)
        if event is None:
            self._notify("warn", self.t("studio.select_event"), "")
            return
        path = event.get("filePath") or (event.get("file") or {}).get("path")
        if not path or not Path(path).is_file():
            if self.connectionState != "connected":
                self._notify("warn", self.t("studio.download_connect"), "")
                return
            self._pending_event_exports.add(str(eventId))
            self.downloadEvent(str(eventId))
            return
        source = event.get("sourceKind") or "unknown"
        def work():
            try:
                from ui.viewmodels.measurement_exports import export_event_file
                files = export_event_file(Path(path), self.user_root / "exports")
                # Event DTO provenance is authoritative; some legacy manifests
                # marked simulated files pl-live. Do not propagate that label.
                metadata = Path(files["metadata"])
                payload = json.loads(metadata.read_text(encoding="utf-8"))
                if source in ("pl-live", "test-fixture", "unknown"):
                    payload.update({"sourceKind":source,"fixture":source=="test-fixture",
                                    "sourceLabelAuthority":"event DTO"})
                    metadata.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
                self._exportReady.emit(json.dumps({"ok":True,"files":files}))
            except Exception as exc:
                self._exportReady.emit(json.dumps({"ok":False,"reason":str(exc)[:240]}))
        self._export_pending += 1
        self._notify("info", self.t("studio.export_working"), "")
        self._schedule_changed()
        self._export_executor.submit(work)

    @Property(bool, notify=dataChanged)
    def exportBusy(self) -> bool:  # noqa: N802
        return self._export_pending > 0

    @Slot(str)
    def _on_export_ready(self, text: str) -> None:
        self._export_pending = max(0, self._export_pending - 1)
        result=json.loads(text)
        if result.get("ok"):
            files=result.get("files") or {}
            path=files.get("metadata") or next(iter(files.values()), "")
            self._notify("info", self.t("studio.export_done"), str(Path(path).parent) if path else "")
        else:
            self._notify("error", self.t("features.save_failed"), result.get("reason", ""))
        self._schedule_changed()

    @Slot()
    def refreshFeatureEvents(self) -> None:  # noqa: N802
        self.listEvents()

    @Slot(int)
    def setInspectorTab(self, tab: int) -> None:  # noqa: N802
        self._inspector_tab = max(0, min(2, int(tab)))
        self._schedule_changed()

    @Slot(str, "QVariant")
    def setSetting(self, key: str, value: Any) -> None:  # noqa: N802
        if key not in self._settings:
            return
        if key == "host":
            value = str(value or "").strip()
            if not value or len(value) > 253:
                return
        if key in ("controlPort", "binaryPort"):
            try:
                value = int(value)
            except (TypeError, ValueError):
                return
            if not 1 <= value <= 65535 or value == 48110:
                self._notify("error", self.t("toast.invalid_port"), str(value))
                return
        self._settings[key] = value
        self._settings_dirty = True
        if key == "themeMode":
            self._apply_theme_mode()
        elif key == "fontScale":
            try:
                scale = max(0.7, min(1.15, float(value)))
            except (TypeError, ValueError):
                return
            self._settings["fontScale"] = scale
            self.theme.set_font_scale(scale)
        elif key == "uiScale":
            try:
                scale = max(0.7, min(1.6, float(value)))
            except (TypeError, ValueError):
                return
            self._settings["uiScale"] = scale
            self._ui_scale_changed = True
            self._restart_required = True
            self._settings_apply_message = self.t("settings.ui_scale_restart")
        self._schedule_changed()

    @Slot(result="QVariantMap")
    def settingsSnapshot(self) -> dict[str, Any]:  # noqa: N802
        return dict(self._settings)

    @Property(bool, notify=dataChanged)
    def settingsDirty(self) -> bool:  # noqa: N802
        return self._settings_dirty

    @Property(bool, notify=dataChanged)
    def restartRequired(self) -> bool:  # noqa: N802
        return self._restart_required

    @Property(str, notify=dataChanged)
    def settingsApplyMessage(self) -> str:  # noqa: N802
        return self._settings_apply_message

    @Slot(result=bool)
    def applySettings(self) -> bool:  # noqa: N802
        ok = self._save_settings()
        self._settings_dirty = not ok
        self._settings_apply_message = self.t("settings.apply_done" if ok else "settings.apply_failed")
        if ok:
            if self._ui_scale_changed:
                self._restart_required = True
                self._settings_apply_message = self.t("settings.ui_scale_restart")
            else:
                self._restart_required = False
            self._notify("info", self.t("settings.apply_done"), "")
        self._schedule_changed()
        return ok

    @Slot()
    def restartAndApply(self) -> None:  # noqa: N802
        self._save_settings()
        self._notify("info", self.t("settings.restarting"), "")
        try:
            import sys
            from PySide6.QtCore import QCoreApplication, QProcess
            QProcess.startDetached(sys.executable, list(sys.argv))
            QCoreApplication.quit()
        except Exception as exc:  # noqa: BLE001
            self._settings_apply_message = f"{self.t('settings.apply_failed')}: {exc}"
            self._restart_required = True
            self._schedule_changed()

    # ------------------------------------------------------------------
    # connection / fixture / control
    # ------------------------------------------------------------------
    @Slot(str, int, int)
    def connectDevice(self, host: str = "", controlPort: int = 0,  # noqa: N802
                      binaryPort: int = 0) -> str:
        # Double-click / Enter can fire a second connect while the first
        # handshake is still in flight; the bridge would answer "busy" and the
        # UI would show a misleading error.  Ignore the duplicate attempt.
        if self._busy and str(self._connection.get("state")) in ("connecting", "handshaking"):
            return ""
        host = str(host or self._settings["host"]).strip()
        controlPort = int(controlPort or self._settings["controlPort"])
        binaryPort = int(binaryPort or self._settings["binaryPort"])
        if not self._fixture_active:
            self._settings["host"] = host
            self._settings["controlPort"] = controlPort
            self._settings["binaryPort"] = binaryPort
            self._save_settings()
        request_id = self._next_request("connect")
        self._connection["state"] = "connecting"
        self._connection["host"] = host
        self._source = "none"
        self._set_busy(True, self.t("busy.connecting"))
        self.stateChanged.emit()
        self.bridge.connectDevice(host, controlPort, binaryPort)
        return request_id

    @Slot()
    def disconnectDevice(self) -> None:  # noqa: N802
        self._next_request("disconnect")
        self._set_busy(True, self.t("busy.disconnecting"))
        self.bridge.disconnectDevice()

    @Slot()
    def startFixtureDemo(self) -> None:  # noqa: N802
        if self._fixture_active:
            return
        try:
            from sixmic_backend.testing.mock_ps_server import MockPsServer
            self._set_busy(True, self.t("busy.fixture_start"))
            self._fixture = MockPsServer(result_frames=2, pcm_chunks=2,
                                         stream_seconds=30.0)
            info = self._fixture.start()
            self._fixture_active = True
            self._fixture_info = info
            self._notify("info", self.t("toast.fixture_started"),
                         f"127.0.0.1:{info['controlPort']}")
            self.connectDevice("127.0.0.1", info["controlPort"], info["binaryPort"])
        except Exception as exc:  # noqa: BLE001
            self._fixture_active = False
            self._set_busy(False)
            self._notify("error", self.t("toast.fixture_failed"), str(exc)[:200])

    @Slot()
    def stopFixtureDemo(self) -> None:  # noqa: N802
        self.bridge.disconnectDevice()
        self._stop_fixture_server()
        self._notify("info", self.t("toast.fixture_stopped"))

    def _stop_fixture_server(self) -> None:
        server = self._fixture
        self._fixture = None
        self._fixture_active = False
        if server is not None:
            try:
                server.stop()
            except Exception:
                pass

    @Slot()
    def subscribeLive(self) -> None:  # noqa: N802
        # Request only runtime-advertised streams. Unsupported PCM must not
        # reject an otherwise usable result/service subscription.
        if self._live_fft_worker is not None and self._live_fft_worker.is_alive():
            # The direct live-frame stream owns the single binary link for now;
            # resume this subscription once that workspace closes.
            self._live_subscription_requested=True
            self._live_subscription_suspended=True
            return
        streams = []
        if self._capabilities.get("liveResults") == "available":
            streams.append("resultWords")
        if self._capabilities.get("livePcm") == "available":
            streams.append("pcmRecord32")
        if self._capabilities.get("serviceSnapshots"):
            streams.append("serviceSnapshot")
        if self._fixture_active:
            streams = ["resultWords", "pcmRecord32", "serviceSnapshot"]
        if not streams:
            self._notify("warn", self.t("pl.no_streams"), self.t("pl.wait_capabilities"))
            return
        try:
            self._live_subscription_requested = True
            self.bridge.subscribe(json.dumps(streams))
        except RuntimeError:
            self._live_subscription_requested = False
            return
        self._set_busy(True, self.t("busy.subscribing"))

    @Slot()
    def unsubscribeLive(self) -> None:  # noqa: N802
        self._live_subscription_requested = False
        self.bridge.unsubscribe()

    @Slot()
    def claimControl(self) -> None:  # noqa: N802
        self._next_request("claim")
        try:
            self.bridge.claimControl()
        except RuntimeError:
            return
        self._schedule_changed()

    @Slot()
    def releaseControl(self) -> None:  # noqa: N802
        self._next_request("release")
        try:
            self.bridge.releaseControl()
        except RuntimeError:
            return
        self._control_held = False
        if op in ("list_features", "start_feature", "stop_feature", "get_feature",
                  "get_feature_result", "release_feature_result"):
            self._feature_api["busy"] = False
            self._feature_api["message"] = str(error.get("code") or "error")
        self._settings_apply_message = ""
        self._settings_dirty = False
        self._restart_required = False
        self._schedule_changed()

    @Slot(str)
    def startJob(self, kind: str) -> None:  # noqa: N802
        self._next_request("job")
        self.bridge.startJob(kind, json.dumps({"clientTaskKey": f"ui-{int(_now())}"}))

    @Slot(str)
    def cancelJob(self, jobId: str) -> None:  # noqa: N802
        self._next_request("cancel")
        self.bridge.cancelJob(jobId)

    @Slot()
    def startRecording(self) -> None:  # noqa: N802
        self._next_request("recording_start")
        self.bridge.startRecording()

    @Slot()
    def stopRecording(self) -> None:  # noqa: N802
        self._next_request("recording_stop")
        self.bridge.stopRecording()

    @Slot()
    def listEvents(self) -> None:  # noqa: N802
        self._next_request("events_list")
        self.bridge.listEvents()

    @Slot()
    def startMonitor(self) -> None:  # noqa: N802
        if self._connection.get("state") != "connected":
            self._notify("warn", self.t("events.monitor.need_connection"), "")
            return
        self._monitor.update({
            "active": True, "phase": "learning", "learningProgress": 0.0,
            "backgroundLocked": False,
            "startedMonotonicNs": str(time.monotonic_ns()),
            "eventsSeen": 0, "newEventId": ""})
        self._monitor_seen_ids = {str(item.get("eventId")) for item in self._events}
        self._monitor_learning_frames = 0
        self._monitor_timer.start()
        self._next_request("events_list")
        self.bridge.listEvents()
        self._notify("info", self.t("events.monitor.started"), "")
        self._schedule_changed()

    @Slot()
    def stopMonitor(self) -> None:  # noqa: N802
        self._monitor_timer.stop()
        self._monitor.update({"active": False, "phase": "stopped",
                              "stoppedMonotonicNs": str(time.monotonic_ns())})
        self._notify("info", self.t("events.monitor.stopped"), "")
        self._schedule_changed()

    @Slot()
    def lockBackground(self) -> None:  # noqa: N802
        if self._monitor.get("phase") != "learning":
            return
        self._monitor.update({"backgroundLocked": True, "phase": "locked",
                              "learningProgress": 1.0})
        QTimer.singleShot(400, self._enter_monitoring)
        self._schedule_changed()

    def _enter_monitoring(self) -> None:
        if not self._monitor.get("active"):
            return
        self._monitor["phase"] = "monitoring"
        self._notify("info", self.t("events.monitor.monitoring"), "")
        self._schedule_changed()

    @Slot()
    def resetBackground(self) -> None:  # noqa: N802
        if self._monitor.get("active"):
            self._monitor.update({"phase": "learning", "learningProgress": 0.0,
                                  "backgroundLocked": False})
            self._monitor_learning_frames = 0
            self._schedule_changed()

    @Slot(str, "QVariant")
    def setMonitorSetting(self, key: str, value: Any) -> None:  # noqa: N802
        settings = self._monitor.get("settings") or {}
        if key not in settings:
            return
        try:
            settings[key] = float(value)
        except (TypeError, ValueError):
            return
        self._schedule_changed()

    def _tick_monitor(self) -> None:
        if not self._monitor.get("active"):
            self._monitor_timer.stop()
            return
        phase = self._monitor.get("phase")
        if phase == "learning":
            # Learning progress reflects received audio frames; it is a local
            # UI readiness indicator, not a device measurement.
            if self._audio_chunk_count != self._monitor_learning_frames:
                self._monitor_learning_frames = self._audio_chunk_count
                progress = min(0.95, float(self._monitor.get("learningProgress", 0.0)) + 0.12)
                self._monitor["learningProgress"] = progress
            if float(self._monitor.get("learningProgress", 0.0)) >= 0.95:
                self._monitor["phase"] = "locked"
                self._monitor["backgroundLocked"] = True
                self._monitor["learningProgress"] = 1.0
                QTimer.singleShot(300, self._enter_monitoring)
            self._schedule_changed()
        if phase in ("locked", "monitoring"):
            self._next_request("events_list")
            try:
                self.bridge.listEvents()
            except RuntimeError:
                self._monitor_timer.stop()

    def _note_event_arrivals(self) -> None:
        runtime=getattr(self._feature_facade,"_runtime",None)
        if runtime is not None:runtime.on_events(self.eventsData['events'])
        monitoring=runtime._active_feature_job('event_trigger') if runtime else None
        if self.connectionState=='connected' and (monitoring or self._current_page=='events') and not self._event_auto_download_suspended and not self._event_clear_pending and not self._event_download_inflight and time.monotonic()>=self._event_download_retry_at:
            for event in self._events:
                local=event.get('filePath') or (event.get('file') or {}).get('path')
                if not local and (event.get('file') or {}).get('state') in ('available','verified'):
                    self.downloadEvent(str(event['eventId']));break
        for event in self._events:
            event_id = str(event.get("eventId"))
            if event_id and event_id not in self._monitor_seen_ids:
                self._monitor_seen_ids.add(event_id)
                if self._monitor.get("active"):
                    self._monitor["eventsSeen"] = int(self._monitor.get("eventsSeen", 0)) + 1
                    self._monitor["newEventId"] = event_id
                    self._notify("warn", self.t("events.monitor.new_event"),
                                 "#" + event_id)

    @Slot()
    def refreshMonitorEvents(self) -> None:  # noqa: N802
        try:
            self.bridge.listEvents()
        except RuntimeError:
            return

    @Slot(str)
    def downloadEvent(self, eventId: str) -> None:  # noqa: N802
        if self._event_download_inflight:return
        self._event_download_inflight=str(eventId)
        self._next_request("event_download")
        name=next((e.get('displayName','') for e in self.eventsData['events'] if str(e.get('eventId'))==str(eventId)),'')
        self._notify("info", self.t("toast.downloading_event"), name)
        self.bridge.downloadEvent(str(eventId))

    @Slot()
    def openEventDownloads(self) -> None:
        folder=self.user_root/'events'/'录音';folder.mkdir(parents=True,exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    @Slot(bool,bool)
    def clearAllEvents(self, device: bool, local: bool) -> None:
        if self._event_download_inflight or self._event_clear_pending:return
        if not device and not local:return
        self.stopFeature('event_trigger')
        self._event_auto_download_suspended=True
        self._event_clear_pending=True
        self._next_request('clear_events');self.bridge.clearEvents(bool(device),bool(local))
        self._schedule_changed()

    # ------------------------------------------------------------------
    # bridge signal handlers
    # ------------------------------------------------------------------
    @Slot(str)
    def _on_connection(self, payload: str) -> None:
        try:
            data = json.loads(payload)
        except ValueError:
            return
        state = str(data.get("state", "disconnected"))
        self._connection.update({
            "state": state, "host": data.get("host", self._connection["host"]),
            "controlPort": data.get("controlPort", self._connection["controlPort"]),
            "binaryPort": data.get("binaryPort", self._connection["binaryPort"]),
            "error": data.get("error"), "since": _now()})
        if state == "connected":
            self._set_busy(False)
            QTimer.singleShot(150, self._refresh_feature_api)
            self._next_request("capabilities")
            self.bridge.refreshCapabilities()
            if self._fixture_active:
                QTimer.singleShot(120, self.subscribeLive)
                QTimer.singleShot(260, self.claimControl)
        elif state in ("failed", "disconnected"):
            self._set_busy(False)
            QTimer.singleShot(0, self._refresh_feature_api)
            self._source = "none" if not self._replay_manifest_path else "file-replay"
            self._last_frame = None
            self._frame_time = 0.0
            self._wave_ring = [[] for _ in range(6)]
            self._wave_revision += 1
            self._analysis.clear()
            self._service_snapshot = {}
            self._live_subscription_requested = False
            self._control_held = False
            self._capabilities = {}
            self._stop_playback()
            if state == "failed":
                self._notify("error", self.t("toast.connection_failed"),
                             str((data.get("error") or {}).get("code", "")))
        elif state == "degraded":
            self._set_busy(False)
            self._notify("warn", self.t("toast.connection_degraded"), "")
        elif state == "reconnecting":
            self._notify("warn", self.t("toast.reconnecting"), "")
        self.stateChanged.emit()
        self._recompute_overview()
        self._schedule_changed()

    @Slot(str)
    def _on_capabilities(self, payload: str) -> None:
        try:
            data = json.loads(payload)
        except ValueError:
            return
        self._capabilities = dict(data)
        self._set_busy(False)
        QTimer.singleShot(50, self._refresh_feature_api)
        if not self._fixture_active and not self._live_subscription_requested and self.plInterface["canSubscribe"]:
            self.subscribeLive()
        self._recompute_overview()
        self._schedule_changed()

    @Slot(str)
    def _on_frame(self, payload: str) -> None:
        try:
            data = json.loads(payload)
        except ValueError:
            return
        if data.get("validity", {}).get("stale"):
            self._notify("warn", self.t("toast.stream_stale"),
                         str(data.get("validity", {}).get("reason", "")))
            self._last_frame = None
            self._frame_time = 0.0
            self._recompute_overview()
            self._schedule_changed()
            return
        self._last_frame = data
        self._frame_time = _now()
        self._frame_count += 1
        self._source = str(data.get("sourceKind", "test-fixture"))
        self._source_detail = {
            "sourceKind": self._source,
            "deviceId": data.get("deviceId"),
            "frameId": data.get("frameId"),
            "configVersion": data.get("configVersion"),
            "sampleIndex": data.get("sampleIndex"),
            "sampleRateHz": data.get("sampleRateHz"),
            "receivedMonotonicNs": data.get("receivedMonotonicNs"),
        }
        self._last_snapshot = data.get("decoded") or {}
        if self._capabilities and data.get("sourceKind") == "pl-live":
            self._source_detail["note"] = "live snapshot received from gateway"
        self._recompute_overview()
        self._schedule_changed()

    @Slot(str)
    def _on_audio(self, payload: str) -> None:
        try:
            data = json.loads(payload)
        except ValueError:
            return
        records = data.get("records") or {}
        handle = records.get("handleId")
        if not handle:
            return
        try:
            raw = bytes(self.bridge.readBuffer(handle, 0, int(records.get("bytes", 0) or 0)))
        except Exception:
            return
        if not raw or len(raw) % 32:
            return
        try:
            from sixmic_backend.protocol.pcm import decode_records
            decoded = decode_records(raw)
        except Exception:
            return
        self._audio_meta = {
            "sourceKind": data.get("sourceKind"),
            "sampleRateHz": data.get("sampleRateHz"),
            "firstSampleIndex": data.get("firstSampleIndex"),
            "sampleCount": data.get("sampleCount"),
            "gapBefore": data.get("gapBefore"),
            "continuity": data.get("continuity"),
        }
        if not self._wave_start:
            self._wave_start = str(data.get("firstSampleIndex", ""))
        for record in decoded:
            for channel in range(6):
                self._wave_ring[channel].append(record.samples[channel] / 8388608.0)
        limit = 12000
        if len(self._wave_ring[0]) > limit:
            drop = len(self._wave_ring[0]) - limit
            for channel in range(6):
                del self._wave_ring[channel][:drop]
        if data.get("gapBefore"):
            self._gaps.append({"at": str(data.get("firstSampleIndex")),
                               "reason": (data.get("continuity") or {}).get("gaps", [{}])[0].get("reason", "gap")})
            self._gaps = self._gaps[-32:]
        self._audio_chunk_count += 1
        self._wave_revision += 1
        self._frame_time = _now()  # data is flowing even between result publications
        self._source = str(data.get("sourceKind", self._source))
        self._schedule_changed()

    @Slot(str)
    def _on_service(self, payload: str) -> None:
        try:
            data = json.loads(payload)
        except ValueError:
            return
        validity = data.get("validity") or {}
        if validity.get("stale") or not (validity.get("done") is True and validity.get("error") == 0
                and validity.get("headerConsistent") is True
                and validity.get("provenanceValid") is True):
            return
        if data.get("sourceKind") not in ("pl-live", "test-fixture"):
            return
        self._service_snapshot = data
        self._source = str(data["sourceKind"])
        self._frame_time = _now()
        self._schedule_changed()

    @Slot(str)
    def _on_gap(self, payload: str) -> None:
        try:
            data = json.loads(payload)
        except ValueError:
            return
        self._gaps.append(data)
        self._gaps = self._gaps[-32:]
        self._notify("warn", self.t("toast.stream_gap"),
                     f"{data.get('reason','gap')} {data.get('droppedRecords','')}")
        self._schedule_changed()

    @Slot(str)
    def _on_job(self, payload: str) -> None:
        try:
            data = json.loads(payload)
        except ValueError:
            return
        job_id = str(data.get("jobId", ""))
        if job_id:
            self._jobs[job_id] = data
        state = data.get("state")
        if state in ("completed", "failed", "canceled"):
            self._notify("info" if state == "completed" else "warn",
                         self.t("toast.job_terminal") + f" {state}", job_id)
        self._schedule_changed()

    @Slot(str)
    def _on_recording(self, payload: str) -> None:
        try:
            data = json.loads(payload)
        except ValueError:
            return
        self._recording = dict(data)
        self._schedule_changed()

    @Slot(str)
    def _on_event_added(self, payload: str) -> None:
        try:
            data = json.loads(payload)
        except ValueError:
            return
        event = data.get("event") if isinstance(data.get("event"), dict) else data
        event_id = str(event.get("eventId", ""))
        if event_id:
            for index, item in enumerate(self._events):
                if str(item.get("eventId")) == event_id:
                    merged = dict(item)
                    merged.update(event)
                    if data.get("state") == "stored":
                        merged["fileState"] = "stored"
                        merged["filePath"] = (data.get("event") or {}).get("path")
                    self._events[index] = merged
                    break
            else:
                self._events.insert(0, dict(event))
        if data.get("state") == "stored" and event_id in self._pending_event_exports:
            self._pending_event_exports.discard(event_id)
            QTimer.singleShot(0, lambda eid=event_id: self.exportEventData(eid))
        self._note_event_arrivals()
        if data.get("state") == "stored":
            self._notify("info", self.t("toast.event_saved"),
                         Path(event['wavFiles'][0]).name if event.get('wavFiles') else str(event_id))
        self._schedule_changed()

    @Slot(str)
    def _on_diagnostic(self, payload: str) -> None:
        try:
            data = json.loads(payload)
        except ValueError:
            return
        self._notifications.insert(0, {"level": data.get("level", "info"),
                                       "title": data.get("code", "diagnostic"),
                                       "detail": json.dumps(data.get("detail") or {},
                                                            ensure_ascii=False)[:300],
                                       "time": _now()})
        self._notifications = self._notifications[:200]
        self._schedule_changed()

    @Slot(str)
    def _on_operation(self, payload: str) -> None:
        try:
            data = json.loads(payload)
        except ValueError:
            return
        if data.get("control") in ("claimed", "released", "renewed"):
            self._control_held = data.get("control") in ("claimed", "renewed")
            if data.get("control") != "renewed":
                self._notify("info", self.t("toast.control_" + str(data.get("control"))), "")
        elif data.get("binary") == "closed":
            self._live_subscription_requested = False
            self._notify("warn", self.t("toast.stream_stale"), "binary-closed")
        elif data.get("event") == "configApplied":
            state = "applied" if data.get("data", {}).get("applied") else "rejected"
            self._notify("info" if state == "applied" else "error",
                         self.t("toast.config_" + state), "")
        self._schedule_changed()

    _OP_ALIASES = {
        "connectDevice": "connect", "disconnectDevice": "disconnect",
        "refreshCapabilities": "capabilities", "claimControl": "claim",
        "releaseControl": "release", "startJob": "job", "cancelJob": "cancel",
        "startRecording": "recording_start", "stopRecording": "recording_stop",
        "listEvents": "events_list", "downloadEvent": "event_download", "clearEvents":"clear_events",
        "openRecording": "open_recording", "seekPlayback": "seek",
        "setPlaybackState": "playback_state", "exportData": "export",
        "readDiagnostics": "diagnostics", "requestPlaybackChunk": "playback_chunk",
        "listFeatures": "list_features", "startFeature": "start_feature",
        "stopFeature": "stop_feature", "getFeature": "get_feature",
        "getFeatureResult": "get_feature_result",
        "releaseFeatureResult": "release_feature_result",
    }

    def _normalize_op(self, op: str) -> str:
        return self._OP_ALIASES.get(op, op)

    @Slot(str)
    def _on_request_finished(self, payload: str) -> None:
        try:
            data = json.loads(payload)
        except ValueError:
            return
        request_id = str(data.get("requestId", ""))
        if self._feature_facade is not None and self._feature_facade.on_response(
                request_id, data.get("result"), None):
            self._last_operation = data
            self._set_busy(False)
            self._schedule_changed()
            return
        op = self._normalize_op(self._pending_ops.pop(
            request_id, str(data.get("op", ""))))
        self._last_operation = data
        self._set_busy(False)
        result = data.get("result") or {}
        if op=='event_download':self._event_download_inflight='';self._event_download_retry_at=time.monotonic()+1
        status = data.get("status")
        if op == "connect":
            self._connection["state"] = "connected"
        elif op == "disconnect":
            self._connection["state"] = "disconnected"
        elif op == "capabilities":
            device = result.get("device") if isinstance(result.get("device"), dict) else result
            if isinstance(device, dict):
                self._capabilities = dict(device)
        elif op == "claim" or str(data.get("op")) == "claimControl":
            self._control_held = status in ("ok", "completed")
        elif op == "events_list":
            if isinstance(result, list):
                events = result
            elif isinstance(result, dict):
                events = result.get("events")
            else:
                events = None
            if isinstance(events, list) and events:
                existing = {str(item.get("eventId")) for item in self._events}
                for event in events:
                    if str(event.get("eventId")) not in existing:
                        self._events.append(dict(event))
                self._events.sort(key=lambda item: int(str(item.get("eventId", "0"))) if str(item.get("eventId", "0")).isdigit() else 0, reverse=True)
                self._note_event_arrivals()
        elif op == "open_recording":
            manifest = str(result.get("manifestPath") or "")
            if not manifest and getattr(self, "_pending_recording_path", ""):
                candidate = Path(str(self._pending_recording_path))
                manifest = str(candidate / "manifest.json" if candidate.is_dir() else candidate)
            if manifest:
                self._load_replay_reference(manifest)
        elif op == "export":
            paths = result if isinstance(result, dict) else {}
            manifest_path = str(paths.get("manifest") or "")
            if manifest_path:
                self._normalize_exported_manifest(manifest_path)
            self._notify("info", self.t("toast.export_started"),
                         str(manifest_path or paths.get("wav") or ""))
        elif op == "diagnostics":
            self._diagnostics_cache = dict(result)
            self._notify("info", self.t("diagnostics.refresh"), "")
        elif op == "event_download":
            pass
        elif op == 'clear_events':
            self._event_clear_pending=False;self._events=[];self._event_selected=''
            self._notify('info','事件清理完成',f"板端 {result.get('deviceRemoved',0)} 条，本机 {result.get('localRemoved',0)} 份；未清理 {len(result.get('failed',[]))} 条；导出文件保留")
            self._note_event_arrivals()
        elif op == "recording_start":
            self._recording = dict(result or self._recording)
        elif op == "recording_stop":
            self._recording = dict(result or self._recording)
        elif op in ("job", "cancel"):
            job_id = str(result.get("jobId", ""))
            if job_id:
                self._jobs.setdefault(job_id, {"jobId": job_id, "state": "accepted"})
                self._jobs[job_id].update(result)
        elif op == "list_features":
            if isinstance(result, dict) and isinstance(result.get("features"), list):
                self._feature_api["available"] = True
                self._feature_api["version"] = str(result.get("version") or "")
                self._feature_api["features"] = list(result.get("features") or [])
                self._feature_api["busy"] = False
                self._feature_api["message"] = self.t("features.list_ok")
        elif op == "start_feature":
            job_id = str((result or {}).get("jobId") or "")
            if job_id:
                self._feature_api["job"] = {"jobId": job_id, "state": "accepted"}
                self._feature_api["result"] = None
                self._feature_api["words"] = []
                self._feature_api["message"] = self.t("features.started") + " " + job_id
                QTimer.singleShot(700, self.refreshFeatureJob)
            self._feature_api["busy"] = False
        elif op == "stop_feature":
            job = dict(self._feature_api.get("job") or {})
            job.update(result or {})
            job["state"] = str(job.get("state") or "canceled")
            self._feature_api["job"] = job
            self._feature_api["busy"] = False
            self._feature_api["message"] = self.t("features.stopped")
        elif op == "get_feature":
            if isinstance(result, dict):
                self._feature_api["job"] = dict(result)
                self._feature_api["message"] = str(result.get("state") or "")
        elif op == "get_feature_result":
            if isinstance(result, dict):
                self._feature_api["result"] = dict(result)
                self._feature_api["busy"] = False
                ref = result.get("dataRef") or {}
                handle = ref.get("handleId")
                count = int(ref.get("count") or 0)
                words = []
                chart = {}
                if handle and count > 0:
                    try:
                        probe = min(count, 1000000)
                        raw = bytes(self.bridge.readBuffer(str(handle), 0, probe))
                        words = list(struct.unpack("<" + "I" * (len(raw) // 4), raw[:len(raw) // 4 * 4]))
                        try:
                            from ui.viewmodels.feature_codec import decode_feature_result
                            local = next((f for f in self._feature_ui.get("features", [])
                                          if str(f.get("featureId")) == str(result.get("featureId"))), {})
                            schema = dict(result.get("schema") or {})
                            if local.get("schemaMeta"):
                                schema.setdefault("metadata", local["schemaMeta"])
                            chart = decode_feature_result(
                                {"schema": schema, "schemaMeta": local.get("schemaMeta")},
                                raw)
                        except Exception as exc:  # noqa: BLE001
                            chart = {"available": False, "reason": f"decode: {exc}"}
                    except Exception:
                        words = []
                self._feature_api["words"] = words[:512]
                self._feature_chart = chart
                self._feature_api["message"] = self.t("features.result_ok") + (
                    " (" + str(count) + " words)" if count else "")
        elif op == "release_feature_result":
            self._feature_api["result"] = None
            self._feature_api["words"] = []
            self._feature_api["message"] = self.t("features.released")
        self.operationFinished.emit(json.dumps({
            "requestId": request_id, "op": op, "status": status,
            "result": result}, ensure_ascii=False))
        self._recompute_overview()
        self._schedule_changed()

    @Slot(str)
    def _on_backend_error(self, payload: str) -> None:
        try:
            data = json.loads(payload)
        except ValueError:
            return
        request_id = str(data.get("requestId", ""))
        if self._feature_facade is not None:
            error_payload = dict(data.get("error") or {})
            if self._feature_facade.on_response(request_id, None, error_payload):
                self._last_error = error_payload
                self._set_busy(False)
                self._schedule_changed()
                return
        op = self._normalize_op(self._pending_ops.pop(
            request_id, str(data.get("op", ""))))
        error = dict(data.get("error") or {})
        if op=='clear_events':self._event_clear_pending=False
        if op=='event_download':
            if error.get('code')=='unknown_event':
                for event in self._events:
                    if str(event.get('eventId'))==self._event_download_inflight:
                        event['file']=dict(event.get('file') or {},state='expired')
            self._event_download_inflight='';self._event_download_retry_at=time.monotonic()+30
        self._last_error = error
        self._set_busy(False)
        if op == "subscribe":
            self._live_subscription_requested = False
        if op == "claim" or str(data.get("op")) == "claimControl":
            self._control_held = False
        self._settings_apply_message = ""
        self._settings_dirty = False
        self._restart_required = False
        if op in ("connect",) or str(data.get("op")) == "connectDevice":
            self._connection["state"] = "failed"
            self._connection["error"] = error
        message = self.t(str(error.get("messageKey", "errors.internal_error")))
        detail = json.dumps(error.get("detail") or {}, ensure_ascii=False)[:260]
        if message == str(error.get("messageKey", "")):
            message = self.t("error." + str(error.get("code", "internal_error")))
        if message.startswith("error.") or message.startswith("errors."):
            message = str(error.get("code", "error"))
        self._notify("error", message, detail)
        self.errorRaised.emit(json.dumps({"op": op, "error": error}, ensure_ascii=False))
        self._recompute_overview()
        self._schedule_changed()

    # ------------------------------------------------------------------
    # replay
    # ------------------------------------------------------------------
    @Slot(str)
    def openRecording(self, path: str) -> None:  # noqa: N802
        # External/offline audio is outside the product scope. Only records
        # produced by this device may be opened, through the backend gateway;
        # that gateway route is not wired yet.
        self._notify("warn", self.t("toast.replay_required"),
                     self.t("toast.replay_required_detail"))

    @Slot(str)
    def seekPlayback(self, fraction: str) -> None:  # noqa: N802
        try:
            value = max(0.0, min(1.0, float(fraction)))
        except (TypeError, ValueError):
            return
        self._replay_position = value
        self.bridge.seekPlayback("", f"{value:.6f}")
        self._schedule_changed()

    def _pump_playback(self) -> None:
        if self._playback_state != "playing":
            self._playback_timer.stop()
            return
        self.bridge.requestPlaybackChunk(150)

    @Slot(str)
    def _on_playback_chunk(self, payload: str) -> None:
        try:
            data = json.loads(payload)
        except ValueError:
            return
        if data.get("state") == "eof":
            self._playback_state = "stopped"
            self._playback_timer.stop()
            self._schedule_changed()
            return
        records = data.get("records") or {}
        handle = records.get("handleId")
        if not handle:
            return
        try:
            raw = bytes(self.bridge.readBuffer(handle, 0, int(records.get("bytes", 0) or 0)))
            from sixmic_backend.protocol.pcm import decode_records
            decoded = decode_records(raw)
        except Exception:
            return
        for record in decoded:
            for channel in range(6):
                self._replay_ring[channel].append(record.samples[channel] / 8388608.0)
        limit = 24000
        if len(self._replay_ring[0]) > limit:
            drop = len(self._replay_ring[0]) - limit
            for channel in range(6):
                del self._replay_ring[channel][:drop]
        first = int(data.get("firstSampleIndex", "0") or 0)
        if self._replay and self._replay_duration > 0:
            first_record_index = max(0, first - int(
                self._replay.manifest.get("firstSampleIndex", "0") or 0))
            self._replay_position = min(
                1.0, first_record_index / max(1, self._replay.records))
        self._wave_revision += 1
        self._source = "file-replay"
        if self._playback_state == "playing":
            self._playback_timer.start()
        self._schedule_changed()

    def _stop_playback(self) -> None:
        self._playback_timer.stop()
        self._playback_state = "stopped"

    # ------------------------------------------------------------------
    # offline reference analysis (explicit user action only)
    # ------------------------------------------------------------------
    def _analysis_options(self) -> dict[str, Any]:
        return {
            "channel": int(self._settings.get("spectrumChannel", 0)),
            "nfft": int(self._settings.get("spectrumNfft", 2048)),
            "pairFirst": int(self._settings.get("pairFirst", 0)),
            "pairSecond": int(self._settings.get("pairSecond", 1)),
            "palette": str(self._settings.get("stftPalette", "viridis")),
        }

    @Slot(str)
    def runOfflineAnalysis(self, kind: str) -> None:  # noqa: N802
        # Removed from the product: the PC must not compute acoustic algorithms.
        self._notify("warn", self.t("toast.offline_removed"),
                     self.t("toast.offline_removed_detail"))

    # ------------------------------------------------------------------
    # page data properties
    # ------------------------------------------------------------------
    @Property("QVariantMap", notify=dataChanged)
    def overviewData(self) -> dict[str, Any]:  # noqa: N802
        return self._overview_cache

    @Property("QVariantMap", notify=dataChanged)
    def instrumentDashboard(self):
        data=dict(getattr(self,'_dashboard',{}));data['connected']=self._connection.get('state')=='connected'
        data['eventCount']=len(self._events);data['refreshHz']=self._live_fft_frames/max(.001,time.monotonic()-self._live_fft_started) if self._live_fft_started else None
        data['fresh']=bool(self._frame_time and _now()-self._frame_time<2)
        return data

    @Property(float, notify=dataChanged)
    def audioSampleRate(self) -> float:  # noqa: N802
        """Lightweight telemetry scalar for status/inspector strips."""
        try:
            return float(self._audio_meta.get("sampleRateHz") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @Property("QVariantMap", notify=dataChanged)
    def timeDomainData(self) -> dict[str, Any]:  # noqa: N802
        """Cached waveform display payload (see _build_time_domain_data).

        Several always-visible shell components read this property on every
        telemetry tick; without the cache the six 12000-sample rings were
        downsampled again for every binding read.
        """
        key = (self._wave_revision, self._source,
               self._settings.get("stackedWaveform", True),
               self._settings.get("timeWindowSeconds", 2.0),
               self._audio_meta.get("sampleRateHz"),
               self._replay is not None, self._language)
        cached = self._time_domain_cache
        if cached is not None and cached[0] == key:
            return cached[1]
        data = self._build_time_domain_data()
        self._time_domain_cache = (key, data)
        return data

    def _build_time_domain_data(self) -> dict[str, Any]:
        channels = []
        colors = self.theme.channelColors
        names = self.theme.channelNames
        source = self._wave_ring
        points = 1600
        available = any(len(series) > 8 for series in source)
        if self._replay is not None and len(self._replay_ring[0]) > 8:
            source = self._replay_ring
            available = True
        for index in range(6):
            values = _downsample(source[index], points)
            channels.append({
                "name": f"CH{index + 1}",
                "color": colors[index] if isinstance(colors, list) else "#007AFF",
                "visible": True,
                "values": values,
                "nameLabel": names[index] if isinstance(names, list) else f"CH{index + 1}",
            })
        sample_rate = self._audio_meta.get("sampleRateHz") or None
        start_index = self._wave_start or None
        source = self._source
        if self._replay is not None and len(self._replay_ring[0]) > 8:
            sample_rate = float(self._replay.rate)
            start_index = str(self._replay.manifest.get("firstSampleIndex") or "")
            source = "file-replay"
        return {
            "available": available,
            "channels": channels,
            "sampleRate": sample_rate,
            "startSampleIndex": start_index,
            "gaps": [],
            "stacked": bool(self._settings.get("stackedWaveform", True)),
            "sourceKind": source,
            "reason": "" if available else self.t("empty.no_audio"),
            "note": self.t("display.extraction_note"),
            "timeWindowSeconds": (len(self._wave_ring[0])/sample_rate if self._audio_meta.get('windowedLive') and sample_rate else float(self._settings.get("timeWindowSeconds",2.0))),
        }

    def _pl_analysis(self, key: str) -> dict[str, Any] | None:
        data = self._analysis.get(key)
        allowed = {"pl-live", "test-fixture"} if self._fixture_active else {"pl-live"}
        return data if isinstance(data, dict) and data.get("sourceKind") in allowed else None

    @Property("QVariantMap", notify=dataChanged)
    def spectrumData(self) -> dict[str, Any]:  # noqa: N802
        data = self._pl_analysis("spectrum")
        if data:
            return data
        return {"available": False, "sourceKind": "none",
                "reason": self.t("pl.wait_data"),
                "note": self.t("pl.data_note")}

    @Property("QVariantMap", notify=dataChanged)
    def stftData(self) -> dict[str, Any]:  # noqa: N802
        data = self._pl_analysis("stft")
        if data:
            return data
        return {"available": False, "sourceKind": "none",
                "reason": self.t("pl.wait_data"),
                "note": self.t("pl.data_note")}

    @Property("QVariantList", notify=dataChanged)
    def plPlotCards(self) -> list[dict[str, Any]]:  # noqa: N802
        """Only known PL chart families with actual source-labelled display DTOs.

        No arbitrary XY/matrix/file/PC-analysis entry is promoted into the product.
        Missing service layout metadata deliberately yields no chart card.
        """
        cards = []
        allowed_sources = {"pl-live"}
        if self._fixture_active:
            allowed_sources.add("test-fixture")
        def add(key, kind, title, data):
            if isinstance(data, dict) and data.get("available") is True and data.get("sourceKind") in allowed_sources:
                cards.append({"id":key,"kind":kind,"title":self.t(title),"data":data})
        add("fft", "line", "plots.spectrum", self._analysis.get("spectrum"))
        add("octave", "bands", "plots.bands", self._analysis.get("bands"))
        stft = self._analysis.get("stft") or {}
        if stft.get("imageUrl"):
            add("stft", "heatmap", "plots.spectrogram", stft)
        if stft.get("frames"):
            add("waterfall", "waterfall", "spectrum.waterfall", stft)
        pair = self._analysis.get("pair") or {}
        if pair.get("available") and pair.get("sourceKind") in allowed_sources:
            for key, title in (("coherence","plots.coherence"),("phase","plots.phase"),("csd","plots.csd")):
                data = pair.get(key)
                if isinstance(data,dict) and data.get("series"):
                    cards.append({"id":key,"kind":"line","title":self.t(title),"data":data})
        add("cepstrum", "line", "plots.cepstrum", self._analysis.get("periodic"))
        directional = self._pl_analysis("directional") or {}
        if (directional.get("imageUrl") and directional.get("azimuthRange")
                and directional.get("elevationRange") and directional.get("colorScale")):
            add("das_map", "polar", "plots.das", directional)
        return cards

    @Property("QVariantMap", notify=dataChanged)
    def plInterface(self) -> dict[str, Any]:  # noqa: N802
        connected = self._connection.get("state") == "connected"
        caps = self._capabilities
        service = self._service_snapshot or {}
        return {"connected": connected, "controlHeld": self._control_held,
                "canSubscribe": connected and (caps.get("liveResults") == "available" or caps.get("livePcm") == "available" or bool(caps.get("serviceSnapshots"))),
                "canStartTask": connected and self._control_held and caps.get("taskControl") == "available",
                "canRecord": connected and self._control_held and caps.get("rawRecording") == "available",
                "taskState": caps.get("taskControl", "not_ready"),
                "serviceId": service.get("serviceId"), "descriptor": service.get("descriptor"),
                "generation": service.get("generation"), "config": service.get("config"),
                "sourceFrame": service.get("sourceFrame"), "sampleIndex": service.get("sampleIndex"),
                "wordCount": (service.get("words") or {}).get("count"),
                "decodedReady": service.get("decoded") is not None,
                "missing": list(caps.get("missing") or [])}

    @Property("QVariantMap", notify=dataChanged)
    def bandsData(self) -> dict[str, Any]:  # noqa: N802
        data = self._pl_analysis("bands")
        if data:
            return data
        return {"available": False, "sourceKind": "none",
                "reason": self.t("pl.wait_data"),
                "note": self.t("pl.data_note")}

    @Property("QVariantMap", notify=dataChanged)
    def multichannelData(self) -> dict[str, Any]:  # noqa: N802
        data = self._pl_analysis("pair")
        if data:
            return data
        return {"available": False, "sourceKind": "none",
                "reason": self.t("pl.wait_data"),
                "note": self.t("pl.data_note")}

    @Property("QVariantMap", notify=dataChanged)
    def periodicData(self) -> dict[str, Any]:  # noqa: N802
        data = self._pl_analysis("periodic")
        if data:
            return data
        return {"available": False, "sourceKind": "none",
                "reason": self.t("pl.wait_data"),
                "note": self.t("pl.data_note")}

    @Property("QVariantMap", notify=dataChanged)
    def directionalData(self) -> dict[str, Any]:  # noqa: N802
        data = self._pl_analysis("directional")
        if data:
            return data
        features = [item for item in self._page_features.get("directional", [])
                    if item.get("role") == "primary"]
        return {"available": False, "sourceKind": "none",
                "reason": self.t("empty.directional_unavailable"),
                "features": features,
                "note": self.t("note.directional_boundary")}

    @Property("QVariantMap", notify=dataChanged)
    def eventsData(self) -> dict[str, Any]:  # noqa: N802
        entries=[]
        for event in self._events:
            e=dict(event);reason=int(e.get('clipReason',0))&255
            category='声音增强' if reason&1 else '频带变化' if reason&2 else '规律声音中断' if reason&4 else '声音变化'
            if self._language=='en':category='Sound increase' if reason&1 else 'Band change' if reason&2 else 'Sound interruption' if reason&4 else 'Sound change'
            date_ms=e.get('createdUnixMs') or (e.get('file') or {}).get('receivedUnixMs')
            e['displayName']=time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(int(date_ms)/1000)) if date_ms else ('时间未知' if self._language=='zh' else 'Time unknown')
            e['category']=category
            e['timeText']=('设备保存时间' if e.get('createdUnixMs') else '接收时间（原事件时间未知）') if self._language=='zh' else ('Device saved time' if e.get('createdUnixMs') else 'Received time (original time unknown)')
            entries.append(e)
        runtime=getattr(self._feature_facade,'_runtime',None)
        job=runtime._active_feature_job('event_trigger') if runtime else None
        pg=dict(job.progress) if job else {}
        queues=self._status.get('queues') or {}
        return {"events": entries,
                "selected": self._event_selected,
                "available": True if self._connection.get("state") == "connected" else False,
                "reason": "" if self._connection.get("state") == "connected"
                else self.t("empty.not_connected"),
                "monitoring": {"available":True,"active":bool(job),"phase":pg.get('phase','idle'),"progress":pg},
                "storage":queues,"downloading":self._event_download_inflight,"clearing":self._event_clear_pending,
                "features": list(self._page_features.get("events", []))}

    @Property("QVariantMap", notify=dataChanged)
    def monitorData(self) -> dict[str, Any]:  # noqa: N802
        data = dict(self._monitor)
        data["settings"] = dict(self._monitor["settings"])
        data["connected"] = self._connection.get("state") == "connected"
        data["eventCount"] = len(self._events)
        data["backendConfigAvailable"] = False
        data["requiresBackendConfig"] = False
        data["note"] = self.t(str(self._monitor.get("noteKey", "events.monitor.local_only")))
        return data

    @Property("QVariantMap", notify=dataChanged)
    def recordingData(self) -> dict[str, Any]:  # noqa: N802
        return {"recording": dict(self._recording),
                "replay": ({**self._replay.info(), "position": self._replay_position,
                            "durationSeconds": self._replay_duration,
                            "playbackState": self._playback_state}
                           if self._replay is not None else None),
                "analysis": self._analysis.get("levels") or [],
                "exportAvailable": self._connection.get("state") == "connected",
                "features": list(self._page_features.get("recording", []))}

    @Property("QVariantMap", notify=dataChanged)
    def roomData(self) -> dict[str, Any]:  # noqa: N802
        return {"available": False, "sourceKind": "none",
                "reason": self.t("empty.room_unavailable"),
                "features": list(self._page_features.get("room", []))}

    @Property("QVariantMap", notify=dataChanged)
    def reportData(self) -> dict[str, Any]:  # noqa: N802
        return {"lastPath": self._report_path,
                "sourceKind": self._source,
                "ready": self._replay is not None or self._last_frame is not None,
                "features": list(self._page_features.get("report", []))}

    @Property("QVariantMap", notify=dataChanged)
    def diagnosticsData(self) -> dict[str, Any]:  # noqa: N802
        return {"path": str(self.user_root),
                "logsPath": str(self.user_root / "logs"),
                "recent": list(self._diagnostics_cache.get("local") or [])[-60:],
                "device": self._diagnostics_cache.get("device") or None,
                "versions": {"app": VERSION, "build": BUILD_DATE,
                             "backend": getattr(self.bridge, "backendVersion", ""),
                             "protocol": self._hello.get("protocolVersion"),
                             "firmware": self._device.get("firmwareId")},
                "fixture": {"active": self._fixture_active,
                            "info": getattr(self, "_fixture_info", None)}}

    @Property("QVariantMap", notify=dataChanged)
    def aboutData(self) -> dict[str, Any]:  # noqa: N802
        return {"nameZh": APP_NAME_ZH, "nameEn": APP_NAME_EN,
                "version": VERSION, "buildDate": BUILD_DATE,
                "authors": AUTHORS, "school": SCHOOL,
                "python": "3.12", "qt": "6.12",
                "backend": self._hello.get("serverVersion", "not connected"),
                "license": "LGPL-3.0 (Qt/PySide6) · ISC (Lucide icons)",
                "assets": str(ASSETS_DIR)}

    def _recompute_overview(self) -> None:
        features = self._features
        status_counts = {"available": 0, "experimental": 0, "not_ready": 0, "unsupported": 0}
        for feature in features:
            status = str(feature.get("status", "not_ready"))
            if status in status_counts:
                status_counts[status] += 1
        latest = self._last_frame or {}
        snapshot = self._last_snapshot or {}
        sensors = snapshot.get("sensors") if isinstance(snapshot, dict) else None
        self._overview_cache = {
            "connection": dict(self._connection),
            "device": dict(self._device),
            "capabilities": dict(self._capabilities),
            "sourceKind": self._source,
            "sourceDetail": dict(self._source_detail),
            "frame": latest or None,
            "features": {"total": len(features), **status_counts,
                         "liveAvailable": status_counts["available"]},
            "recording": dict(self._recording),
            "jobs": list(self._jobs.values()),
            "events": list(self._events[:8]),
            "channels": ([{"label": f"CH{i + 1}",
                           "color": self.theme.channelColors[i],
                           "samples": len(self._wave_ring[i])}
                          for i in range(6)]),
            "sensors": sensors,
            "gaps": list(self._gaps[-6:]),
            "fixtureActive": self._fixture_active,
            "replay": self._replay is not None,
            "note": self.t("overview.scope_note"),
        }

    # ------------------------------------------------------------------
    # status tick / diagnostics / report / export
    # ------------------------------------------------------------------
    def _tick_status(self) -> None:
        stale = False
        if self._frame_time:
            stale = (_now() - self._frame_time) > 3.0
        self._status = {
            "sourceKind": self._source,
            "sourceLabel": self.dataSourceLabel,
            "connection": self._connection.get("state"),
            "controlHeld": bool(self._capabilities.get("controlHeld")),
            "sampleRateHz": (self._source_detail.get("sampleRateHz")),
            "stale": stale,
            "gaps": len(self._gaps),
            "jobsPending": sum(1 for job in self._jobs.values()
                               if job.get("state") not in ("completed", "failed", "canceled")),
            "recordingState": self._recording.get("state", "idle"),
            "fixture": self._fixture_active,
            "replay": self._replay is not None,
            "temperatureC": ((self._last_snapshot or {}).get("temperatureC")
                             if isinstance(self._last_snapshot, dict) else None),
            "humidityRaw": ((self._last_snapshot or {}).get("humidityRaw")
                            if isinstance(self._last_snapshot, dict) else None),
            "soundSpeedMps": ((self._last_snapshot or {}).get("soundSpeedMps")
                              if isinstance(self._last_snapshot, dict) else None),
            "updated": self._now_iso(),
            "liveFrameReceiveHz": self._live_fft_frames/max(.001,time.monotonic()-self._live_fft_started) if self._live_fft_started else 0,
            "liveFrameDispatchMaxMs": self._live_fft_max_dispatch_ms,
            "liveFramesCoalesced": self._live_fft_coalesced,
        }
        self._schedule_changed()

    @Slot()
    def refreshDiagnostics(self) -> None:  # noqa: N802
        self._next_request("diagnostics")
        self.bridge.readDiagnostics(200)

    @Slot(str)
    def openPath(self, path: str) -> None:  # noqa: N802
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    @Slot(str)
    def exportRecordingData(self, directory: str = "") -> None:  # noqa: N802
        if self._connection.get("state") != "connected":
            self._notify("warn", self.t("toast.export_requires_connection"),
                         self.t("toast.export_requires_connection_detail"))
            return
        self._next_request("export")
        try:
            self.bridge.exportData(directory)
        except RuntimeError:
            return

    @Slot(str, str, str)
    def generateReport(self, title: str, note: str, imagesJson: str) -> None:  # noqa: N802
        self._set_busy(True, self.t("busy.report"))
        try:
            images: list[dict[str, Any]] = []
            try:
                parsed = json.loads(imagesJson or "[]")
                if isinstance(parsed, list):
                    images = [item for item in parsed if isinstance(item, dict)]
            except ValueError:
                images = []
            report_dir = self.user_root / "reports"
            report_dir.mkdir(parents=True, exist_ok=True)
            # Second-resolution stamps collided when a report was generated twice
            # in the same second and silently overwrote the earlier files.
            import uuid
            stamp = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
            html_path = report_dir / f"report-{stamp}.html"
            pdf_path = report_dir / f"report-{stamp}.pdf"
            body = self._render_report_html(title, note, images)
            html_path.write_text(body, encoding="utf-8")
            self._render_pdf(body, pdf_path)
            pdf_ok = False
            try:
                pdf_ok = pdf_path.is_file() and pdf_path.stat().st_size > 0
            except OSError:
                pdf_ok = False
            if not pdf_ok:
                try:
                    pdf_path.unlink(missing_ok=True)
                except OSError:
                    pass
                self._report_path = str(html_path)
                self._notify("warn", self.t("toast.report_failed"),
                             "PDF export failed; HTML report saved: " + str(html_path))
                return
            self._report_path = str(html_path)
            self._notify("info", self.t("toast.report_saved"), str(html_path))
        except Exception as exc:  # noqa: BLE001
            self._notify("error", self.t("toast.report_failed"), str(exc)[:220])
        finally:
            self._set_busy(False)
            self._schedule_changed()

    def _normalize_exported_manifest(self, manifest_path: str) -> None:
        """Frozen backend appends a literal backslash-n; rewrite valid JSON.

        Documented as backend gap FRONTEND-EXPORT-1; removed once the backend is
        unfrozen and fixed. The exported file remains byte-compatible otherwise.
        """
        try:
            path = Path(manifest_path)
            text = path.read_text(encoding="utf-8")
            cleaned = text.rstrip()
            if cleaned.endswith("\\n"):
                cleaned = cleaned[:-2].rstrip()
            if not cleaned.endswith("}"):
                return
            payload = json.loads(cleaned)
            if not isinstance(payload, dict):
                return
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        except (OSError, ValueError):
            return

    def _render_report_html(self, title: str, note: str, images: list[dict[str, Any]]) -> str:
        source = self.t("source." + self._source.replace("-", "_"))
        replay_info = self._replay.info() if self._replay else {}
        rows = [
            (self.t("report.field.source"), source),
            (self.t("report.field.device"), str(self._device.get("deviceId", "—"))),
            (self.t("report.field.firmware"), str(self._device.get("firmwareId", "—"))),
            (self.t("report.field.sample_rate"), str(replay_info.get("sampleRateHz")
                                                     or (self._last_frame or {}).get("sampleRateHz")
                                                     or "—")),
            (self.t("report.field.recording"), str(replay_info.get("recordingId", "—"))),
            (self.t("report.field.duration"),
             f"{float(replay_info.get('durationSeconds') or 0.0):.3f} s"),
            (self.t("report.field.gaps"), str(len(self._gaps))),
            (self.t("report.field.version"), f"{VERSION} / {BUILD_DATE}"),
            (self.t("report.field.authors"), AUTHORS),
            (self.t("report.field.school"), SCHOOL),
        ]
        table = "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(v)}</td></tr>"
                        for k, v in rows)
        figures = []
        for item in images:
            path = str(item.get("path") or "")
            if not path or not Path(path).is_file():
                continue
            data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
            figures.append(
                f"<figure><img src='data:image/png;base64,{data}' "
                f"style='max-width:100%;border:1px solid #dce1e7;border-radius:6px'/>"
                f"<figcaption>{html.escape(str(item.get('caption') or ''))}</figcaption></figure>")
        note_block = f"<p class='note'>{html.escape(note)}</p>" if note else ""
        return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>{html.escape(title or APP_NAME_ZH)}</title>
<style>
body{{font:14px 'Segoe UI','Microsoft YaHei UI',sans-serif;color:#17212d;background:#f5f6f8;margin:0;padding:32px}}
main{{max-width:980px;margin:0 auto;background:#fff;border:1px solid #dce1e7;border-radius:10px;padding:36px 44px}}
h1{{font-size:24px;margin:0 0 6px}} .sub{{color:#5f6b7a;margin:0 0 24px}}
table{{border-collapse:collapse;width:100%;margin:18px 0}}
th,td{{text-align:left;padding:7px 10px;border-bottom:1px solid #eef1f4;font-size:13px}}
th{{color:#5f6b7a;font-weight:600;width:180px}}
h2{{font-size:17px;margin:26px 0 10px;border-top:1px solid #eef1f4;padding-top:18px}}
figure{{margin:16px 0}} figcaption{{color:#5f6b7a;font-size:12px;margin-top:6px}}
.note{{color:#5f6b7a;background:#f7f9fb;border-left:3px solid #c6cdd6;padding:10px 14px;font-size:13px}}
.foot{{margin-top:26px;color:#9aa6b4;font-size:12px}}
</style></head><body><main>
<h1>{html.escape(title or APP_NAME_ZH)}</h1>
<p class="sub">{html.escape(APP_NAME_ZH)} / {html.escape(APP_NAME_EN)} · {VERSION}</p>
{note_block}
<h2>{html.escape(self.t('report.section.measurement'))}</h2>
<table>{table}</table>
<h2>{html.escape(self.t('report.section.figures'))}</h2>
{''.join(figures) or '<p class="sub">' + html.escape(self.t('report.no_figures')) + '</p>'}
<h2>{html.escape(self.t('report.section.scope'))}</h2>
<p class="note">{html.escape(self.t('report.scope_note'))}</p>
<p class="foot">{html.escape(self.t('report.footer').format(authors=AUTHORS, school=SCHOOL))}</p>
</main></body></html>"""

    def _render_pdf(self, body: str, pdf_path: Path) -> None:
        try:
            from PySide6.QtGui import QTextDocument
            from PySide6.QtPrintSupport import QPrinter
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(str(pdf_path))
            document = QTextDocument()
            document.setHtml(body)
            document.print_(printer)
        except Exception:
            pdf_path.write_bytes(b"")

    @Slot(str)
    def saveDiagnosticsReport(self, directory: str) -> None:  # noqa: N802
        target = Path(directory or (self.user_root / "exports"))
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"diagnostics-{time.strftime('%Y%m%d-%H%M%S')}.json"
        payload = {"application": {"version": VERSION, "build": BUILD_DATE},
                   "connection": self._connection, "capabilities": self._capabilities,
                   "device": self._device, "status": self._status,
                   "settings": {key: value for key, value in self._settings.items()
                                if key not in ("reportNote",)},
                   "notifications": self._notifications[:100]}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        self._notify("info", self.t("toast.diagnostics_saved"), str(path))

    @Slot(str)
    def selectEvent(self, eventId: str) -> None:  # noqa: N802
        self._event_selected = str(eventId)
        self._schedule_changed()

    @Slot()
    def prepareExit(self) -> None:  # noqa: N802
        """Best-effort graceful stop for window close (never blocks the GUI thread)."""
        try:
            self._persist_feature_history()
        except Exception:  # noqa: BLE001 - exit must never be blocked
            pass
        self._export_executor.shutdown(wait=False, cancel_futures=True)
        if self._live_fft_worker:self._live_fft_worker.stop()
        try:
            if self._feature_timer is not None:
                self._feature_timer.stop()
        except Exception:  # noqa: BLE001
            pass
        if self._feature_facade is not None:
            try:
                self._feature_facade.shutdown()
            except Exception:  # noqa: BLE001
                pass
        try:
            if self._recording.get("state") == "recording":
                self.bridge.stopRecording()
        except Exception:
            pass
        try:
            if self._playback_state == "playing":
                self.bridge.setPlaybackState("stopped")
        except Exception:
            pass
        try:
            self._save_settings()
        except Exception:
            pass

    @Slot(str, result=str)
    def assetSource(self, relative: str) -> str:  # noqa: N802
        candidate = (ASSETS_DIR / str(relative)).resolve()
        try:
            if not str(candidate).startswith(str(ASSETS_DIR.resolve())):
                return ""
        except OSError:
            return ""
        return QUrl.fromLocalFile(str(candidate)).toString() if candidate.is_file() else ""

    @Slot(str, str, result=str)
    def iconSource(self, name: str, color: str) -> str:  # noqa: N802
        """Return a cached, theme-colored copy of a local Lucide SVG."""
        safe = re.sub(r"[^a-z0-9-]", "", str(name).lower())
        if not safe:
            return ""
        color_key = re.sub(r"[^0-9a-fA-F]", "", str(color)) or "17212d"
        cache_dir = self.user_root / "ui" / "icons"
        cache_dir.mkdir(parents=True, exist_ok=True)
        target = cache_dir / f"tabler1-{safe}-{color_key}.svg"
        if target.is_file():
            return QUrl.fromLocalFile(str(target)).toString()
        source = ASSETS_DIR / "icons" / f"{safe}.svg"
        if not source.is_file():
            return ""
        try:
            payload = source.read_text(encoding="utf-8")
        except OSError:
            return ""
        payload = payload.replace("currentColor", color if color.startswith("#") else "#" + color_key)
        try:
            target.write_text(payload, encoding="utf-8")
        except OSError:
            return QUrl.fromLocalFile(str(source)).toString()
        return QUrl.fromLocalFile(str(target)).toString()

    @Slot(result=str)
    def userDataDirectory(self) -> str:  # noqa: N802
        return str(self.user_root)
