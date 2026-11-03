# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir spec: SixMic3D-BackendCheck.exe (console diagnostic build).

Build (always through the wrapper so protocol data, hashes and the scrubbed-PATH
self-test are recorded):
  powershell -ExecutionPolicy Bypass -File apps/sixmic-desktop/packaging/build_backend_check.ps1

What ships in this bundle:
  * sixmic_backend package + its PySide6 runtime imports (probed by Analysis)
  * interfaces/pc_backend_v1 protocol data as _internal/protocol/ (datas) and,
    added afterwards by the wrapper, as <dist>/protocol/ next to the exe
  * no GUI assets, no UI resources, no training/ML payloads

The exe is a diagnostic console entry (--self-test), not a product GUI. No
final SixMic3D GUI acceptance is claimed from this artifact.
"""

import sys
from pathlib import Path

try:
    SPEC_DIR = Path(SPECPATH).resolve()
except NameError:  # pragma: no cover - defensive
    SPEC_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(SPEC_DIR / "tools"))
sys.path.insert(0, str(SPEC_DIR.parent / "backend"))

import pyi_common  # noqa: E402

VERSION = pyi_common.read_version()
BACKEND_ENTRY = pyi_common.BACKEND_CHECK_ENTRY
if not BACKEND_ENTRY.is_file():
    raise SystemExit("sixmic_backend_check.spec: backend entry missing: " + str(BACKEND_ENTRY))
# PyInstaller runs "scripts" as top-level __main__, but backend_check.py uses
# package-relative imports. Use the packaging-owned wrapper that imports the
# module inside its package and calls main(). Backend code is not modified.
ENTRY = SPEC_DIR / "pyi" / "backend_check_entry.py"
if not ENTRY.is_file():
    raise SystemExit("sixmic_backend_check.spec: entry wrapper missing: " + str(ENTRY))

datas = pyi_common.protocol_datas("sixmic_backend_check.spec")
# Headless by design: backend_check.py does not import sixmic_backend.qt and
# PySide6 is only a lazy soft dependency of the Qt adapter, so the diagnostic
# console exe carries no Qt runtime. Qt Quick/QML deployment is exclusively in
# sixmic_desktop.spec (the product GUI bundle).
hiddenimports = pyi_common.sixmic_backend_hiddenimports(include_qt=False)
print("sixmic_backend_check.spec: version=" + VERSION + " datas=" + str(len(datas)) + " hiddenimports=" + str(len(hiddenimports)))

a = Analysis(
    scripts=[str(ENTRY)],
    pathex=[str(pyi_common.BACKEND_DIR), str(pyi_common.APP_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=pyi_common.EXCLUDES,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SixMic3D-BackendCheck",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(pyi_common.VERSION_RESOURCE_BACKEND),
    contents_directory="_internal",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SixMic3D-BackendCheck",
)
