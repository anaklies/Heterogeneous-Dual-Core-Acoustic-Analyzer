"""Preflight checks for the echo Windows packaging pipeline.

Run with the build venv python from apps/sixmic-desktop:
  .venv/Scripts/python.exe packaging/tools/preflight.py --mode backend
  .venv/Scripts/python.exe packaging/tools/preflight.py --mode desktop
  .venv/Scripts/python.exe packaging/tools/preflight.py --mode installer
  .venv/Scripts/python.exe packaging/tools/preflight.py --mode all --json

No check is allowed to say "verified" for work it did not do: this script only
inspects the local environment and files. Real build/run evidence comes from
build_backend_check.ps1, build_installer.ps1 and smoke_test_installer.ps1.

Exit codes: 0 = no FAIL, 1 = at least one FAIL, 2 = bad arguments.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from importlib import metadata
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PACKAGING_DIR = TOOLS_DIR.parent
APP_DIR = PACKAGING_DIR.parent
REPO_ROOT = APP_DIR.parent.parent
BACKEND_DIR = APP_DIR / "backend"
BACKEND_CHECK_ENTRY = BACKEND_DIR / "sixmic_backend" / "app" / "backend_check.py"
MAIN_PY = APP_DIR / "main.py"
INTERFACES_DIR = REPO_ROOT / "interfaces" / "pc_backend_v1"
LOCK_FILE = PACKAGING_DIR / "requirements-lock.txt"
DIST_DIR = APP_DIR / "dist"
DESKTOP_BUNDLE = DIST_DIR / "echo"
BACKEND_BUNDLE = DIST_DIR / "SixMic3D-BackendCheck"

UI_DIRS = ("ui", "assets", "themes", "rendering")
EXPECTED_PACKAGES = ("PySide6", "PyInstaller", "pytest")
LICENSE_FILES = (
    "THIRD_PARTY_LICENSES.txt",
    "QT_PYSIDE6_NOTICE.txt",
    "PYTHON_LICENSE.txt",
    "SIXMIC_PROTOCOL_NOTICE.txt",
    "LICENSE-LGPL-3.0.txt",
    "LICENSE-GPL-3.0.txt",
)
SPEC_FILES = (
    "requirements-lock.txt",
    "sixmic_backend_check.spec",
    "sixmic_desktop.spec",
    "build_backend_check.ps1",
    "build_installer.ps1",
    "smoke_test_installer.ps1",
    "installer/echo.iss",
)

sys.path.insert(0, str(TOOLS_DIR))
import protocol_data  # noqa: E402
import qt_qml  # noqa: E402

RESULTS: list[dict] = []


def check(status: str, name: str, detail: str) -> None:
    RESULTS.append({"status": status, "name": name, "detail": detail})


def installed_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for dist in metadata.distributions():
        try:
            name = dist.metadata["Name"]
        except Exception:
            continue
        if not name:
            continue
        # Match Python/importlib's first distribution on sys.path. Replacing it
        # with a later duplicate reports the wrong pip/setuptools environment.
        out.setdefault(str(name).lower(), str(dist.version or ""))
    return out


def read_lock() -> dict[str, str]:
    pinned: dict[str, str] = {}
    for raw in LOCK_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-") or "==" not in line or ";" in line:
            continue
        name, version = line.split("==", 1)
        pinned[name.strip().lower()] = version.strip()
    return pinned


def qt_versions() -> tuple[str | None, str | None]:
    try:
        import PySide6  # noqa: PLC0415
        from PySide6 import QtCore  # noqa: PLC0415

        return str(PySide6.__version__), str(QtCore.qVersion())
    except Exception:
        pass
    try:
        return metadata.version("PySide6"), None
    except Exception:
        return None, None


def version_resources() -> dict[str, str]:
    detail: dict[str, str] = {}
    for name in ("version_backend_check.txt", "version_desktop.txt"):
        path = PACKAGING_DIR / "pyi" / name
        if not path.is_file():
            continue
        match = re.search(r"filevers=\((\d+), (\d+), (\d+), (\d+)\)", path.read_text(encoding="utf-8"))
        if match:
            detail[name] = ".".join(match.groups())
    return detail


def scan_qml_count() -> tuple[int, list[str], list[str]]:
    exclusions = {".venv", "build", "dist", "__pycache__", "packaging"}
    files: list[Path] = []
    for path in APP_DIR.rglob("*.qml"):
        if any(part in exclusions for part in path.parts):
            continue
        files.append(path)
    modules: dict[str, list[str]] = {}
    for path in files:
        try:
            modules.update(qt_qml.scan_qml_sources([path.parent]))
        except Exception:
            continue
    return len(files), sorted({p.parent.name for p in files}), sorted(modules)


def run_checks(mode: str, allow_missing_protocol_data: bool) -> dict:
    RESULTS.clear()

    # --- location sanity -------------------------------------------------
    check("PASS" if REPO_ROOT.is_dir() else "FAIL", "repo-root", str(REPO_ROOT))
    check("PASS" if APP_DIR.is_dir() else "FAIL", "app-dir", str(APP_DIR))
    if mode in ("backend", "desktop", "installer", "all"):
        check(
            "PASS" if BACKEND_DIR.is_dir() else "FAIL",
            "backend-package-dir",
            str(BACKEND_DIR),
        )
        check(
            "PASS" if BACKEND_CHECK_ENTRY.is_file() else "FAIL",
            "backend-check-entry",
            str(BACKEND_CHECK_ENTRY),
        )

    # --- python interpreter -------------------------------------------------
    py = sys.version_info
    check(
        "PASS" if (py.major, py.minor) == (3, 12) else "FAIL",
        "python-version",
        "{0}.{1}.{2} (expected 3.12.x, sys.executable={3})".format(py.major, py.minor, py.micro, sys.executable),
    )

    # --- dependency lock ----------------------------------------------------
    versions = {"python": "{0}.{1}.{2}".format(py.major, py.minor, py.micro)}
    pyside, qt = qt_versions()
    versions["pyside6"] = pyside or "not-installed"
    versions["qt"] = qt or "unknown"
    try:
        versions["pyinstaller"] = metadata.version("PyInstaller")
    except Exception:
        versions["pyinstaller"] = "not-installed"

    if not LOCK_FILE.is_file():
        check("FAIL", "requirements-lock", "missing " + str(LOCK_FILE) + " (run tools/gen_requirements_lock.py)")
    else:
        pinned = read_lock()
        inst = installed_map()
        mismatch: list[str] = []
        missing: list[str] = []
        for name, version in sorted(pinned.items()):
            actual = inst.get(name)
            if actual is None:
                missing.append(name + "==" + version)
            elif actual != version:
                mismatch.append(name + ": lock=" + version + " installed=" + actual)
        extra = [name + "==" + ver for name, ver in sorted(inst.items()) if name not in pinned and name not in ("pip",)]
        if missing or mismatch:
            detail = "missing=" + repr(missing) + " mismatch=" + repr(mismatch)
            check("FAIL", "dependency-lock-match", detail)
        else:
            check("PASS", "dependency-lock-match", str(len(pinned)) + " pinned packages match the installed venv")
        if extra:
            check("WARN", "dependency-lock-extras", "installed but not pinned: " + ", ".join(extra))
        else:
            check("PASS", "dependency-lock-extras", "no unpinned installed packages")
        for pkg in EXPECTED_PACKAGES:
            actual = inst.get(pkg.lower())
            check(
                "PASS" if actual else "FAIL",
                "package-" + pkg,
                actual or "not installed in " + str(Path(sys.executable)),
            )

    if mode in ("backend", "desktop", "installer", "all"):
        # Headless BackendCheck does not need Qt; the desktop/installer builds do.
        qt_required = mode in ("desktop", "installer", "all")
        if pyside:
            check("PASS", "pyside6", str(pyside))
        elif qt_required:
            check("FAIL", "pyside6", "not importable (required for desktop/installer bundle)")
        else:
            check("WARN", "pyside6", "not installed - acceptable for headless BackendCheck only")
        qt_ok = bool(qt) and str(qt).split(".")[0] == "6"
        if qt:
            check("PASS" if qt_ok else "FAIL", "qt-runtime", str(qt))
        elif qt_required:
            check("FAIL", "qt-runtime", "no Qt runtime (required for desktop/installer bundle)")
        else:
            check("WARN", "qt-runtime", "no Qt runtime - headless BackendCheck only")
        check(
            "PASS" if versions["pyinstaller"] != "not-installed" else "FAIL",
            "pyinstaller",
            str(versions["pyinstaller"]),
        )

    # --- protocol data ------------------------------------------------------
    if mode in ("backend", "desktop", "installer", "all"):
        missing_required = protocol_data.find_missing_required(INTERFACES_DIR)
        if missing_required:
            status = "WARN" if allow_missing_protocol_data else "FAIL"
            check(status, "protocol-data", "missing required files: " + ", ".join(missing_required))
        else:
            manifest = protocol_data.bundle_manifest(INTERFACES_DIR)
            check(
                "PASS",
                "protocol-data",
                "{0} files, {1} bytes, manifestSha256={2}".format(
                    manifest["fileCount"], manifest["totalBytes"], manifest["manifestSha256"]
                ),
            )

    # --- version metadata ---------------------------------------------------
    ver_file = PACKAGING_DIR / "VERSION"
    if ver_file.is_file():
        declared = ver_file.read_text(encoding="utf-8").strip()
        resources = version_resources()
        bad = [name + "!=" + ver for name, ver in resources.items() if not ver.startswith(declared)]
        check(
            "PASS" if not bad else "FAIL",
            "version-metadata",
            "VERSION=" + declared + " resources=" + json.dumps(resources) + ("" if not bad else " mismatched: " + repr(bad)),
        )

    # --- desktop entry / UI merge state ------------------------------------
    if mode in ("desktop", "all"):
        check("PASS" if MAIN_PY.is_file() else "FAIL", "main-py", str(MAIN_PY))
        present = [name for name in UI_DIRS if (APP_DIR / name).is_dir()]
        check(
            "PASS" if present else "WARN",
            "ui-dirs-present",
            ", ".join(present) if present else "no ui/assets/themes/rendering dirs yet (main agent owns them)",
        )
        qml_count, dirs, modules = scan_qml_count()
        if qml_count:
            check("PASS", "qml-sources", str(qml_count) + " .qml file(s) in " + ", ".join(dirs) + "; imports=" + repr(modules))
        else:
            check("FAIL", "qml-sources", "no .qml sources found - UI not merged, an honest desktop bundle cannot be built")
    else:
        modules = []

    # --- installer inputs ---------------------------------------------------
    if mode in ("installer", "all"):
        for label, exe in (
            ("desktop-bundle", DESKTOP_BUNDLE / "echo.exe"),
            ("backendcheck-bundle", BACKEND_BUNDLE / "SixMic3D-BackendCheck.exe"),
        ):
            check("PASS" if exe.is_file() else "FAIL", label, str(exe))
        if DESKTOP_BUNDLE.is_dir():
            check("PASS", "desktop-bundle-contents", str(sum(1 for _ in DESKTOP_BUNDLE.rglob("*")) ) + " files in bundle")
        lic_dir = PACKAGING_DIR / "licenses"
        missing_lic = [name for name in LICENSE_FILES if not (lic_dir / name).is_file()]
        check(
            "PASS" if not missing_lic else "FAIL",
            "license-files",
            "all present in packaging/licenses" if not missing_lic else "missing: " + ", ".join(missing_lic),
        )

    # --- packaging assets presence -----------------------------------------
    if mode in ("desktop", "installer", "all"):
        missing_assets = [name for name in SPEC_FILES if not (PACKAGING_DIR / name).is_file()]
        check(
            "PASS" if not missing_assets else "FAIL",
            "packaging-assets",
            "all pipeline files present" if not missing_assets else "missing: " + ", ".join(missing_assets),
        )

    ok = not any(item["status"] == "FAIL" for item in RESULTS)
    return {
        "mode": mode,
        "ok": ok,
        "generatedAtLocal": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "paths": {
            "repoRoot": str(REPO_ROOT),
            "appDir": str(APP_DIR),
            "venvPython": str(Path(sys.executable)),
            "backendCheckEntry": str(BACKEND_CHECK_ENTRY),
            "mainPy": str(MAIN_PY),
            "interfaces": str(INTERFACES_DIR),
        },
        "versions": versions,
        "qmlModules": modules,
        "checks": RESULTS,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=("backend", "desktop", "installer", "all"), default="backend")
    parser.add_argument("--json", action="store_true", help="emit only a JSON summary")
    parser.add_argument("--allow-missing-protocol-data", action="store_true")
    parser.add_argument("--report", help="also write JSON summary to this path")
    args = parser.parse_args(argv)

    summary = run_checks(args.mode, args.allow_missing_protocol_data)
    if args.report:
        Path(args.report).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print("echo packaging preflight - mode=" + args.mode)
        print("repo: " + summary["paths"]["repoRoot"])
        print("python: " + summary["paths"]["venvPython"])
        for item in summary["checks"]:
            print("[{0:4}] {1}: {2}".format(item["status"], item["name"], item["detail"]))
        print()
        print("RESULT: " + ("PASS" if summary["ok"] else "FAIL") + " (" + str(len(summary["checks"])) + " checks)")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
