"""Qt Quick / QML collection helper for the SixMic3D PyInstaller specs.

Why this exists
---------------
PyInstaller collects Python-level Qt modules (PySide6.QtCore, QtQml, ...) but it
does not parse QML files, so QML import modules (QtQuick, QtQuick.Controls,
Qt.labs.platform, ...) and their plugin DLLs would be missing at runtime.

This module:
  1. scans the application's .qml/.js sources for QML import statements,
  2. resolves each module name to PySide6/Qt/qml/<module path>,
  3. adds implied dependency modules (for example Controls -> Templates),
  4. returns PyInstaller datas entries plus a verification report.

The result is deliberately data-only: it never imports Qt and never executes
QML. The real build verification is a separate offscreen QML probe
(packaging/tools/qt_qml_probe.py) documented in packaging/README.md.

No cross-Qt-major mixing: the QML root is always the one inside the installed
PySide6 wheel (PySide6/Qt/qml); nothing is collected from a system Qt.
"""
from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

QML_SUFFIXES = (".qml", ".mjs", ".js")
_SCAN_EXCLUDE_DIRS = ("__pycache__", ".git", ".venv", "build", "dist")

# QML line: import QtQuick 2.15 | import QtQuick.Controls 2.15 | import QtQml 2.15
_IMPORT_RE = re.compile(
    r"^\s*import\s+(?P<module>[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z0-9_.]+|[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s+(?P<version>[0-9]+(?:\.[0-9]+)?))?\s*$",
    re.MULTILINE,
)

# Modules always present for a Qt Quick/QML application. Missing ones are
# reported, not fatal (some Qt builds merge modules).
ALWAYS_INCLUDE = (
    "QtQml",
    "QtQuick",
)

# Known implied module dependencies (QML module -> extra modules to copy).
IMPLIED_MODULES = {
    # QtQuick.Controls is only the plugin/qmldir shell; the concrete style used by
    # main.py (QQuickStyle.setStyle("Basic")) and the shared impl/Templates
    # modules are separate QML modules and must be shipped explicitly.
    "QtQuick.Controls": (
        "QtQuick.Templates",
        "QtQml.Models",
        "QtQuick.Controls.impl",
        "QtQuick.Controls.Basic",
    ),
    "QtQuick.Controls.Basic": (
        "QtQuick.Controls",
        "QtQuick.Templates",
        "QtQuick.Controls.Basic.impl",
    ),
    "QtQuick.Controls.impl": ("QtQuick.Templates",),
    "QtQuick.Controls.Basic.impl": ("QtQuick.Controls.Basic",),
    "QtQuick.Dialogs": ("QtQuick.Templates", "QtQuick.Dialogs.quickimpl"),
    "QtQuick.Dialogs.quickimpl": ("QtQuick.Dialogs",),
    "QtQuick.Controls.Fusion": ("QtQuick.Controls", "QtQuick.Templates"),
    "QtQuick.Controls.Imagine": ("QtQuick.Controls", "QtQuick.Templates"),
    "QtQuick.Controls.Material": ("QtQuick.Controls", "QtQuick.Templates"),
    "QtQuick.Controls.Universal": ("QtQuick.Controls", "QtQuick.Templates"),
    "QtQuick.Controls.Windows": ("QtQuick.Controls", "QtQuick.Templates"),
    "QtQuick.Layouts": (),
    "QtQuick.Window": ("QtQuick",),
    "QtQuick.Shapes": ("QtQuick",),
    "Qt.labs.platform": ("QtQuick.Window", "QtQml.Models"),
}


def resolve_qml_root(pyside6_package_dir: str | Path) -> Path:
    """Return the qml module root of the installed PySide6 wheel."""
    root = Path(pyside6_package_dir) / "Qt" / "qml"
    if not root.is_dir():
        raise SystemExit(
            "Qt QML module root not found: " + str(root) +
            " - the installed PySide6 wheel does not look like a full Qt Quick runtime."
        )
    return root


