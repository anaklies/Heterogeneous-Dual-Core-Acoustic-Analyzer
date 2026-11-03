"""Shared helpers for the SixMic3D PyInstaller specs.

Both specs import this module (packaging/tools is put on sys.path by the spec)
so path resolution, exclusion policy, protocol data and Qt checks are defined
in exactly one place.

Policy notes:
  * onedir only (COLLECT). No --onefile: faster start, simpler Qt plugin
    layout, and no self-extraction to %TEMP% on every launch.
  * the only bundled Qt is the one inside apps/sixmic-desktop/.venv
    (PySide6 wheel). No system Qt, no Qt5, no PyQt.
  * forbidden payloads never ship: torch/CUDA/training caches, MATLAB
    artifacts, Vivado projects, old PC prototype (pc/), keys, .venv itself.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path, PurePosixPath

PACKAGING_DIR = Path(__file__).resolve().parent.parent
APP_DIR = PACKAGING_DIR.parent
REPO_ROOT = APP_DIR.parent.parent
BACKEND_DIR = APP_DIR / "backend"
INTERFACES_DIR = REPO_ROOT / "interfaces" / "pc_backend_v1"
DIST_DIR = APP_DIR / "dist"
BUILD_DIR = APP_DIR / "build"

BACKEND_CHECK_ENTRY = BACKEND_DIR / "sixmic_backend" / "app" / "backend_check.py"
DESKTOP_ENTRY = APP_DIR / "main.py"

VERSION_FILE = PACKAGING_DIR / "VERSION"
VERSION_RESOURCE_BACKEND = PACKAGING_DIR / "pyi" / "version_backend_check.txt"
VERSION_RESOURCE_DESKTOP = PACKAGING_DIR / "pyi" / "version_desktop.txt"

# Hard exclusion policy. These must never appear in a product bundle:
# training/ML stacks, CUDA, plotting/test-only tooling and any other Qt binding.
EXCLUDES = [
    # ML / training junk (explicitly forbidden in the handoff brief)
    "torch",
    "torchvision",
    "torchaudio",
    "tensorflow",
    "keras",
    "jax",
    "jaxlib",
    "cupy",
    "cuda",
    "triton",
    "numba",
    "llvmlite",
    "matplotlib",
    "sklearn",
    "onnx",
    "onnxruntime",
    "IPython",
    "ipykernel",
    "jupyter",
    "notebook",
    # other Qt bindings: never mix Qt major versions / bindings
    "PyQt5",
    "PyQt6",
    "PySide2",
    "shiboken2",
    # legacy Tk / dev-only test tooling
    "tkinter",
    "_tkinter",
    "pytest",
    "_pytest",
    "pluggy",
    "pytest_cov",
]

QT_HIDDENIMPORTS = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtNetwork",
]


def read_version() -> str:
    return VERSION_FILE.read_text(encoding="utf-8").strip()


def protocol_datas(script_name: str) -> list[tuple[str, str]]:
    """Protocol data files for PyInstaller datas under _internal/protocol/.

    Missing hard-required protocol files abort the build unless the build
    script explicitly sets SIXMIC_ALLOW_MISSING_PROTOCOL_DATA=1 (used only to
    separate "PyInstaller mechanics" from "protocol deliverables are ready"
    while the backend is still landing; never for a release build).
    """
    sys.path.insert(0, str(PACKAGING_DIR / "tools"))
    import protocol_data  # noqa: PLC0415

    missing = protocol_data.find_missing_required(INTERFACES_DIR)
    if missing and os.environ.get("SIXMIC_ALLOW_MISSING_PROTOCOL_DATA") != "1":
        raise SystemExit(
            script_name + ": required protocol data missing under " + str(INTERFACES_DIR) + ": " + ", ".join(missing) +
            ". Build refused (set SIXMIC_ALLOW_MISSING_PROTOCOL_DATA=1 only for pipeline mechanics tests)."
        )
    if missing:
        print("WARNING: " + script_name + ": building WITHOUT required protocol data: " + ", ".join(missing))
    return protocol_data.collect_datas(INTERFACES_DIR)


def sixmic_backend_hiddenimports(include_qt: bool = True) -> list[str]:
    """Every sixmic_backend submodule (entry point is not statically visible).

    include_qt=False is used by the headless BackendCheck build: the console
    entry deliberately does not import sixmic_backend.qt (PySide6 is a lazy,
    soft dependency of the Qt adapter only - see qt/adapter.py). Excluding it
    keeps the diagnostic exe Qt-free and small; the desktop bundle is the one
    that carries the Qt Quick/QML runtime.
    """
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    try:
        from PyInstaller.utils.hooks import collect_submodules  # noqa: PLC0415

        modules = list(collect_submodules("sixmic_backend"))
    except Exception as exc:  # pragma: no cover - build environment issue
        print("WARNING: collect_submodules(sixmic_backend) failed: " + repr(exc))
        return []
    if include_qt:
        return modules
    return [
        name
        for name in modules
        if name != "sixmic_backend.qt" and not name.startswith("sixmic_backend.qt.")
    ]


def assert_qt6() -> tuple[str, str, str]:
    """Fail the build unless the env has PySide6 with a Qt 6 runtime.

    Returns (pyside6_version, qt_version, pyside6_package_dir).
    """
    try:
        import PySide6  # noqa: PLC0415
        from PySide6 import QtCore  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover
        raise SystemExit("PySide6 is not importable in the build venv: " + repr(exc))
    qt = str(QtCore.qVersion())
    if qt.split(".")[0] != "6":
        raise SystemExit("Refusing to package non-Qt6 runtime: QtCore.qVersion()=" + qt)
    pyside_dir = str(Path(PySide6.__file__).resolve().parent)
    ver = str(getattr(PySide6, "__version__", "unknown"))
    print("sixmic packaging: PySide6=" + ver + " Qt=" + qt + " from " + pyside_dir)
    return ver, qt, pyside_dir


def qt_layout(pyside6_dir: str | None = None) -> dict:
    """Resolve the real Qt runtime layout of the build venv's PySide6 wheel.

    PySide6 wheel layouts differ: newer wheels are "flat" (PySide6/Qt6Core.dll,
    PySide6/plugins, PySide6/qml) while older ones use PySide6/Qt/{bin,plugins,qml}.
    Assumptions are therefore derived from the live QLibraryInfo, never hardcoded.

    Returns a dict with absolute source directories plus the destination
    prefixes (relative to the frozen _internal/ directory) that mirror the
    wheel layout expected by the frozen PySide6 package.
    """
    if pyside6_dir is None:
        import PySide6  # noqa: PLC0415

        pyside6_dir = str(Path(PySide6.__file__).resolve().parent)
    from PySide6.QtCore import QLibraryInfo  # noqa: PLC0415

    package = Path(pyside6_dir).resolve()

    def _lib_path(name: str) -> Path:
        return Path(QLibraryInfo.path(getattr(QLibraryInfo.LibraryPath, name))).resolve()

    def _dest_for(path: Path, fallback: str) -> str:
        try:
            rel = path.relative_to(package)
        except ValueError:
            return fallback
        if not rel.parts:
            return "PySide6"
        return str(PurePosixPath("PySide6", *rel.parts))

    plugins = _lib_path("PluginsPath")
    qml = _lib_path("QmlImportsPath")
    dll_dirs: list[Path] = []
    for candidate in (package / "Qt" / "bin", package / "bin", _lib_path("BinariesPath"), package):
        if candidate.is_dir() and candidate not in dll_dirs:
            dll_dirs.append(candidate)
    return {
        "pyside6_dir": str(package),
        "prefix": str(_lib_path("PrefixPath")),
        "plugins": str(plugins),
        "plugins_dest_prefix": _dest_for(plugins, "PySide6/Qt/plugins"),
        "qml": str(qml),
        "qml_dest_prefix": _dest_for(qml, "PySide6/Qt/qml"),
        "libs": str(_lib_path("LibrariesPath")),
        "binaries": str(_lib_path("BinariesPath")),
        "qt_dll_dirs": [str(path) for path in dll_dirs],
    }


def ensure_plugin_datas(analysis, pyside6_dir: str, plugin_subdirs=("platforms", "imageformats", "qmltooling", "styles", "tls")) -> list[str]:
    """Guarantee Qt plugin folders are bundled even if a PyInstaller hook misses them.

    PyInstaller's PySide6 hooks normally collect platforms/imageformats/styles,
    but QML tooling plugins are easy to miss. We append only the files whose
    destination is not already present, to avoid duplicate TOC entries.

    Returns the list of plugin directories that were added explicitly.
    """
    layout = qt_layout(pyside6_dir)
    plugins_root = Path(layout["plugins"])
    dest_root = PurePosixPath(layout["plugins_dest_prefix"])
    # After Analysis.__init__, analysis.datas / analysis.binaries are TOC lists
    # of 3-tuples (dest_relative_path, source_path, typecode); new entries must
    # be added in that form (a 2-tuple here would crash COLLECT's normalize_toc).
    # Track destination FILE paths, not directories: several plugins can live in
    # one plugin directory (imageformats/qico.dll + imageformats/qsvg.dll) and
    # tracking directories would silently drop all but the first one.
    existing = set()
    for entry in list(getattr(analysis, "datas", [])) + list(getattr(analysis, "binaries", [])):
        try:
            if len(entry) >= 3:
                existing.add(PurePosixPath(str(entry[0]).replace("\\", "/")).as_posix())
            elif len(entry) == 2:
                dest = PurePosixPath(str(entry[1]).replace("\\", "/"))
                existing.add((dest / str(entry[0]).split("\\")[-1].split("/")[-1]).as_posix())
        except Exception:
            continue
    added: list[str] = []
    for subdir in plugin_subdirs:
        src_root = plugins_root / subdir
        if not src_root.is_dir():
            continue
        added_any = False
        for path in sorted(src_root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(plugins_root)
            dest_file = (dest_root.joinpath(*rel.parts)).as_posix()
            if dest_file in existing:
                continue
            analysis.datas.append((dest_file, str(path), "DATA"))
            existing.add(dest_file)
            added_any = True
        if added_any:
            added.append(subdir)
    return added
