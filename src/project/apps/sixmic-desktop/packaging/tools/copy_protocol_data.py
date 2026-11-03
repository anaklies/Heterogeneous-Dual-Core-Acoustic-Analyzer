"""Copy the shipped protocol data next to a frozen SixMic3D executable.

Run by build_backend_check.ps1 / build_desktop.ps1 after PyInstaller:
  python tools/copy_protocol_data.py --interfaces <repo>/interfaces/pc_backend_v1 \
      --dest <dist>/SixMic3D-BackendCheck/protocol --report <build-log>/protocol_manifest.json

Evidence written by this tool is the authoritative list of protocol files that
ship next to the exe (path + bytes + sha256), mirroring the PyInstaller datas
under _internal/protocol/ from tools/protocol_data.py.

Exit codes: 0 copied+verified, 2 required data missing, 3 copy/verify failed,
4 refused unsafe destination.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))
import protocol_data  # noqa: E402


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fail(code: int, message: str) -> int:
    print("FAIL: " + message, file=sys.stderr)
    return code


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--interfaces", required=True, help="repo interfaces/pc_backend_v1 directory")
    parser.add_argument("--dest", required=True, help="destination protocol/ directory next to the exe")
    parser.add_argument("--report", help="write JSON evidence manifest here")
    parser.add_argument("--allow-missing", action="store_true")
    args = parser.parse_args(argv)

    interfaces = Path(args.interfaces).resolve()
    dest = Path(args.dest).resolve()
    if not interfaces.is_dir():
        return fail(2, "interfaces directory not found: " + str(interfaces))
    if dest.name.lower() != "protocol":
        return fail(4, "refusing destination that is not named protocol: " + str(dest))

    missing = protocol_data.find_missing_required(interfaces)
    if missing and not args.allow_missing:
        return fail(2, "required protocol data missing: " + ", ".join(missing))
    if missing:
        print("WARNING: copying protocol data with required files missing: " + ", ".join(missing), file=sys.stderr)

    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    copied: list[dict] = []
    try:
        for entry in protocol_data.SHIPPED_ENTRIES:
            src = interfaces / entry
            if src.is_file():
                target = dest / entry
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)
            elif src.is_dir():
                shutil.copytree(src, dest / entry)
    except OSError as exc:
        return fail(3, "copy failed: " + repr(exc))

    # verify every shipped file exists and matches byte-for-byte
    problems: list[str] = []
    for path in protocol_data.iter_shipped_files(interfaces):
        rel = path.relative_to(interfaces)
        target = dest / rel
        if not target.is_file():
            problems.append("missing after copy: " + rel.as_posix())
        elif sha256_file(path) != sha256_file(target):
            problems.append("hash mismatch after copy: " + rel.as_posix())
        else:
            copied.append(
                {
                    "path": rel.as_posix(),
                    "bytes": target.stat().st_size,
                    "sha256": sha256_file(target),
                }
            )
    # forbid shipping things that are repo-source-only
    forbidden: list[str] = []
    for entry in protocol_data.EXCLUDED_ENTRIES:
        if (dest / entry).exists():
            forbidden.append(entry)
    if forbidden:
        problems.append("forbidden entries copied: " + ", ".join(forbidden))
    if problems:
        return fail(3, "; ".join(problems))

    canonical = "\n".join(str(item["sha256"]) + "  " + str(item["path"]) for item in copied)
    manifest = {
        "source": str(interfaces),
        "destination": str(dest),
        "fileCount": len(copied),
        "totalBytes": sum(int(item["bytes"]) for item in copied),
        "manifestSha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "missingRequired": missing,
        "excludedEntriesAbsent": forbidden == [],
        "files": copied,
    }
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print("report: " + str(report_path))
    print(
        "COPIED " + str(manifest["fileCount"]) + " protocol files, " + str(manifest["totalBytes"]) +
        " bytes to " + str(dest) + " manifestSha256=" + str(manifest["manifestSha256"])
    )
    print(json.dumps({k: manifest[k] for k in ("fileCount", "totalBytes", "manifestSha256", "destination")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
