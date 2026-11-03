"""SixMic3D desktop launcher.

Wires the frozen backend bridge into Qt Quick and loads the product QML UI.
This file stays a thin seam: no UI design, no protocol logic, no fake data.

Usage:
    SixMic3D.exe                        # product GUI
    SixMic3D.exe --self-test            # headless backend self-test (exit 0/1)
    SixMic3D.exe --backend-status       # backend stages/status JSON
    SixMic3D.exe --protocol-dir DIR     # explicit protocol contract data
    SixMic3D.exe --smoke-gui SECONDS    # offscreen GUI smoke run (exit 0/1)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent
_STYLE_CONFIGURED = False
BACKEND_ROOT = APP_ROOT / "backend"
UI_ROOT = APP_ROOT / "ui"
for extra in (str(BACKEND_ROOT), str(APP_ROOT)):
    if extra not in sys.path:
        sys.path.insert(0, extra)


def _candidate_roots(explicit: str | None) -> list[Path]:
    roots: list[Path] = []
    if explicit:
        roots.append(Path(explicit))
    if os.environ.get("SIXMIC_QML_ROOT"):
        roots.append(Path(os.environ["SIXMIC_QML_ROOT"]))
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        base = Path(meipass)
        roots += [base / "ui" / "qml", base / "ui", base]
    roots += [UI_ROOT / "qml", UI_ROOT, APP_ROOT]
    return roots


def find_main_qml(explicit: str | None) -> Path | None:
    for root in _candidate_roots(explicit):
        candidate = root / "main.qml"
        if candidate.is_file():
            return candidate
    return None


def run_self_test(protocol_dir: str | None) -> int:
    prepare_user_data_dir()
    from sixmic_backend.app.backend_check import run_self_test as backend_self_test
    return backend_self_test(protocol_dir)


def print_backend_status(protocol_dir: str | None) -> int:
    from sixmic_backend import __version__, BACKEND_STATUS
    from sixmic_backend.paths import protocol_data_candidates, user_data_dir

    qml = find_main_qml(None)
    payload = {
        "backendVersion": __version__,
        "stage": BACKEND_STATUS,
        "protocolDataCandidates": [str(path) for path in protocol_data_candidates(protocol_dir)],
        "userDataDir": str(user_data_dir()),
        "qmlFound": str(qml) if qml else None,
        "uiRoot": str(UI_ROOT),
        "note": "GUI product build; backend protocol/session layer is unchanged and frozen.",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


USER_DATA_SUBDIRS = ("logs", "data", "recordings", "events", "exports", "ui",
                     "evidence", "reports", "screenshots")


def _dir_is_writable(candidate: Path) -> bool:
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        probe = candidate / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def prepare_user_data_dir() -> Path | None:
    """Pick a writable data directory before any component touches user paths.

    A packaged app may run where %LOCALAPPDATA% is not writable (restricted
    profile / policy). Falling back to the portable directory, the temp folder
    or the launch directory keeps the UI usable instead of aborting startup.
    """
    explicit = os.environ.get("SIXMIC_USER_DATA_DIR", "").strip()
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    local = os.environ.get("LOCALAPPDATA", "").strip()
    legacy = Path(local) / "SixMic3D" if local else None
    if local:
        candidates.append(Path(local) / "echo")
        if legacy is not None:
            candidates.append(legacy)
    candidates.extend([
        APP_ROOT / "user-data",
        Path(tempfile.gettempdir()) / "echo",
        Path.cwd() / "echo-user-data",
        Path.home() / "echo",
    ])
    for candidate in candidates:
        if not _dir_is_writable(candidate):
            continue
        try:
            for name in USER_DATA_SUBDIRS:
                (candidate / name).mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        if (legacy is not None and candidate == (Path(local) / "echo")
                and legacy.is_dir()):
            try:
                import shutil
                shutil.copytree(legacy, candidate, dirs_exist_ok=True)
            except OSError:
                pass
        os.environ["SIXMIC_USER_DATA_DIR"] = str(candidate)
        return candidate
    return None


def apply_saved_ui_scale() -> None:
    """Use native Qt/OS DPI; migrate the former double75% presentation once."""
    data_dir = os.environ.get("SIXMIC_USER_DATA_DIR", "").strip()
    if not data_dir:
        return
    path = Path(data_dir) / "ui" / "ui_settings.json"
    try:
        settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not settings.get("nativeInstrumentUiApplied"):
            settings.update({"uiScale":1.0,"fontScale":1.0,"inspectorCollapsed":True,"nativeInstrumentUiApplied":True})
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(settings,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    except (OSError,ValueError,TypeError):
        return


def show_startup_error(message: str) -> None:
    """Best-effort native dialog so a windowed build reports instead of crashing."""
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance() or QApplication([])
        QMessageBox.critical(None, "echo", message)
        if app is not None:
            app.quit()
    except Exception:
        try:
            log = Path(tempfile.gettempdir()) / "echo-startup-error.log"
            log.write_text(message, encoding="utf-8", errors="replace")
        except OSError:
            pass
        print(message, file=sys.stderr)


def create_application(protocol_dir: str | None = None, qml_root: str | None = None,
                       argv: list[str] | None = None):
    """Create QGuiApplication + engine + backend bridge + app viewmodel.

    Returns (application, engine, bridge, app_view_model, theme, images, main_qml).
    Raises RuntimeError with a structured message on failure.
    """
    prepare_user_data_dir()
    apply_saved_ui_scale()
    main_qml = find_main_qml(qml_root)
    if main_qml is None:
        raise RuntimeError(json.dumps({
            "error": "QML_NOT_FOUND",
            "searched": [str(path) for path in _candidate_roots(qml_root)],
        }))
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine
    global _STYLE_CONFIGURED
    if not _STYLE_CONFIGURED:
        try:
            from PySide6.QtQuickControls2 import QQuickStyle
            QQuickStyle.setStyle("Basic")
        except Exception:
            pass
        _STYLE_CONFIGURED = True
    from sixmic_backend.errors import BackendError
    from sixmic_backend.qt.adapter import create_bridge
    try:
        from pc_client.qt_bridge import FeatureBackendBridge
    except Exception:  # noqa: BLE001
        FeatureBackendBridge = None
    from ui.viewmodels.app_view_model import AppViewModel
    from ui.viewmodels.plot_images import PlotImageProvider
    from ui.viewmodels.theme_source import ThemeSource

    if QGuiApplication.instance() is None:
        try:
            from PySide6.QtCore import Qt
            QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
                Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
            QGuiApplication.setAttribute(
                Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
        except Exception:
            pass
    application = QGuiApplication.instance() or QGuiApplication(argv or sys.argv)
    application.setApplicationName("echo")
    icon_path = APP_ROOT / "assets" / "branding" / "sixmic3d.ico"
    if icon_path.is_file():
        try:
            from PySide6.QtGui import QIcon
            application.setWindowIcon(QIcon(str(icon_path)))
        except Exception:
            pass
    try:
        from PySide6.QtGui import QFont, QFontDatabase
        font_dir = APP_ROOT / "assets" / "fonts"
        family = "Noto Sans CJK SC"
        for font_path in sorted(font_dir.glob("NotoSansCJKsc-*.otf")):
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
            if families:
                family = families[0]
        application.setFont(QFont(family, 11, QFont.Weight.Medium))
    except Exception:
        pass
    application.setApplicationDisplayName("echo acoustic analysis workstation")
    application.setOrganizationName("echo")
    engine = QQmlApplicationEngine()
    try:
        if FeatureBackendBridge is not None:
            bridge = FeatureBackendBridge(protocol_root=protocol_dir)
        else:
            bridge = create_bridge(protocol_root=protocol_dir)
    except BackendError as exc:
        raise RuntimeError(json.dumps({"error": exc.code, "detail": exc.to_dict()})) from exc
    images = PlotImageProvider()
    engine.addImageProvider("plots", images)
    theme = ThemeSource()
    try:
        app = AppViewModel(bridge, theme, images, engine)
    except Exception as exc:
        raise RuntimeError(json.dumps({
            "error": "APP_INIT_FAILED",
            "detail": f"{type(exc).__name__}: {exc}",
            "hint": "user data directory is not writable; set SIXMIC_USER_DATA_DIR",
        }, ensure_ascii=False)) from exc
    # Outlive the QML engine so context properties never read as null while the
    # scene graph is torn down (avoids harmless-but-noisy teardown warnings).
    theme.setParent(application)
    app.setParent(application)
    bridge.setParent(application)
    engine.rootContext().setContextProperty("backend", bridge)
    engine.rootContext().setContextProperty("App", app)
    engine.rootContext().setContextProperty("Theme", theme)
    engine.rootContext().setContextProperty("backendVersion", bridge.backendVersion)
    engine.rootContext().setContextProperty("uiRootUrl", QUrl.fromLocalFile(str(main_qml.parent)).toString())

    def reload_ui() -> None:
        window_state = {}
        for root in list(engine.rootObjects()):
            try:
                window_state = {"width": int(root.property("width") or 0),
                                "height": int(root.property("height") or 0),
                                "x": int(root.property("x") or 0),
                                "y": int(root.property("y") or 0)}
            except Exception:
                pass
        for root in list(engine.rootObjects()):
            try:
                root.setProperty("visible", False)
                root.deleteLater()
            except Exception:
                pass
        application.processEvents()
        try:
            from PySide6.QtCore import QCoreApplication, QEvent
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        except Exception:
            pass
        application.processEvents()
        engine.clearComponentCache()
        engine.load(QUrl.fromLocalFile(str(main_qml)))
        if engine.rootObjects() and window_state.get("width"):
            root = engine.rootObjects()[0]
            root.setProperty("width", window_state["width"])
            root.setProperty("height", window_state["height"])
    app.uiReloadRequested.connect(reload_ui)
    engine.load(QUrl.fromLocalFile(str(main_qml)))
    return application, engine, bridge, app, theme, images, main_qml


def _collect_qml_errors(engine) -> list[str]:
    messages: list[str] = []
    try:
        for error in engine.warnings() if hasattr(engine, "warnings") else []:
            messages.append(str(error.toString()))
    except Exception:
        pass
    for root in engine.rootObjects():
        try:
            if root.property("_loadErrors"):
                messages.extend([str(item) for item in root.property("_loadErrors")])
        except Exception:
            pass
    return messages


def run_gui(protocol_dir: str | None, qml_root: str | None, smoke_seconds: float = 0.0) -> int:
    try:
        application, engine, bridge, app, theme, images, main_qml = create_application(
            protocol_dir, qml_root)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 6
    if not engine.rootObjects():
        print(json.dumps({"error": "QML_LOAD_FAILED", "path": str(main_qml)}), file=sys.stderr)
        return 6
    if smoke_seconds and smoke_seconds > 0:
        from PySide6.QtCore import QTimer, QUrl
        from PySide6.QtQml import QQmlComponent
        # Root startup alone does not compile lazy analysis pages. A malformed
        # shared chart can otherwise pass packaging and break every measurement.
        initial_roots=bool(engine.rootObjects())
        page_paths=sorted((main_qml.parent / "pages").glob("*Page.qml"))
        errors = _collect_qml_errors(engine)
        for page_path in page_paths:
            component=QQmlComponent(engine,QUrl.fromLocalFile(str(page_path)))
            errors.extend(error.toString() for error in component.errors())
        QTimer.singleShot(int(smoke_seconds * 1000), application.quit)
        application.exec()
        bridge.shutdown()
        errors += _collect_qml_errors(engine)
        payload = {"qmlLoaded": initial_roots, "pageComponentCount": len(page_paths),
                   "smokeSeconds": smoke_seconds, "warnings": errors,
                   "page": app.currentPage, "appVersion": app.version}
        print("SMOKE_GUI_OK" if not errors else "SMOKE_GUI_WARNINGS")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if not errors else 6
    code = application.exec()
    bridge.shutdown()
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="SixMic3D",
                                     description="SixMic3D desktop application")
    parser.add_argument("--self-test", action="store_true", help="headless backend self-test")
    parser.add_argument("--protocol-dir", metavar="DIR")
    parser.add_argument("--qml-root", metavar="DIR", help="override QML root")
    parser.add_argument("--backend-status", action="store_true")
    parser.add_argument("--smoke-gui", type=float, metavar="SECONDS", default=0.0,
                        help="run the GUI offscreen for N seconds then exit (CI smoke)")
    args = parser.parse_args(argv)
    if args.self_test:
        return run_self_test(args.protocol_dir)
    if args.backend_status:
        return print_backend_status(args.protocol_dir)
    try:
        return run_gui(args.protocol_dir, args.qml_root, smoke_seconds=args.smoke_gui)
    except Exception as exc:  # noqa: BLE001 - last-resort guard for windowed builds
        import traceback
        detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        try:
            log = Path(tempfile.gettempdir()) / "echo-crash.log"
            log.write_text(detail, encoding="utf-8", errors="replace")
        except OSError:
            pass
        show_startup_error(
            "echo could not start.\n\n"
            f"{type(exc).__name__}: {exc}\n\n"
            "If this is a portable copy, make sure its folder is writable, or set "
            "SIXMIC_USER_DATA_DIR to a writable folder.")
        return 4


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001
        show_startup_error(f"echo could not start: {type(exc).__name__}: {exc}")
        raise SystemExit(4)