def scan_qml_sources(source_dirs: list[Path]) -> dict[str, list[str]]:
    """Scan directories for .qml/.js files and return {module: [files]}.

    Relative file imports (import "components") do not name a module and are
    ignored here; those files ship with the application resource tree.
    """
    hits: dict[str, list[str]] = {}
    for base in source_dirs:
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.suffix.lower() not in QML_SUFFIXES or not path.is_file():
                continue
            if any(part in _SCAN_EXCLUDE_DIRS for part in path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for match in _IMPORT_RE.finditer(text):
                module = match.group("module")
                hits.setdefault(module, []).append(str(path))
    return hits


def closure_modules(modules) -> tuple[list[str], list[str]]:
    """Expand modules with implied dependencies.

    Returns (resolved_sorted, implied_added).
    """
    requested = {str(m) for m in modules}
    pending = list(requested)
    while pending:
        current = pending.pop()
        for extra in IMPLIED_MODULES.get(current, ()):
            if extra not in requested:
                requested.add(extra)
                pending.append(extra)
    implied = sorted(requested - {str(m) for m in modules})
    return sorted(requested), implied


DESIGNER_ONLY_DIRS = ("designer",)


def collect_qml_datas(
    qml_root: str | Path,
    modules,
    *,
    dest_prefix: str | None = None,
) -> tuple[list[tuple[str, str]], list[str], list[str]]:
    """Collect only the requested QML modules as PyInstaller datas.

    Returns (datas, missing_modules, copied_module_paths).

    For each requested module the files directly inside the module directory
    are collected (qmldir, qmltypes, plugin DLLs, qml sources). Sub-directories
    that contain their own qmldir are *separate* QML modules and are only
    collected when they are part of the resolved module closure (this keeps
    e.g. every QtQuick.Controls style out of the bundle). Sub-directories
    without qmldir are data (recursed), except designer-only metadata.

    dest_prefix defaults to "PySide6/qml", the on-disk location that matches
    the PySide6 6.12 wheel (QLibraryInfo.QmlImportsPath) and the frozen
    _internal/PySide6/qml layout; the spec passes the value resolved from
    QLibraryInfo so old/new wheel layouts both work.
    """
    root = Path(qml_root)
    prefix = dest_prefix or "PySide6/qml"
    datas: list[tuple[str, str]] = []
    missing: list[str] = []
    copied: list[str] = []

    def _add(path: Path, dest_dir: PurePosixPath) -> None:
        datas.append((str(path), dest_dir.as_posix()))

    for module in modules:
        rel = module.replace(".", "/")
        src = root / rel
        if not src.is_dir() or not (src / "qmldir").is_file():
            missing.append(module)
            continue
        copied.append(module)
        dest_dir = PurePosixPath(prefix, *rel.split("/"))
        for entry in sorted(src.iterdir()):
            if entry.is_file():
                _add(entry, dest_dir)
            elif entry.is_dir():
                if (entry / "qmldir").is_file():
                    continue  # separate QML module in the closure
                if entry.name in DESIGNER_ONLY_DIRS:
                    continue
                for path in sorted(entry.rglob("*")):
                    if path.is_file():
                        sub_rel = path.relative_to(src)
                        _add(path, dest_dir.joinpath(*sub_rel.parts[:-1]))
    return datas, missing, copied


def dat_files(
    source_dirs: list[Path],
    dest_prefixes: dict[str, str] | None = None,
    exclude_dir_names: tuple[str, ...] = ("_selftest", "tools"),
    exclude_suffixes: tuple[str, ...] = (".py", ".pyc"),
) -> list[tuple[str, str]]:
    """Copy whole application resource trees (ui/, assets/, themes/, rendering/).

    dest_prefixes maps absolute source dir -> destination prefix (defaults to
    the directory name, preserving the on-disk layout the launcher expects).

    exclude_dir_names drops development-only directories: the chart
    exploration sandbox (_selftest/) and developer tooling (ui/tools/). Those
    are not product resources; everything the runtime can reach through
    ui/qml/main.qml stays. exclude_suffixes drops Python sources: ui/ and
    themes/ modules are compiled into the PYZ archive, so shipping the .py
    files again as data would only leak source without being used.
    """
    prefixes = dest_prefixes or {}
    out: list[tuple[str, str]] = []
    for base in source_dirs:
        if not base.is_dir():
            continue
        prefix = prefixes.get(str(base), base.name)
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if any(part in _SCAN_EXCLUDE_DIRS for part in path.parts):
                continue
            if any(part in exclude_dir_names for part in path.relative_to(base).parts[:-1]):
                continue
            if path.suffix.lower() in exclude_suffixes:
                continue
            rel = path.relative_to(base)
            dest = PurePosixPath(prefix, *rel.parts[:-1])
            out.append((str(path), str(dest)))
    return out
