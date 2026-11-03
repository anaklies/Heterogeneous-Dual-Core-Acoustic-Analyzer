# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir spec: echo.exe (windowed Qt Quick/QML product build).

Build (always through the wrapper so Qt plugin/config checks and evidence are
recorded):
  powershell -ExecutionPolicy Bypass -File apps/sixmic-desktop/packaging/build_desktop.ps1

This spec intentionally refuses to build while the GUI is not merged: the
main-agent UI (ui/, assets/, themes/, rendering/ + main.py) is required, and a
bundle without real QML sources would be a fake product build.

Qt deployment rules enforced here:
  * the only Qt bundled is the Qt 6 shipped inside the build venv's PySide6
    wheel (pyi_common.assert_qt6 refuses anything else);
  * QML import modules are discovered from the application's own .qml sources
    (PyInstaller does not parse QML) and only that resolved closure is copied,
    under the wheel's real QML destination (PySide6/qml in PySide6 6.12);
  * PyInstaller's built-in "collect every QML module" hook is overridden by
    packaging/pyi/hook-PySide6.QtQml.py so WebEngine/Qt3D/Quick3D/Charts/
    multimedia never enter the bundle; the required Qt 6 runtime DLL closure is
    resolved explicitly by tools/qt_runtime.py from the PE import tables;
  * platforms/imageformats/styles/qmltooling plugins are verified in Analysis
    and appended only if a PyInstaller hook did not collect them.

