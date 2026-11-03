"""Offscreen capture for the device-scoped product (developer harness).

Every capture is SIMULATED / test-fixture evidence:
  * the UI is connected to the real host fixture gateway
    (deployment/echo_feature_closure_20261025/ps/build/host/test-feature-server.exe,
    sourceKind=test-fixture, numericDSPVerified=false) when available, otherwise
    to the frozen backend mock demo;
  * every PNG gets a stamped footer naming the fixture source, hardwareState
    NOT_TESTED, page, size and DPI, so a screenshot can never be mistaken for
    pl-live or board evidence.

Sizing: QML opens the window maximized with Math.min(1920, Screen.availableWidth)
which, on the offscreen platform (800x800 virtual screen), produced 796x796
grabs.  This tool forces Windowed visibility, clears the QML size bindings,
relaxes the QML minimum size when the requested logical size is smaller
(150%/200% DPI), and verifies the grabbed PNG has exactly the requested pixel
size.  A capture manifest records requested/actual sizes, DPI/device pixel
ratio, sourceKind and verification results.

DPI is applied by re-executing this file once per DPI with QT_SCALE_FACTOR set
before QGuiApplication is created; the parent process merges worker manifests.

Usage:
    apps/sixmic-desktop/.venv/Scripts/python.exe apps/sixmic-desktop/ui/tools/ui_capture.py
    ... --dpis 100 --sizes 1920x1080,1280x800 --quick
    ... --demo          (do not start the host fixture gateway)
    ... --output DIR
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

APP_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = APP_ROOT.parents[1]
DEPLOY_ROOT = REPO_ROOT / "deployment" / "echo_feature_closure_20261025"
DEFAULT_OUT = APP_ROOT / "docs" / "frontend" / "screenshots" / "feature_wiring_20261026"
DEFAULT_SIZES = ((1920, 1080), (1280, 800))
DEFAULT_DPIS = (100, 150, 200)
PRODUCT_MIN = (1280, 800)

BASE_PAGES = (
    ("overview", "overview", None),
    ("time", "time", None),
    ("spectrum", "spectrum", None),
    ("bands", "bands", None),
    ("multichannel", "multichannel", None),
    ("events", "events", None),
    ("recording", "recording", None),
    ("diagnostics", "diagnostics", None),
    ("settings", "settings", None),
    ("about", "about", None),
    ("advanced_plots", "advanced", 0),
    ("advanced_periodic", "advanced", 1),
    ("advanced_directional", "advanced", 2),
    ("advanced_room", "advanced", 3),
)

#: one representative feature per spec page (first entry of the page's groups)
WORKSPACE_FLOWS = (
    {"name": "waveform", "page": "time", "sub": None, "feature": "io_pcm", "flow": "single"},
    {"name": "levels", "page": "time", "sub": None, "feature": "levels_core", "flow": "single"},
    {"name": "spectrum_fft", "page": "spectrum", "sub": None, "feature": "fft", "flow": "single"},
    {"name": "spectrum_psd", "page": "spectrum", "sub": None, "feature": "psd", "flow": "single"},
    {"name": "stft_2d_3d", "page": "spectrum", "sub": None, "feature": "stft", "flow": "stft"},
    {"name": "octave", "page": "bands", "sub": None, "feature": "octave", "flow": "single"},
    {"name": "third_octave", "page": "bands", "sub": None, "feature": "third_octave", "flow": "single"},
    {"name": "noise_rating", "page": "bands", "sub": None, "feature": "noise_rating",
     "flow": "dual", "confirm": ("referenceConfirmed", True)},
    {"name": "csd", "page": "multichannel", "sub": None, "feature": "csd", "flow": "single"},
    {"name": "coherence_phase", "page": "multichannel", "sub": None,
     "feature": "coherence_phase", "flow": "single"},
    {"name": "periodic", "page": "advanced", "sub": 1, "feature": "frequency_tracking",
     "flow": "single"},
    {"name": "cepstrum", "page": "advanced", "sub": 1, "feature": "cepstrum", "flow": "single"},
    {"name": "das_directed", "page": "advanced", "sub": 2, "feature": "directed_das",
     "flow": "single"},
    {"name": "das_full", "page": "advanced", "sub": 2, "feature": "full_das", "flow": "single"},
    {"name": "das_grid", "page": "advanced", "sub": 2, "feature": "spatial_grid", "flow": "single"},
    {"name": "ab_spectrum_freeze", "page": "spectrum", "sub": None,
     "feature": "spectrum_freeze", "flow": "reference_compare"},
    {"name": "relative_limit", "page": "spectrum", "sub": None,
     "feature": "relative_limit", "flow": "reference_compare"},
    {"name": "room_decay", "page": "advanced", "sub": 3, "feature": "room_decay", "flow": "room"},
    {"name": "room_clarity", "page": "advanced", "sub": 3, "feature": "room_clarity",
     "flow": "room"},
    {"name": "insulation", "page": "advanced", "sub": 3,
     "feature": "relative_insulation", "flow": "reference_measure"},
    {"name": "stipa_stages", "page": "advanced", "sub": 3,
     "feature": "stipa_experimental", "flow": "staged"},
    {"name": "event_monitor", "page": "events", "sub": None, "feature": "event_trigger",
     "flow": "monitor"},
)

BANNER = ("测试数据（非实测） | 模拟网关 | 硬件状态：未测试 | 数值未验证 | "
          "非设备实测，非实板，非声学验收")


def png_size(path: Path) -> tuple[int, int] | None:
    try:
        data = path.read_bytes()[:24]
    except OSError:
        return None
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return int(width), int(height)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


class CaptureWorker:
    def __init__(self, dpi: int, sizes: list[tuple[int, int]], output: Path,
                 use_gateway: bool, quick: bool, phase: str = "pages",
                 flow_start: int = 0, flow_count: int = 0) -> None:
        self.dpi = int(dpi)
        self.phase = str(phase)
        self.flow_start = int(flow_start)
        self.flow_count = int(flow_count)
        self.scale = self.dpi / 100.0
        self.sizes = sizes
        self.output = output
        self.use_gateway = use_gateway
        self.quick = quick
        self.gateway = None
        self.gateway_ready = None
        self.spool = output / "_tmp" / "spool"
        self.userdata = output / "_tmp" / "userdata"
        self.gateway_counter = 0
        self.manifest = {
            "worker": True,
            "phase": self.phase,
            "flowStart": self.flow_start,
            "flowCount": self.flow_count,
            "dpiRequested": self.dpi,
            "scaleFactor": self.scale,
            "sizes": [list(size) for size in sizes],
            "banner": BANNER,
            "shots": [],
            "errors": [],
        }

    # -- app ---------------------------------------------------------------
    def create_app(self):
        sys.path.insert(0, str(APP_ROOT))
        sys.path.insert(0, str(APP_ROOT / "backend"))
        import main as appmain
        return appmain, appmain.create_application()

    # -- fixture gateway ---------------------------------------------------
    def ensure_gateway(self) -> bool:
        if not self.use_gateway:
            return False
        exe = DEPLOY_ROOT / "ps" / "build" / "host" / "test-feature-server.exe"
        registry = DEPLOY_ROOT / "registry" / "INTERFACE_REGISTRY.json"
        profile = DEPLOY_ROOT / "ps" / "profiles" / "default" / "profile_init.smi"
        if not (exe.is_file() and registry.is_file() and profile.is_file()):
            self.manifest["errors"].append("fixture gateway files missing")
            return False
        self.spool.mkdir(parents=True, exist_ok=True)
        self.userdata.mkdir(parents=True, exist_ok=True)
        try:
            self.spool = self.output / "_tmp" / f"spool-{int(time.time() * 1000)}-{self.gateway_counter}"
            self.spool.mkdir(parents=True, exist_ok=True)
            self.gateway_counter += 1
            self.gateway = subprocess.Popen(
                [str(exe), str(registry), str(profile), str(self.spool)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                cwd=str(REPO_ROOT))
            line = self._read_line(self.gateway, timeout=30.0)
            if not line:
                raise RuntimeError(
                    f"no ready line: {(self.gateway.stderr.read() or '')[-500:]}")
            self.gateway_ready = json.loads(line)
            if self.gateway_ready.get("sourceKind") != "test-fixture":
                raise RuntimeError(f"unexpected sourceKind: {self.gateway_ready}")
            return True
        except Exception as exc:  # noqa: BLE001 - fall back to the frozen demo
            self.manifest["errors"].append(f"gateway start failed: {exc!r}")
            self._stop_gateway()
            return False

    @staticmethod
    def _read_line(proc, timeout: float = 30.0) -> str:
        import threading
        box: dict[str, object] = {}

        def reader() -> None:
            try:
                box["line"] = proc.stdout.readline()
            except Exception as exc:  # noqa: BLE001
                box["error"] = repr(exc)

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        thread.join(timeout)
        line = box.get("line")
        return str(line) if line else ""

    def reconnect_fresh_gateway(self, application, vm) -> None:
        """Give every workspace flow its own fresh fixture (60 s lifetime, no job leaks)."""
        if not self.use_gateway:
            return
        try:
            vm.disconnectDevice()
            self.pump(application, 0.4)
        except Exception:  # noqa: BLE001
            pass
        self._stop_gateway()
        self.ensure_gateway()
        if self.gateway is None or self.gateway_ready is None:
            return
        try:
            vm.connectDevice("127.0.0.1", int(self.gateway_ready["controlPort"]),
                             int(self.gateway_ready["binaryPort"]))
            self.wait_for(application,
                          lambda: (vm.connectionState == "connected"
                                   and bool(vm.featureStatus.get("featureApiEnabled"))),
                          timeout=15.0)
            self.pump(application, 0.4)
            self.manifest["gatewayPerFlow"] = int(
                self.manifest.get("gatewayPerFlow", 0)) + 1
        except Exception as exc:  # noqa: BLE001
            self.manifest["errors"].append(f"fresh gateway connect failed: {exc!r}")

    def _stop_gateway(self) -> None:
        proc = self.gateway
        self.gateway = None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass

    def gateway_alive(self) -> bool:
        return self.gateway is not None and self.gateway.poll() is None

    def ensure_live(self, application, vm) -> None:
        """Keep the 60 s-lifetime fixture gateway and the GUI connection alive."""
        if not self.use_gateway:
            return
        if self.gateway_alive():
            return
        self.ensure_gateway()
        if self.gateway is None or self.gateway_ready is None:
            self.manifest["captureMode"] = "frozen-mock-demo"
            try:
                vm.startFixtureDemo()
                self.wait_for(application, lambda: vm.connectionState == "connected",
                              timeout=10.0)
            except Exception as exc:  # noqa: BLE001
                self.manifest["errors"].append(f"fixture fallback failed: {exc!r}")
            return
        try:
            vm.connectDevice("127.0.0.1", int(self.gateway_ready["controlPort"]),
                             int(self.gateway_ready["binaryPort"]))
            self.wait_for(application,
                          lambda: bool(vm.featureStatus.get("featureApiEnabled")),
                          timeout=15.0)
            self.manifest["gatewayRestarts"] = int(self.manifest.get("gatewayRestarts", 0)) + 1
        except Exception as exc:  # noqa: BLE001
            self.manifest["errors"].append(f"gateway reconnect failed: {exc!r}")

    # -- capture helpers ---------------------------------------------------
    @staticmethod
    def pump(application, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            application.processEvents()
            time.sleep(0.01)

    def wait_for(self, application, predicate, timeout: float, interval: float = 0.05) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                if predicate():
                    return True
            except Exception:  # noqa: BLE001
                pass
            application.processEvents()
            time.sleep(interval)
        return False

    @staticmethod
    def _advanced_page(window):
        try:
            from PySide6.QtCore import QObject
            return window.findChild(QObject, "advancedToolsPage")
        except Exception:  # noqa: BLE001
            return None

    def set_page(self, application, vm, window, page_id: str, sub_tab: int | None) -> None:
        vm.setCurrentPage(page_id)
        self.pump(application, 0.15)
        if sub_tab is not None:
            advanced = self._advanced_page(window)
            if advanced is not None:
                advanced.setProperty("subTab", int(sub_tab))
                self.pump(application, 0.35)
            else:
                self.manifest["errors"].append("advancedToolsPage object not found")

    @staticmethod
    def stamp(image, label: str, dpr: float):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QFont, QPainter
        width, height = image.width(), image.height()
        strip = max(24, int(round(24 * max(1.0, dpr))))
        painter = QPainter(image)
        try:
            painter.fillRect(0, height - strip, width, strip, QColor(8, 8, 10, 235))
            font = QFont()
            font.setPixelSize(max(10, int(round(11 * max(1.0, dpr)))))
            painter.setFont(font)
            painter.setPen(QColor(233, 230, 73, 255))
            text = BANNER + "  |  " + label
            metrics = painter.fontMetrics()
            painter.drawText(8, height - strip + int(strip * 0.68),
                             metrics.elidedText(text, Qt.TextElideMode.ElideRight,
                                                width - 16))
        finally:
            painter.end()
        return image

    def save_shot(self, application, window, vm, name: str, label: str,
                  requested: tuple[int, int], dpr: float, extra: dict | None = None) -> dict:
        application.processEvents()
        try:
            vm.dismissToast()
        except Exception:  # noqa: BLE001
            pass
        self.pump(application, 0.35)
        image = window.grabWindow()
        actual = (image.width(), image.height())
        image = self.stamp(image, label, dpr)
        path = self.output / f"{name}.png"
        ok = image.save(str(path), "PNG")
        record = {
            "name": name,
            "label": label,
            "file": path.name,
            "requestedWidth": requested[0],
            "requestedHeight": requested[1],
            "actualWidth": actual[0],
            "actualHeight": actual[1],
            "devicePixelRatio": round(dpr, 3),
            "dpiRequested": self.dpi,
            "dpiEffective": round(dpr * 100.0, 1),
            "matchesRequestedPixels": actual == requested,
            "saved": bool(ok),
            "sha256": sha256_file(path),
            "page": vm.currentPage,
            "sourceKind": vm.dataSource,
            "language": vm.language,
            "theme": getattr(vm, "themeMode", ""),
            "stampedTestFixture": True,
            "capturedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        try:
            status = vm.featureStatus
            record["featureStatus"] = {
                "featureApiEnabled": bool(status.get("featureApiEnabled")),
                "featureCount": status.get("featureCount"),
                "catalogComplete": bool(status.get("catalogComplete")),
                "sourceKind": status.get("sourceKind"),
                "reason": status.get("reason"),
            }
        except Exception:  # noqa: BLE001
            record["featureStatus"] = None
        if extra:
            record.update(extra)
        if not record["matchesRequestedPixels"]:
            self.manifest["errors"].append(
                f"{name}: requested {requested} got {actual}")
        self.manifest["shots"].append(record)
        print(f"SHOT {name} {actual[0]}x{actual[1]} dpi={self.dpi} "
              f"dpr={dpr:.2f} saved={bool(ok)}", flush=True)
        return record

    def resize(self, application, window, size: tuple[int, int]) -> float:
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QWindow
        window.setVisibility(QWindow.Visibility.Windowed)
        self.pump(application, 0.2)
        try:
            window.setMinimumSize(QSize(0, 0))
        except Exception:  # noqa: BLE001
            pass
        screen = window.screen()
        dpr = float(screen.devicePixelRatio()) if screen is not None else 1.0
        logical = (max(320, int(round(size[0] / dpr))),
                   max(240, int(round(size[1] / dpr))))
        window.setProperty("width", logical[0])
        window.setProperty("height", logical[1])
        self.pump(application, 0.4)
        return dpr

    # -- main worker -------------------------------------------------------
    def run(self) -> int:
        self.output.mkdir(parents=True, exist_ok=True)
        from PySide6.QtCore import qVersion
        started = time.monotonic()
        appmain, created = self.create_app()
        application, engine, bridge, vm, theme, images, qml = created
        roots = engine.rootObjects()
        if not roots:
            self.manifest["errors"].append("QML produced no root window")
            return 1
        window = roots[-1]
        self.manifest.update({
            "appVersion": getattr(vm, "version", ""),
            "appBuildDate": getattr(vm, "buildDate", ""),
            "qtVersion": qVersion(),
            "qml": str(qml),
        })
        gateway_ok = self.ensure_gateway()
        if gateway_ok:
            try:
                vm.connectDevice("127.0.0.1", int(self.gateway_ready["controlPort"]),
                                 int(self.gateway_ready["binaryPort"]))
                ready = self.wait_for(
                    application,
                    lambda: bool(vm.featureStatus.get("featureApiEnabled"))
                    and bool(vm.featureStatus.get("catalogComplete")),
                    timeout=15.0)
                self.manifest["captureMode"] = "host-fixture-gateway" if ready else "gateway-connected-no-catalog"
                self.manifest["gatewayReady"] = dict(self.gateway_ready)
            except Exception as exc:  # noqa: BLE001
                self.manifest["captureMode"] = "gateway-connect-failed"
                self.manifest["errors"].append(f"vm.connectDevice failed: {exc!r}")
                gateway_ok = False
        if not gateway_ok:
            self.manifest["captureMode"] = "frozen-mock-demo"
            try:
                vm.startFixtureDemo()
                self.wait_for(application, lambda: vm.connectionState == "connected",
                              timeout=10.0)
            except Exception as exc:  # noqa: BLE001
                self.manifest["errors"].append(f"startFixtureDemo failed: {exc!r}")
        self.manifest["connectionState"] = vm.connectionState
        self.manifest["featureStatusAtStart"] = dict(vm.featureStatus)
        self.pump(application, 0.8)

        vm.setThemeMode("dark")
        if self.phase == "pages":
            for size in self.sizes:
                self.capture_page_set(application, window, vm, size)
        if self.phase == "workspace":
            self.capture_workspaces(application, window, vm)
        self.manifest["elapsedSeconds"] = round(time.monotonic() - started, 2)
        try:
            vm.prepareExit()
            bridge.shutdown()
        except Exception:  # noqa: BLE001
            pass
        self._stop_gateway()
        return 0

    # -- page-set capture ------------------------------------------------
    def capture_page_set(self, application, window, vm, size: tuple[int, int]) -> None:
        dpr = self.resize(application, window, size)
        self.manifest["sizesDetected"] = {"requested": list(size),
                                          "devicePixelRatio": round(dpr, 3),
                                          "logical": [int(round(size[0] / dpr)),
                                                      int(round(size[1] / dpr))]}
        for shot_name, page_id, sub_tab in BASE_PAGES:
            self.ensure_live(application, vm)
            self.set_page(application, vm, window, page_id, sub_tab)
            try:
                vm.closeFeatureWorkspace()
            except Exception:  # noqa: BLE001
                pass
            self.pump(application, 0.2)
            self.save_shot(application, window, vm,
                           f"{shot_name}_{size[0]}x{size[1]}_dpi{self.dpi}",
                           f"{shot_name} {size[0]}x{size[1]} @ {self.dpi}%",
                           size, dpr)

    # -- feature workspace capture (charts with test-fixture data) --------
    def _ws(self, vm) -> dict:
        return dict(vm.featureWorkspace)

    def _wait_ws(self, application, vm, predicate, timeout: float = 40.0) -> bool:
        return self.wait_for(application, lambda: predicate(self._ws(vm)), timeout=timeout,
                             interval=0.03)

    def _ws_state(self, vm) -> str:
        return str(self._ws(vm).get("state") or "")

    def _chart_summary(self, vm) -> dict:
        chart = dict(self._ws(vm).get("chart") or {})
        series = chart.get("series") or []
        frames = chart.get("frames") or []
        categories = chart.get("categories") or []
        scalars = chart.get("scalarRows") or []
        channels = chart.get("channels") or []
        image_url = str(chart.get("imageUrl") or "")
        has_data = bool(series or frames or categories or scalars or channels or image_url
                        or (chart.get("text") and chart.get("kind") != "capability"))
        return {"kind": chart.get("kind"),
                "title": chart.get("title"),
                "seriesCount": len(series),
                "frameCount": len(frames),
                "categoryCount": len(categories),
                "scalarCount": len(scalars),
                "channelCount": len(channels),
                "hasImage": bool(image_url),
                "view3D": bool(chart.get("view3D")),
                "emptyReason": chart.get("emptyReason"),
                "hasData": has_data}

    def _flow_page(self, application, vm, window, flow: dict) -> None:
        self.set_page(application, vm, window, flow["page"], flow.get("sub"))

    def _open_feature(self, application, vm, feature_id: str) -> None:
        vm.openFeatureEntry(feature_id)
        self.pump(application, 0.5)

    def _run(self, application, vm, feature_id: str, *,
             expect_states: tuple[str, ...] = ("completed",),
             timeout: float = 40.0) -> dict:
        vm.runFeature(feature_id)
        self.wait_for(
            application,
            lambda: self._ws_state(vm) in expect_states
            or self._ws_state(vm) in ("failed", "unavailable"),
            timeout=timeout, interval=0.03)
        self.pump(application, 0.4)
        return self._ws(vm)

    def _assert_live_workspace(self, vm, flow: dict, label: str) -> str | None:
        """Lead requirement: never save a workspace shot that is not live fixture data."""
        connection = str(getattr(vm, "connectionState", ""))
        workspace = self._ws(vm)
        state = str(workspace.get("state") or "")
        source_kind = str(workspace.get("sourceKind") or "")
        chart = self._chart_summary(vm)
        monitor_ok = (flow.get("flow") == "monitor" and state in ("running", "stopped"))
        completed_ok = state == "completed"
        if connection != "connected":
            return f"connectionState={connection!r} != connected"
        if not (completed_ok or monitor_ok):
            return f"workspace.state={state!r} (must be completed; running only for monitor)"
        if source_kind != "test-fixture":
            return f"workspace.sourceKind={source_kind!r} != test-fixture"
        if not chart.get("hasData") and chart.get("kind") not in ("capability", "events"):
            return f"chart has no data (kind={chart.get('kind')!r})"
        return None

    def _capture_flow_state(self, application, window, vm, flow: dict, label: str,
                            extra: dict | None = None) -> None:
        invalid = self._assert_live_workspace(vm, flow, label)
        if invalid:
            self.manifest.setdefault("invalidWorkspaceShots", []).append(
                {"flow": flow["name"], "featureId": flow["feature"], "label": label,
                 "reason": invalid})
            self.manifest["errors"].append(
                f"workspace {flow['name']} {label} NOT captured: {invalid}")
            return
        charts = []
        for size in self.sizes:
            dpr = self.resize(application, window, size)
            self.pump(application, 0.35)
            chart = self._chart_summary(vm)
            charts.append(chart)
            workspace = self._ws(vm)
            payload = {"flow": flow["name"], "flowType": flow["flow"],
                       "featureId": flow["feature"],
                       "workspaceState": workspace.get("state"),
                       "workspaceLifecycle": workspace.get("lifecycle"),
                       "workspaceSourceKind": workspace.get("sourceKind"),
                       "workspaceError": workspace.get("error"),
                       "workspaceNotes": workspace.get("notes"),
                       "chart": chart}
            if extra:
                payload.update(extra)
            self.save_shot(application, window, vm,
                           f"workspace_{flow['name']}_{label}_{size[0]}x{size[1]}_dpi{self.dpi}",
                           f"workspace {flow['feature']} {label} "
                           f"{size[0]}x{size[1]} @ {self.dpi}%",
                           size, dpr, extra=payload)
        if charts:
            combined = dict(charts[0])
            combined["perSize"] = charts
            workspace = self._ws(vm)
            self.manifest.setdefault("workspaces", []).append(
                {"flow": flow["name"], "featureId": flow["feature"],
                 "workspaceState": workspace.get("state"),
                 "workspaceLifecycle": workspace.get("lifecycle"),
                 "workspaceSourceKind": workspace.get("sourceKind"),
                 "workspaceError": workspace.get("error"),
                 "workspaceNotes": workspace.get("notes"),
                 **combined})

    def capture_workspaces(self, application, window, vm) -> None:
        flows = list(WORKSPACE_FLOWS)
        if self.flow_count > 0:
            flows = flows[self.flow_start:self.flow_start + self.flow_count]
        else:
            flows = flows[self.flow_start:]
        self.manifest["flowsPlanned"] = [flow["name"] for flow in flows]
        for flow in flows:
            self.reconnect_fresh_gateway(application, vm)
            try:
                self._flow_page(application, vm, window, flow)
                self._open_feature(application, vm, flow["feature"])
            except Exception as exc:  # noqa: BLE001
                self.manifest["errors"].append(
                    f"workspace {flow['name']} open failed: {exc!r}")
                continue
            try:
                self._run_flow(application, window, vm, flow)
            except Exception as exc:  # noqa: BLE001
                self.manifest["errors"].append(
                    f"workspace {flow['name']} run failed: {exc!r}")
                self._capture_flow_state(application, window, vm, flow, "error",
                                         {"flowException": repr(exc)[:300]})
            finally:
                try:
                    vm.stopFeature(flow["feature"])
                except Exception:  # noqa: BLE001
                    pass
                self.pump(application, 0.2)

    def _run_flow(self, application, window, vm, flow: dict) -> None:
        feature = flow["feature"]
        kind = flow["flow"]
        confirm = flow.get("confirm")
        if confirm:
            vm.featureConfirm(feature, confirm[0], confirm[1])
            self.pump(application, 0.2)
        if kind == "single":
            self._run(application, vm, feature)
            self._capture_flow_state(application, window, vm, flow, "completed")
        elif kind == "dual":
            self._run(application, vm, feature, timeout=60.0)
            self._capture_flow_state(application, window, vm, flow, "completed")
        elif kind == "room":
            vm.featureConfirm(feature, "stimulus", "clap")
            self.pump(application, 0.2)
            self._run(application, vm, feature)
            self._capture_flow_state(application, window, vm, flow, "completed")
        elif kind == "reference_compare":
            first = self._run(application, vm, feature)
            second = self._run(application, vm, feature)
            self._capture_flow_state(application, window, vm, flow, "compare", {
                "firstRunState": first.get("state"),
                "secondRunState": second.get("state"),
                "references": dict(second.get("references") or {}),
            })
        elif kind == "reference_measure":
            first = self._run(application, vm, feature)
            vm.featureConfirm(feature, "chain-confirm", True)
            second = self._run(application, vm, feature)
            self._capture_flow_state(application, window, vm, flow, "measure", {
                "firstRunState": first.get("state"),
                "secondRunState": second.get("state"),
            })
        elif kind == "staged":
            first = self._run(application, vm, feature, timeout=60.0)
            vm.featureConfirm(feature, "testSignalConfirmed", True)
            self.pump(application, 0.2)
            vm.runFeature(feature)
            running_capture = self.wait_for(
                application,
                lambda: self._ws_state(vm) == "running", timeout=5.0, interval=0.01)
            if running_capture:
                self._capture_flow_state(application, window, vm, flow, "running", {
                    "firstRunState": first.get("state"),
                    "progress": dict((self._ws(vm).get("flow") or {})),
                })
            self._wait_ws(application, vm,
                          lambda ws: ws.get("state") in ("completed", "failed"), timeout=60.0)
            self.pump(application, 0.4)
            self._capture_flow_state(application, window, vm, flow, "completed", {
                "firstRunState": first.get("state"),
            })
        elif kind == "stft":
            self._run(application, vm, feature)
            self._capture_flow_state(application, window, vm, flow, "2d")
            vm.setFeatureViewOption(feature, "2D3D", True)
            self.pump(application, 0.5)
            self._capture_flow_state(application, window, vm, flow, "3d", {"view3D": True})
            vm.setFeatureViewOption(feature, "2D3D", False)
        elif kind == "monitor":
            self._run(application, vm, feature, expect_states=("running",))
            self._capture_flow_state(application, window, vm, flow, "running")
            vm.stopFeature(feature)
            self.wait_for(application,
                          lambda: self._ws_state(vm) in ("canceled", "failed"),
                          timeout=20.0, interval=0.03)
            self.pump(application, 0.3)
            self._capture_flow_state(application, window, vm, flow, "stopped")
        else:
            raise RuntimeError(f"unknown flow type {kind}")

    def write_manifest(self) -> Path:
        suffix = (f"_flows{self.flow_start}" if self.phase == "workspace" else "")
        path = self.output / f"_worker_{self.phase}_dpi{self.dpi}{suffix}.json"
        path.write_text(json.dumps(self.manifest, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        return path


def _parse_sizes(text: str) -> list[tuple[int, int]]:
    sizes = []
    for chunk in text.split(","):
        chunk = chunk.strip().lower()
        if not chunk:
            continue
        width, height = chunk.split("x")
        sizes.append((int(width), int(height)))
    return sizes


def run_parent(args) -> int:
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    sizes = _parse_sizes(args.sizes)
    dpis = [int(item) for item in args.dpis.split(",") if item.strip()]
    manifest_path = output / "capture_manifest.json"
    stale_files = list(output.glob("_worker_*.log")) + list(output.glob("_worker_*.json"))
    if not args.workspace_only:
        stale_files += list(output.glob("*.png"))
    for stale in stale_files:
        try:
            stale.unlink()
        except OSError:
            pass
    worker_manifests = []
    worker_failures = []
    runs: list[dict] = []
    if not args.workspace_only:
        runs.extend({"phase": "pages", "dpi": dpi, "flow_start": 0, "flow_count": 0}
                    for dpi in dpis)
    if not args.pages_only and not args.quick:
        batch = int(args.workspace_batch)
        for start in range(0, len(WORKSPACE_FLOWS), batch):
            runs.append({"phase": "workspace", "dpi": 100, "flow_start": start,
                         "flow_count": min(batch, len(WORKSPACE_FLOWS) - start)})
    for run in runs:
        phase, dpi = run["phase"], run["dpi"]
        suffix = (f"_flows{run['flow_start']}" if phase == "workspace" else "")
        worker_manifest = output / f"_worker_{phase}_dpi{dpi}{suffix}.json"
        if worker_manifest.exists():
            worker_manifest.unlink()
        env = dict(os.environ)
        env["QT_SCALE_FACTOR"] = f"{dpi / 100.0:g}"
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["QT_QUICK_BACKEND"] = "software"
        env["SIXMIC_DISABLE_UI_SCALE"] = "1"
        command = [sys.executable, str(Path(__file__).resolve()),
                   "--worker", "--dpi", str(dpi), "--sizes", args.sizes,
                   "--output", str(output), "--phase", phase,
                   "--flow-start", str(run["flow_start"]),
                   "--flow-count", str(run["flow_count"])]
        if args.demo:
            command.append("--demo")
        if args.quick:
            command.append("--quick")
        print(f"WORKER phase={phase} dpi={dpi} "
              f"flows={run['flow_start']}+{run['flow_count']} start", flush=True)
        completed = subprocess.run(command, env=env, text=True,
                                   capture_output=True, cwd=str(APP_ROOT))
        output_text = (completed.stdout or "") + (completed.stderr or "")
        (output / f"_worker_{phase}_dpi{dpi}.log").write_text(output_text, encoding="utf-8")
        print(output_text[-4000:], flush=True)
        if worker_manifest.is_file():
            worker_manifests.append(json.loads(worker_manifest.read_text(encoding="utf-8")))
        if completed.returncode != 0:
            worker_failures.append(
                f"{phase}/dpi{dpi}: worker exit {completed.returncode}")
            print(f"WORKER phase={phase} dpi={dpi} exit={completed.returncode}",
                  flush=True)
    shots = []
    worker_errors = []
    for manifest in worker_manifests:
        shots.extend(manifest.get("shots") or [])
        for error in manifest.get("errors") or []:
            worker_errors.append(f"dpi{manifest.get('dpiRequested')}: {error}")
    verification = []
    missing = []
    for shot in shots:
        path = output / shot["file"]
        size = png_size(path)
        ok = size is not None and size == (shot["requestedWidth"], shot["requestedHeight"])
        verification.append({"file": shot["file"], "expected": [shot["requestedWidth"],
                                                               shot["requestedHeight"]],
                             "actual": list(size) if size else None, "ok": ok})
        if not ok:
            missing.append(shot["file"])
    document = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "product": "SixMic3D device software (feature wiring)",
        "banner": BANNER,
        "sourceKind": "test-fixture",
        "simulated": True,
        "numericDSPVerified": False,
        "hardwareState": "NOT_TESTED",
        "tool": str(Path(__file__).resolve().relative_to(REPO_ROOT)),
        "captureMode": "host-fixture-gateway or frozen-mock-demo (per worker)",
        "requestedDpis": dpis,
        "requestedSizes": [list(size) for size in sizes],
        "productMinimumLogicalSize": list(PRODUCT_MIN),
        "note": "150/200% DPI captures use a logical size below the product "
                "minimum (1280x800); the window minimum is relaxed only to "
                "produce true-pixel DPI evidence. 100% captures are the "
                "supported layout size.",
        "workers": worker_manifests,
        "shots": shots,
        "shotCount": len(shots),
        "verification": verification,
        "svgOrPngDimensionCheck": {
            "checked": len(verification),
            "mismatched": missing,
        },
        "errors": worker_errors,
    }
    manifest_path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    for name in output.glob("_worker_dpi*.json"):
        try:
            name.unlink()
        except OSError:
            pass
    page_workers = [manifest for manifest in worker_manifests
                    if manifest.get("phase") == "pages"]
    workspace_workers = [manifest for manifest in worker_manifests
                         if manifest.get("phase") == "workspace"]
    pages_expected = len(page_workers) * len(sizes) * len(BASE_PAGES)
    page_shot_names = {shot["name"] for shot in shots
                       if any(shot["name"].startswith(page[0] + "_")
                              for page in BASE_PAGES)}
    flows_seen = {}
    for manifest in workspace_workers:
        for item in manifest.get("workspaces") or []:
            flows_seen[str(item.get("flow"))] = item
    required_flows = {flow["name"] for flow in WORKSPACE_FLOWS}
    missing_flows = sorted(required_flows - set(flows_seen))
    empty_charts = sorted(name for name, item in flows_seen.items()
                          if not item.get("hasData")
                          and item.get("kind") not in ("capability", "events"))
    print(f"CAPTURE_MANIFEST {manifest_path}")
    print(f"CAPTURE_SHOTS {len(shots)} checked={len(verification)} "
          f"mismatched={len(missing)} pagesExpected={pages_expected} "
          f"workers={len(worker_manifests)}/{len(runs)} "
          f"flows={len(flows_seen)}/{len(required_flows)} "
          f"emptyCharts={empty_charts[:8]} "
          f"failures={worker_errors + worker_failures}")
    document["workspaceFlows"] = {"seen": sorted(flows_seen),
                                  "missing": missing_flows,
                                  "emptyChartData": empty_charts}
    manifest_path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    if missing or worker_failures or len(page_shot_names) != pages_expected:
        print("CAPTURE_FAIL")
        return 1
    if workspace_workers and missing_flows:
        print("CAPTURE_FAIL missing workspace flows")
        return 1
    print("CAPTURE_OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offscreen test-fixture UI capture")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--dpi", type=int, default=100)
    parser.add_argument("--dpis", default=",".join(str(d) for d in DEFAULT_DPIS))
    parser.add_argument("--sizes", default=",".join(f"{w}x{h}" for w, h in DEFAULT_SIZES))
    parser.add_argument("--output", default=str(DEFAULT_OUT))
    parser.add_argument("--phase", choices=("pages", "workspace"), default="pages",
                        help=argparse.SUPPRESS)
    parser.add_argument("--flow-start", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--flow-count", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--workspace-batch", type=int, default=6,
                        help="feature-workspace flows per fresh worker process")
    parser.add_argument("--pages-only", action="store_true",
                        help="capture pages only (skip feature-workspace charts)")
    parser.add_argument("--workspace-only", action="store_true",
                        help="capture only feature-workspace charts (DPI 100)")
    parser.add_argument("--demo", action="store_true",
                        help="do not start the host fixture gateway")
    parser.add_argument("--quick", action="store_true",
                        help="pages only, no feature-workspace captures")
    args = parser.parse_args(argv)
    if args.worker:
        worker = CaptureWorker(args.dpi, _parse_sizes(args.sizes),
                               Path(args.output).resolve(), not args.demo, args.quick,
                               args.phase, args.flow_start, args.flow_count)
        code = worker.run()
        worker.write_manifest()
        return code
    return run_parent(args)


if __name__ == "__main__":
    raise SystemExit(main())
