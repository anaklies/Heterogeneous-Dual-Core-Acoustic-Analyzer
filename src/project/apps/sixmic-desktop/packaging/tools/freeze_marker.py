"""Compute the Lead's code-state freeze markers (reproducible).

Algorithm (agreed with Lead 2026-10-24; case-insensitivity confirmed empirically):
  line  = '<posix-relative-path> <sha256hex-of-file-bytes>'  (single space)
  lines = sorted by posix-relative-path CASE-INSENSITIVELY, joined by LF,
          NO trailing LF
  marker = sha256(UTF-8 bytes of that text)

backendSha256  : all sixmic_backend/**/*.py (regular files, __pycache__ excluded),
                 relative paths from apps/sixmic-desktop/backend/sixmic_backend/
protocolSha256 : ALL regular files under interfaces/pc_backend_v1
                 (relative paths from interfaces/pc_backend_v1)

Usage (from repo root, any Python):
  python apps/sixmic-desktop/packaging/tools/freeze_marker.py
  python apps/sixmic-desktop/packaging/tools/freeze_marker.py --json
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PACKAGING_DIR = TOOLS_DIR.parent
APP_DIR = PACKAGING_DIR.parent
REPO_ROOT = APP_DIR.parent.parent
BACKEND_ROOT = APP_DIR / "backend" / "sixmic_backend"
PROTOCOL_ROOT = REPO_ROOT / "interfaces" / "pc_backend_v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def marker(root: Path, files: list[Path]) -> tuple[str, list[str]]:
    lines = []
    ordered = sorted(files, key=lambda p: p.relative_to(root).as_posix().lower())
    for path in ordered:
        rel = path.relative_to(root).as_posix()
        lines.append(rel + " " + sha256_file(path))
    text = "\n".join(lines)
    return hashlib.sha256(text.encode("utf-8")).hexdigest(), lines


def backend_files() -> list[Path]:
    return [
        p
        for p in BACKEND_ROOT.rglob("*.py")
        if p.is_file() and "__pycache__" not in p.parts
    ]


def protocol_files() -> list[Path]:
    return [
        p
        for p in PROTOCOL_ROOT.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    ]


def main(argv: list[str]) -> int:
    backend_marker, backend_lines = marker(BACKEND_ROOT, backend_files())
    protocol_marker, protocol_lines = marker(PROTOCOL_ROOT, protocol_files())
    report = {
        "algorithm": "sha256(UTF-8('\n'.join(sorted('<posix-rel-path> <sha256hex>')))) no trailing LF",
        "backendRoot": str(BACKEND_ROOT),
        "backendFileCount": len(backend_lines),
        "backendSha256": backend_marker,
        "protocolRoot": str(PROTOCOL_ROOT),
        "protocolFileCount": len(protocol_lines),
        "protocolSha256": protocol_marker,
    }
    if "--json" in argv:
        print(json.dumps(report, indent=2))
    else:
        print("backendSha256=" + backend_marker + " (" + str(len(backend_lines)) + " .py files under sixmic_backend/)")
        print("protocolSha256=" + protocol_marker + " (" + str(len(protocol_lines)) + " files under interfaces/pc_backend_v1)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