The GUI is owned by the main agent; this spec only packages it. Packaging must
never become a place where UI code is written.
"""

import sys
from pathlib import Path

try:
    SPEC_DIR = Path(SPECPATH).resolve()
except NameError:  # pragma: no cover - defensive
    SPEC_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(SPEC_DIR / "tools"))
sys.path.insert(0, str(SPEC_DIR.parent / "backend"))
sys.path.insert(0, str(SPEC_DIR.parent))

import pyi_common  # noqa: E402
import qt_qml  # noqa: E402
import qt_runtime  # noqa: E402

VERSION = pyi_common.read_version()
ENTRY = pyi_common.DESKTOP_ENTRY
if not ENTRY.is_file():
    raise SystemExit("sixmic_desktop.spec: launcher missing (main agent/lead owns it): " + str(ENTRY))

APP_DIR = pyi_common.APP_DIR
UI_DIRS = ("ui", "assets", "themes", "rendering")
existing_ui_dirs = [APP_DIR / name for name in UI_DIRS if (APP_DIR / name).is_dir()]
if not existing_ui_dirs:
    raise SystemExit(
        "sixmic_desktop.spec: none of ui/, assets/, themes/, rendering/ exist under " + str(APP_DIR) +
        ". The main-agent UI is not merged yet; refusing to build a fake echo GUI bundle."
    )

# --- Qt/QML runtime discovery -------------------------------------------
pyside_version, qt_version, pyside_dir = pyi_common.assert_qt6()
# Real wheel layout (QLibraryInfo): new PySide6 wheels keep Qt6*.dll in
# PySide6/, plugins in PySide6/plugins and QML in PySide6/qml; old wheels use
# PySide6/Qt/{bin,plugins,qml}. Never hardcode the layout.
qt_layout = pyi_common.qt_layout(pyside_dir)
qml_root = Path(qt_layout["qml"])
print("sixmic_desktop.spec: Qt layout qml=" + str(qml_root) + " destPrefix=" + str(qt_layout["qml_dest_prefix"]))

qml_source_dirs = [d for d in (APP_DIR / "ui", APP_DIR / "rendering") if d.is_dir()]
imports = qt_qml.scan_qml_sources(qml_source_dirs)
if not imports:
    raise SystemExit(
        "sixmic_desktop.spec: no QML import statements found under " + ", ".join(str(d) for d in qml_source_dirs) +
        ". UI sources are not merged yet; refusing to build."
    )
modules, implied = qt_qml.closure_modules(set(imports) | set(qt_qml.ALWAYS_INCLUDE))
qml_datas, missing_qml, copied_modules = qt_qml.collect_qml_datas(
    qml_root, modules, dest_prefix=qt_layout["qml_dest_prefix"]
)
if "QtQuick" in missing_qml or "QtQml" in missing_qml:
    raise SystemExit("sixmic_desktop.spec: base QML modules missing from PySide6 wheel: " + repr(missing_qml))
print(
    "sixmic_desktop.spec: Qt=" + qt_version + " QML modules copied=" + str(len(copied_modules)) +
    " implied=" + repr(implied) + " missing=" + repr(missing_qml)
)

# --- selective Qt 6 runtime DLL closure ----------------------------------
# Seeds: the Qt DLLs of the PySide6 Python modules the app imports, the QML
# plugin DLLs of exactly the resolved QML modules, and the image-format plugins
# (SVG icons are rendered through Qt's SVG image plugin).
qml_module_dirs_for_runtime = [str(qml_root / module.replace(".", "/")) for module in modules]
image_plugin_dir = Path(qt_layout["plugins"]) / "imageformats"
image_plugin_seeds = [
    str(image_plugin_dir / name) for name in ("qsvg.dll", "qico.dll") if (image_plugin_dir / name).is_file()
]
runtime_binaries, missing_runtime_qt, runtime_info = qt_runtime.collect_qt_runtime_binaries(
    pyside_dir, qml_module_dirs_for_runtime, image_plugin_seeds
)
if missing_runtime_qt:
    raise SystemExit(
        "sixmic_desktop.spec: unresolved Qt 6 runtime DLL dependencies: " + repr(missing_runtime_qt) +
        " - the PySide6 wheel is incomplete or the Qt layout is unexpected."
    )
print(
    "sixmic_desktop.spec: Qt runtime binaries=" + str(len(runtime_binaries)) +
    " seeds=" + str(runtime_info["seedCount"]) + " destinations=" + repr(runtime_info["destinations"])
)

# A product build must contain the real launcher QML, not just any .qml file.
MAIN_QML = APP_DIR / "ui" / "qml" / "main.qml"
if not MAIN_QML.is_file():
    raise SystemExit(
        "sixmic_desktop.spec: ui/qml/main.qml is missing under " + str(APP_DIR) +
        ". The product launcher is not merged; refusing to build a GUI bundle without it."
    )

# --- application resources (owned by the main agent; copied, never edited) ---
# dat_files() drops development-only trees such as ui/.../charts/_selftest/
# (QML exploration scripts, screenshots, bundled fonts) - never product data.
app_datas = qt_qml.dat_files(existing_ui_dirs,
                               # dev-only: chart gallery demo rasters are not
                               # referenced by the product FeatureChart routes.
                               exclude_dir_names=("_selftest", "tools", "demo"))

# --- protocol data (same shared policy as the backend check build) ---
protocol_datas = pyi_common.protocol_datas("sixmic_desktop.spec")

hiddenimports = list(pyi_common.QT_HIDDENIMPORTS)
hiddenimports += pyi_common.sixmic_backend_hiddenimports()
import importlib.util  # noqa: E402

for optional in (
    "PySide6.QtQuickControls2",   # QML QtQuick.Controls backing module
    "PySide6.QtQuickLayouts",     # QtQuick.Layouts used by main.qml
    "PySide6.QtSvg",              # Icon.qml renders themed SVG files through Image
    "PySide6.QtPrintSupport",     # AppViewModel imports QPrinter for report export
    "PySide6.QtWidgets",          # QtPrintSupport dependency
):
    if importlib.util.find_spec(optional) is not None:
        hiddenimports.append(optional)


def _app_namespace_hiddenimports() -> list[str]:
    """Collect the main agent's ui/, themes/, rendering/ Python modules.

    ui/ and themes/ are namespace packages (no __init__.py), and PyInstaller's
    collect_submodules() does not walk them, so enumerate the .py files
    explicitly. _selftest/ and __pycache__ are development-only.
    """
    modules: set[str] = set()
    for package in ("ui", "themes", "rendering"):
        root = APP_DIR / package
        if not root.is_dir():
            continue
        modules.add(package)
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(root)
            if "__pycache__" in rel.parts or "_selftest" in rel.parts:
                continue
            parts = list(rel.with_suffix("").parts)
            if parts and parts[-1] == "__init__":
                parts = parts[:-1]
            if not parts:
                continue
            modules.add(".".join([package] + parts))
            for depth in range(1, len(parts)):
                modules.add(".".join([package] + parts[:depth]))
    return sorted(modules)


app_hiddenimports = _app_namespace_hiddenimports()
hiddenimports += app_hiddenimports
print("sixmic_desktop.spec: application python modules collected=" + str(len(app_hiddenimports)))

datas = app_datas + qml_datas + protocol_datas

# Product icon: the main agent ships assets/branding/sixmic3d.ico; the older
# assets/icon.ico name is accepted as a fallback. No icon is fabricated.
icon_candidates = (
    APP_DIR / "assets" / "branding" / "sixmic3d.ico",
    APP_DIR / "assets" / "icon.ico",
)
icon_path = next((candidate for candidate in icon_candidates if candidate.is_file()), None)
icon = str(icon_path) if icon_path else None
print("sixmic_desktop.spec: exe icon=" + (str(icon_path) if icon_path else "<none: no assets/branding/sixmic3d.ico>"))

runtime_hooks = []
# packaging-owned runtime hooks only (never UI code):
#   rth_gui_log.py - opt-in stdout/Qt-message capture used by the scrubbed-PATH
#                    GUI smoke tests (windowed bundle has no console). No effect
#                    unless SIXMIC_PACKAGING_GUI_LOG is set.
for _rth_name in ("rth_sixmic_paths.py", "rth_gui_log.py"):
    _rth = SPEC_DIR / "pyi" / _rth_name
    if _rth.is_file():
        runtime_hooks.append(str(_rth))
        print("sixmic_desktop.spec: runtime hook=" + str(_rth))

a = Analysis(
    scripts=[str(ENTRY)],
    pathex=[str(pyi_common.BACKEND_DIR), str(APP_DIR), str(SPEC_DIR.parent)],
    binaries=runtime_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # packaging/pyi/hook-PySide6.QtQml.py overrides PyInstaller's built-in hook
    # (custom hook directories take precedence) so the whole QML tree is not
    # collected. See tools/qt_qml.py + tools/qt_runtime.py for the selective set.
    hookspath=[str(SPEC_DIR / "pyi")],
    hooksconfig={},
    runtime_hooks=runtime_hooks,
    excludes=pyi_common.EXCLUDES,
    noarchive=False,
)

# Qt6 on supported Windows 10/11 uses the OS ICU API (unversioned exports).
# A PATH-installed ICU 78 has version-suffixed symbols and shadows that API,
# causing ERROR_PROC_NOT_FOUND even though all Qt DLL hashes are correct.
# Keep Windows-owned ICU in System32, as the working source runtime does.
_os_icu = {"icuuc.dll", "icuin.dll", "icudt.dll"}
a.binaries = [entry for entry in a.binaries
              if Path(entry[0]).name.lower() not in _os_icu
              and not (Path(entry[0]).name.lower().startswith("icudt")
                       and Path(entry[0]).name.lower().endswith(".dll"))]

added_plugins = pyi_common.ensure_plugin_datas(a, pyside_dir)
print("sixmic_desktop.spec: explicit Qt plugin dirs added=" + repr(added_plugins))

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="echo",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(pyi_common.VERSION_RESOURCE_DESKTOP),
    icon=icon,
    contents_directory="_internal",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="echo",
)
