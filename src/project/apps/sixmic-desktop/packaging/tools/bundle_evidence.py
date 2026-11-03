"""Inspect a PyInstaller onedir bundle and emit machine-checkable evidence.

Used by build_backend_check.ps1 / build_desktop.ps1 / smoke_test_installer.ps1.

Checks:
  * expected exe exists (name configurable per profile);
  * every file hashed -> bundle inventory sha256 (for the build log);
  * forbidden payloads absent (torch/CUDA/training caches, pc/ prototype, keys,
    .venv, Vivado projects, __pycache__);
  * Qt runtime provenance: every bundled Qt6 DLL / platform plugin must be
    byte-identical to the file inside the build venv's PySide6 wheel, and no
    Qt5/PyQt DLL may be present (no cross-Qt-major mixing);
  * protocol data present both in _internal/protocol/ and next to the exe.

Exit codes: 0 all required checks pass, 1 check failed, 2 bad arguments.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

FORBIDDEN_SEGMENTS = (
    ".venv",
    "torch",
    "torchvision",
    "torchaudio",
    "cuda",
    "cudnn",
    "tensorflow",
    "training",
    "train_cnn",
    "matplotlib",
    "vivado",
    ".xil",
    ".git",
    "__pycache__",
    "experiments",
    "pc",
    "pip-install-",
    "pip-ephem-wheel-cache",
    "pytest-cache-files",
)
FORBIDDEN_SUFFIXES = (".key", ".pem", ".p12", ".pfx", ".csr")
FORBIDDEN_NAME_HINTS = ("private-key", "secret")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory(bundle: Path) -> tuple[list[dict], int]:
    files: list[dict] = []
    for path in sorted(p for p in bundle.rglob("*") if p.is_file()):
        rel = path.relative_to(bundle).as_posix()
        files.append({"path": rel, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return files, sum(int(item["bytes"]) for item in files)


def check_forbidden(files: list[dict]) -> list[str]:
    violations: list[str] = []
    for item in files:
        rel = str(item["path"])
        parts = [part.lower() for part in rel.split("/")]
        name = parts[-1]
        if any(segment in FORBIDDEN_SEGMENTS for segment in parts[:-1]):
            violations.append("forbidden directory segment in bundle: " + rel)
        if name.endswith(FORBIDDEN_SUFFIXES):
            violations.append("forbidden credential-like file: " + rel)
        if any(hint in name for hint in FORBIDDEN_NAME_HINTS):
            violations.append("suspicious file name: " + rel)
    return violations


def _qt_source_dirs(pyside6_dir: Path) -> list[Path]:
    """Directories of the wheel that may contain Qt6*.dll, most specific first."""
    candidates = [
        pyside6_dir / "Qt" / "bin",  # older PySide6 wheel layout
        pyside6_dir / "bin",
        pyside6_dir,                 # PySide6 6.12 flat layout (Windows)
    ]
    return [path for path in candidates if path.is_dir()]


def _plugin_source_candidates(pyside6_dir: Path, subdir: str, name: str) -> list[Path]:
    return [
        pyside6_dir / "Qt" / "plugins" / subdir / name,  # older layout
        pyside6_dir / "plugins" / subdir / name,          # flat layout
    ]


def find_qt_mismatches(bundle: Path, pyside6_dir: Path | None) -> tuple[list[str], list[str], int]:
    """Return (violations, warnings, qt_dll_count)."""
    violations: list[str] = []
    warnings: list[str] = []
    qt_files = [p for p in bundle.rglob("*") if p.is_file() and p.name.lower().startswith("qt6")]
    qt_files = [p for p in qt_files if p.suffix.lower() == ".dll"]
    source_dirs = _qt_source_dirs(pyside6_dir) if pyside6_dir else []
    for path in qt_files:
        name = path.name
        # no cross-major / foreign binding DLLs anywhere
        if name.lower().startswith("qt5"):
            violations.append("Qt5 DLL in bundle (cross-major mixing): " + name)
            continue
        if not source_dirs:
            continue
        expected = next((directory / name for directory in source_dirs if (directory / name).is_file()), None)
        if expected is None:
            warnings.append("Qt6 DLL with no counterpart in the PySide6 wheel: " + name)
            continue
        if sha256_file(path) != sha256_file(expected):
            violations.append("Qt6 DLL differs from build venv PySide6 copy: " + name)
    # platform plugin provenance
    for path in bundle.rglob("qwindows.dll"):
        if pyside6_dir is None:
            warnings.append("platform plugin present but no PySide6 dir to compare: " + str(path))
            continue
        candidates = _plugin_source_candidates(pyside6_dir, "platforms", "qwindows.dll")
        expected = next((candidate for candidate in candidates if candidate.is_file()), None)
        if expected is None:
            warnings.append("qwindows.dll not found in PySide6 wheel to compare")
        elif sha256_file(path) != sha256_file(expected):
            violations.append("platforms/qwindows.dll differs from PySide6 wheel")
    return violations, warnings, len(qt_files)


def protocol_count(root: Path) -> int:
    if not root.is_dir():
        return 0
    return sum(1 for _ in root.rglob("*") if _.is_file())


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bundle", required=True, help="dist/<bundle name> directory")
    parser.add_argument("--exe-name", required=True, help="expected exe file name inside the bundle root")
    parser.add_argument("--profile", choices=("backend", "desktop"), required=True)
    parser.add_argument("--pyside6-dir", help="PySide6 package dir of the build venv (Qt provenance check)")
    parser.add_argument("--report", help="write JSON evidence here")
    args = parser.parse_args(argv)

    bundle = Path(args.bundle).resolve()
    if not bundle.is_dir():
        print("FAIL: bundle directory not found: " + str(bundle), file=sys.stderr)
        return 2
    pyside6_dir = Path(args.pyside6_dir).resolve() if args.pyside6_dir else None

    violations: list[str] = []
    warnings: list[str] = []
    exe = bundle / args.exe_name
    if not exe.is_file():
        violations.append("missing exe: " + str(exe))

    files, total_bytes = inventory(bundle)
    violations += check_forbidden(files)
    qt_violations, qt_warnings, qt_dll_count = find_qt_mismatches(bundle, pyside6_dir)
    violations += qt_violations
    warnings += qt_warnings

    internal_protocol = bundle / "_internal" / "protocol"
    adjacent_protocol = bundle / "protocol"
    protocol_checks = {
        "_internalProtcolFiles": protocol_count(internal_protocol),
        "adjacentProtocolFiles": protocol_count(adjacent_protocol),
    }
    if protocol_checks["_internalProtcolFiles"] == 0:
        warnings.append("_internal/protocol/ is empty or missing (PyInstaller datas not collected)")
    if protocol_checks["adjacentProtocolFiles"] == 0:
        violations.append("protocol/ missing next to exe (build wrapper must copy it)")
    for required in ("PROTOCOL.md", "errors/ERROR_CATALOG.json", "golden/GOLDEN_MANIFEST.json",
                     "features/FEATURE_CATALOG.json", "schema/control.schema.json"):
        if not (adjacent_protocol / required).is_file():
            violations.append("adjacent protocol/ missing required file: " + required)

    if args.profile == "desktop":
        has_platform = any(p.name.lower() == "qwindows.dll" for p in bundle.rglob("*"))
        if not has_platform:
            violations.append("desktop bundle missing platforms/qwindows.dll")
        # QML destination depends on the PySide6 wheel layout (flat 6.x vs
        # PySide6/Qt/... in some wheels); accept either but require the modules
        # the launcher's QML actually imports.
        qml_candidates = [
            bundle / "_internal" / "PySide6" / "qml",
            bundle / "_internal" / "PySide6" / "Qt" / "qml",
        ]
        internal_qml = next((candidate for candidate in qml_candidates if candidate.is_dir()), None)
        qml_files = sum(1 for _ in internal_qml.rglob("*") if _.is_file()) if internal_qml else 0
        protocol_checks["qmlModuleFiles"] = qml_files
        protocol_checks["qmlRoot"] = str(internal_qml) if internal_qml else None
        if qml_files == 0:
            violations.append("desktop bundle missing QML modules under _internal/PySide6/qml")
        if internal_qml is not None:
            required_modules = (
                "QtQuick",
                "QtQuick/Controls",
                "QtQuick/Controls/Basic",
                "QtQuick/Layouts",
                "QtQuick/Window",
                # Redesign (2026-10-26) removed the in-QML file dialogs; the app
                # opens files through QtWidgets QFileDialog from Python, so
                # QtQuick.Dialogs is intentionally NOT a required QML module.
                "QtQml",
                "QtQml/Models",
            )
            present_modules = sorted(
                module for module in required_modules if (internal_qml / module / "qmldir").is_file()
            )
            protocol_checks["qmlRequiredModulesPresent"] = present_modules
            missing_modules = [module for module in required_modules if module not in present_modules]
            if missing_modules:
                violations.append("desktop bundle missing required QML modules: " + ", ".join(missing_modules))
            # Selective-collection policy: the big Qt QML trees the handoff brief
            # forbids must not be present (they also pull 100+ MB of Qt DLLs).
            forbidden_qml = (
                "QtWebEngine",
                "QtQuick3D",
                "Qt3D",
                "QtCharts",
                "QtDataVisualization",
                "QtGraphs",
                "QtMultimedia",
                "QtLocation",
                "QtPositioning",
                "QtSensors",
                "QtTextToSpeech",
                "QtVirtualKeyboard",
                "QtPdf",
                "QtQuick3D",
                "QtQuick/Shapes",
                "QtQuick/Particles",
                "QtQuick/Timeline",
                "QtQuick/VectorImage",
                "QtQuick/Pdf",
                "QtQuick/VirtualKeyboard",
                "QtQuick/Scene3D",
            )
            present_forbidden = sorted(module for module in forbidden_qml if (internal_qml / module).exists())
            protocol_checks["qmlForbiddenModulesPresent"] = present_forbidden
            for module in present_forbidden:
                violations.append("desktop bundle contains forbidden Qt QML module tree: " + module)
            protocol_checks["qmlModuleDirs"] = sorted(
                str(path.relative_to(internal_qml).as_posix()) for path in internal_qml.iterdir() if path.is_dir()
            )
    if qt_dll_count == 0:
        if args.profile == "desktop":
            violations.append("desktop bundle contains no Qt6 DLLs")
        else:
            warnings.append("backend bundle contains no Qt6 DLLs (console-only backend is acceptable)")

    canonical = "\n".join(str(item["sha256"]) + "  " + str(item["path"]) for item in files)
    report = {
        "bundle": str(bundle),
        "profile": args.profile,
        "exe": str(exe),
        "exeBytes": exe.stat().st_size if exe.is_file() else 0,
        "exeSha256": sha256_file(exe) if exe.is_file() else None,
        "fileCount": len(files),
        "totalBytes": total_bytes,
        "inventorySha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "qtDllCount": qt_dll_count,
        "protocol": protocol_checks,
        "violations": violations,
        "warnings": warnings,
        "files": files,
    }
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print("report: " + str(report_path))
    for warning in warnings:
        print("WARN: " + warning)
    for violation in violations:
        print("FAIL: " + violation, file=sys.stderr)
    print(
        "BUNDLE " + args.profile + ": files=" + str(report["fileCount"]) + " bytes=" + str(report["totalBytes"]) +
        " exeSha256=" + str(report["exeSha256"]) + " inventorySha256=" + str(report["inventorySha256"]) +
        " qtDlls=" + str(qt_dll_count) + " violations=" + str(len(violations))
    )
    return 0 if not violations else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
