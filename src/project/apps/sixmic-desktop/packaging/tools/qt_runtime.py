"""Resolve the minimal Qt 6 runtime DLL set for the SixMic3D GUI bundle.

Why this exists
---------------
PyInstaller's built-in hook-PySide6.QtQml.py collects *every* QML module in the
PySide6 wheel by default. That drags in QtWebEngine, QtQuick3D, Qt3D,
QtCharts, multimedia, etc. - explicitly forbidden by the frontend handoff brief
("only collect the Qt modules actually needed; do not stuff WebEngine, models,
toolchains or historical audio into the bundle").

The packaging override packaging/pyi/hook-PySide6.QtQml.py therefore skips that
whole-tree collection, and the spec ships only the QML modules the app's own
QML imports (tools/qt_qml.py). This module then computes the closure of Qt 6
DLLs required by those QML plugin DLLs plus the PySide6 Python modules the app
imports, by walking the PE import tables with PyInstaller's own bindepend
helper. The result is a small, explicit binaries list for Analysis.

Destinations mirror the wheel layout: on Windows the PySide6 6.12 wheel keeps
Qt6*.dll directly in PySide6/, so the frozen destination is "PySide6".

No third-party PE library is used beyond what PyInstaller already ships.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PACKAGING_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACKAGING_DIR / "tools"))

import pyi_common  # noqa: E402

# Qt 6 runtime DLLs pulled in by the PySide6 Python modules the launcher imports
# (main.py + ui/viewmodels/*): QtCore/Gui/Qml/Quick/QuickControls2/QuickLayouts/
# Svg/Widgets/PrintSupport/Network.
CORE_QT_DLL_SEEDS = (
    "Qt6Core.dll",
    "Qt6Gui.dll",
    "Qt6Qml.dll",
    "Qt6Quick.dll",
    "Qt6QuickControls2.dll",
    "Qt6QuickLayouts.dll",
    "Qt6Svg.dll",
    "Qt6Widgets.dll",
    "Qt6PrintSupport.dll",
    "Qt6Network.dll",
)

# Extra plugin DLLs (not part of the QML module tree) whose dependencies the
# application needs: image format plugins are collected by the QtGui hook.
IMAGE_FORMAT_PLUGIN_SEEDS = ("imageformats/qsvg.dll", "imageformats/qico.dll")


def _resolve_in_dirs(name: str, dirs: list[Path]) -> Path | None:
    lowered = name.lower()
    for directory in dirs:
        candidate = directory / name
        if candidate.is_file():
            return candidate
        try:
            for entry in directory.iterdir():
                if entry.is_file() and entry.name.lower() == lowered:
                    return entry
        except OSError:
            continue
    return None


def _dest_dir_for(src: Path, package: Path, layout: dict) -> str:
    """Destination directory (relative to frozen _internal/) mirroring the wheel."""
    package = package.resolve()
    try:
        parent_rel = src.resolve().parent.relative_to(package)
    except ValueError:
        return "PySide6"
    if not parent_rel.parts:
        return "PySide6"
    return str(Path("PySide6", *parent_rel.parts)).replace("\\", "/")


def collect_qt_runtime_binaries(
    pyside6_dir: str | None,
    qml_module_dirs: list[str] | None = None,
    extra_seed_paths: list[str] | None = None,
) -> tuple[list[tuple[str, str]], list[str], dict]:
    """Return (binaries, missing_qt_dlls, info) for Analysis(binaries=...).

    * qml_module_dirs: source QML module directories that will be shipped as
      datas; every *.dll plugin inside them seeds the dependency walk.
    * extra_seed_paths: extra DLLs to seed (e.g. imageformat plugins).
    """
    from PyInstaller.depend.bindepend import get_imports

    layout = pyi_common.qt_layout(pyside6_dir)
    package = Path(layout["pyside6_dir"])
    dll_dirs = [Path(p) for p in layout["qt_dll_dirs"]]
    search_paths = [str(p) for p in dll_dirs]

    seed_paths: list[Path] = []
    for name in CORE_QT_DLL_SEEDS:
        resolved = _resolve_in_dirs(name, dll_dirs)
        if resolved is not None:
            seed_paths.append(resolved)
    for path_text in extra_seed_paths or []:
        candidate = Path(path_text)
        if candidate.is_file():
            seed_paths.append(candidate)
    for module_dir in qml_module_dirs or []:
        root = Path(module_dir)
        if not root.is_dir():
            continue
        # Only plugin DLLs that belong to THIS module: sub-directories with a
        # qmldir are separate QML modules (e.g. every Controls style) that are
        # deliberately not shipped and must not leak runtime DLLs into the bundle.
        for entry in sorted(root.iterdir()):
            if entry.is_file() and entry.suffix.lower() == ".dll":
                seed_paths.append(entry)
            elif entry.is_dir():
                if (entry / "qmldir").is_file() or entry.name in QML_DESIGNER_ONLY_DIRS:
                    continue
                for path in sorted(entry.rglob("*.dll")):
                    seed_paths.append(path)

    seen_sources: set[Path] = set()
    binaries: list[tuple[str, str]] = []
    missing: set[str] = set()
    processed: set[Path] = set()
    queue: list[Path] = list(seed_paths)

    # The explicit seed DLLs must ship as well, not only their transitive
    # dependencies. QML plugin DLLs are already shipped as datas inside their
    # module directories, so only the core Qt seeds are added here.
    for seed in seed_paths:
        if not seed.is_file():
            continue
        if "qml" in seed.parts:
            continue  # QML plugin DLLs ship inside their module data tree
        resolved_seed = seed.resolve()
        if resolved_seed in seen_sources:
            continue
        seen_sources.add(resolved_seed)
        binaries.append((str(resolved_seed), _dest_dir_for(resolved_seed, package, layout)))
    while queue:
        current = queue.pop()
        try:
            current_resolved = current.resolve()
        except OSError:
            continue
        if current_resolved in processed:
            continue
        processed.add(current_resolved)
        try:
            imports = get_imports(str(current), search_paths=search_paths)
        except Exception:  # noqa: BLE001 - defensive for exotic binaries
            imports = set()
        for name, fullpath in imports:
            if not str(name).lower().startswith("qt6"):
                continue
            dep: Path | None = None
            if fullpath:
                dep = Path(fullpath)
            else:
                dep = _resolve_in_dirs(str(name), dll_dirs)
            if dep is None or not dep.is_file():
                missing.add(str(name))
                continue
            try:
                dep = dep.resolve()
            except OSError:
                continue
            if dep in seen_sources:
                continue
            seen_sources.add(dep)
            binaries.append((str(dep), _dest_dir_for(dep, package, layout)))
            queue.append(dep)

    binaries.sort()
    info = {
        "pyside6Dir": str(package),
        "layout": layout,
        "seedCount": len(seed_paths),
        "binaries": len(binaries),
        "missing": sorted(missing),
        "destinations": sorted({dest for _, dest in binaries}),
    }
    return binaries, sorted(missing), info


QML_DESIGNER_ONLY_DIRS = ("designer",)


def qml_plugin_seed_paths(qml_source_root: str, modules) -> tuple[list[str], list[str]]:
    """Return (module directories, plugin DLL paths) for the resolved modules.

    Only DLLs that belong to the requested modules are returned: a DLL in a
    sub-directory with its own qmldir is a *different* QML module (e.g. every
    QtQuick.Controls style) and must not seed the runtime DLL closure, exactly
    like qt_qml.collect_qml_datas() does not copy it.
    """
    root = Path(qml_source_root)
    module_dirs: list[str] = []
    plugin_paths: list[str] = []
    for module in modules:
        rel = str(module).replace(".", "/")
        directory = root / rel
        if not directory.is_dir():
            continue
        module_dirs.append(str(directory))
        for entry in sorted(directory.iterdir()):
            if entry.is_file() and entry.suffix.lower() == ".dll":
                plugin_paths.append(str(entry))
            elif entry.is_dir():
                if (entry / "qmldir").is_file() or entry.name in QML_DESIGNER_ONLY_DIRS:
                    continue
                for path in sorted(entry.rglob("*.dll")):
                    plugin_paths.append(str(path))
    return module_dirs, plugin_paths


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pyside6-dir", help="PySide6 package dir of the build venv")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    binaries, missing, info = collect_qt_runtime_binaries(args.pyside6_dir)
    payload = {"binaries": binaries, "missing": missing, **info}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("Qt runtime DLLs: " + str(len(binaries)) + " (" + ", ".join(Path(b[0]).name for b in binaries) + ")")
        if missing:
            print("MISSING Qt6 DLLs: " + ", ".join(missing))
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
