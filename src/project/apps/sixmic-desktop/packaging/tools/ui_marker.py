"""Reproducible UI source-freeze marker for the SixMic3D frontend handoff.

Scheme (agreed with the Lead):
    lines  = "<posix relative path> <sha256 hex of file bytes>" for every regular
             file under apps/sixmic-desktop/{ui,themes,assets} plus main.py
             (paths relative to apps/sixmic-desktop)
    order  = sorted case-insensitively by path
    text   = lines joined with LF, no trailing LF
    marker = sha256(UTF-8 bytes of text)

This is the marker the Lead cites as uiSha256 (e.g. the frozen frontend for the
Windows release). __pycache__ files are included by default because that is how
the Lead's freeze marker is computed; --no-pycache additionally reports the
sources-only marker (useful because bytecode caches can be regenerated).

Exit codes: 0 = computed, 2 = bad arguments.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PACKAGING_DIR = Path(__file__).resolve().parent.parent
APP_DIR = PACKAGING_DIR.parent


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ui_files(app_dir: Path, include_pycache: bool = True) -> list[str]:
    entries: list[str] = []
    for root_name in ("ui", "themes", "assets"):
        root = app_dir / root_name
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(app_dir).as_posix()
            if not include_pycache and "__pycache__" in rel:
                continue
            entries.append(rel)
    main_py = app_dir / "main.py"
    if main_py.is_file():
        entries.append("main.py")
    return sorted(set(entries), key=lambda s: s.lower())


def compute_marker(app_dir: str | Path | None = None, include_pycache: bool = True) -> dict:
    app = Path(app_dir) if app_dir else APP_DIR
    files = ui_files(app, include_pycache=include_pycache)
    parts = [rel + " " + sha256_file(app / rel) for rel in files]
    marker = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return {
        "appDir": str(app),
        "scheme": "path+sha256 lines sorted case-insensitively, LF joined, sha256 of UTF-8",
        "includePycache": bool(include_pycache),
        "fileCount": len(files),
        "uiSha256": marker,
        "files": files,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--app-dir", help="apps/sixmic-desktop directory (default: derived from this file)")
    parser.add_argument("--json", action="store_true", help="print JSON")
    parser.add_argument("--report", help="write JSON to this path")
    parser.add_argument("--no-pycache", action="store_true", help="exclude __pycache__ from the file set")
    args = parser.parse_args(argv)
    include_pycache = not args.no_pycache
    result = compute_marker(args.app_dir, include_pycache=include_pycache)
    sources_only = compute_marker(args.app_dir, include_pycache=False)
    result["sourcesOnly"] = {
        "fileCount": sources_only["fileCount"],
        "uiSha256": sources_only["uiSha256"],
    }
    payload = json.dumps(result, indent=2)
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(payload + "\n", encoding="utf-8")
    if args.json:
        print(payload)
    else:
        print("uiSha256=" + result["uiSha256"] + " files=" + str(result["fileCount"]) + " includePycache=" + str(result["includePycache"]))
        print("sourcesOnly uiSha256=" + result["sourcesOnly"]["uiSha256"] + " files=" + str(result["sourcesOnly"]["fileCount"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))