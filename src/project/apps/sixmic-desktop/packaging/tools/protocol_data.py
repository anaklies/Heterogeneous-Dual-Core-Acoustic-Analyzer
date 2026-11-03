"""Single source of truth for protocol data shipped beside the SixMic3D executables.

Both PyInstaller specs (via collect_protocol_datas) and build/preflight scripts
use this module so the shipped-file list cannot drift between them.

Shipping policy (updated 2026-10-24 with Lead):
  The frozen interfaces/pc_backend_v1 contract bundle is shipped WHOLE - all
  35 regular files - into <bundle>/protocol/ next to the exe, and also embedded
  through PyInstaller datas as _internal/protocol/ for the same build. This
  keeps the on-disk protocol bundle byte-identical to the frozen interface
  (Lead's protocolSha256 over all 35 files), including README.md,
  c/sixmic_analysis_wire.h and tools/generate_*.py (kept for reproducibility of
  the frozen golden samples). Only __pycache__/.pyc build artifacts are skipped.

  Refresh without rebuilding the exe:
    powershell -ExecutionPolicy Bypass -File apps/sixmic-desktop/packaging/refresh_protocol_bundle.ps1
"""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

# Entries copied from interfaces/pc_backend_v1 into <bundle>/protocol/
# (dirs are copied recursively; files are copied as-is)
SHIPPED_ENTRIES: tuple[str, ...] = (
    "schema",
    "golden",
    "errors",
    "features",
    "device",
    "dto",
    "c",
    "tools",
    "PROTOCOL.md",
    "README.md",
)

# Hard preflight requirements: build must fail (or explicitly allow) if missing.
REQUIRED_FILES: tuple[str, ...] = (
    "PROTOCOL.md",
    "errors/ERROR_CATALOG.json",
    "golden/GOLDEN_MANIFEST.json",
    "features/FEATURE_CATALOG.json",
    "schema/control.schema.json",
)

# Nothing is intentionally excluded from the frozen interface bundle anymore.
# (Kept for copy_protocol_data.py's negative check / future policy changes.)
EXCLUDED_ENTRIES: tuple[str, ...] = ()


def find_missing_required(interfaces_dir: Path) -> list[str]:
    """Return repo-relative required files that do not exist."""
    return [rel for rel in REQUIRED_FILES if not (interfaces_dir / rel).is_file()]


def _is_shippable(path: Path) -> bool:
    if not path.is_file():
        return False
    if "__pycache__" in path.parts or path.suffix.lower() == ".pyc":
        return False
    return True


def iter_shipped_files(interfaces_dir: Path) -> list[Path]:
    """Return every file that must ship, in stable sorted order."""
    files: list[Path] = []
    for entry in SHIPPED_ENTRIES:
        src = interfaces_dir / entry
        if src.is_file() and _is_shippable(src):
            files.append(src)
        elif src.is_dir():
            files.extend(sorted(p for p in src.rglob("*") if _is_shippable(p)))
    return files


def collect_datas(interfaces_dir: Path) -> list[tuple[str, str]]:
    """PyInstaller datas entries: [(absolute source file, dest directory)].

    Destination is protocol/<repo-relative-dir> so the bundle layout is
    _internal/protocol/<same tree>.
    """
    out: list[tuple[str, str]] = []
    for path in iter_shipped_files(interfaces_dir):
        rel = path.relative_to(interfaces_dir)
        dest = PurePosixPath("protocol", *rel.parts[:-1])
        out.append((str(path), str(dest)))
    return out


def bundle_manifest(interfaces_dir: Path) -> dict:
    """Stable manifest used as build evidence (paths + sizes + sha256)."""
    files = []
    for path in iter_shipped_files(interfaces_dir):
        rel = path.relative_to(interfaces_dir).as_posix()
        data = path.read_bytes()
        files.append(
            {
                "path": rel,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    canonical = "\n".join(str(f["sha256"]) + "  " + str(f["path"]) for f in files)
    return {
        "source": str(interfaces_dir),
        "fileCount": len(files),
        "totalBytes": sum(int(f["bytes"]) for f in files),
        "manifestSha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "files": files,
    }
