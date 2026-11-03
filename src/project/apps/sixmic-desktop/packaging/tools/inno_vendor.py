"""Verify the vendored, build-time Inno Setup compiler provenance.

The SixMic3D installer is compiled by an official Inno Setup release that was
unpacked offline (not installed) into packaging/vendor/InnoSetup6 - see
vendor/README.md. This tool re-verifies that tree against the recorded hashes
so every installer build lane carries real provenance evidence instead of a
claim.

Checks (all must pass for exit 0):
  * vendor/MANIFEST.json exists and is well-formed;
  * every file in InnoSetup6.INVENTORY.sha256 matches its recorded SHA256
    (sha256sum format: "<hex>  <relative/path>");
  * the recomputed tree inventory SHA256 matches
    MANIFEST.compiler.extractedTreeInventorySha256 (same algorithm as
    tools/bundle_evidence.py inventorySha256);
  * ISCC.exe / ISCmplr.dll match MANIFEST.compiler hashes;
  * the vendored innoextract tool files match MANIFEST.extraction hashes.

Exit codes: 0 = verified, 1 = verification failed, 2 = bad arguments.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PACKAGING_DIR = Path(__file__).resolve().parent.parent
DEFAULT_VENDOR = PACKAGING_DIR / "vendor"
TREE_NAME = "InnoSetup6"
INVENTORY_NAME = "InnoSetup6.INVENTORY.sha256"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory(tree: Path) -> tuple[list[dict], str]:
    files: list[dict] = []
    for path in sorted(p for p in tree.rglob("*") if p.is_file()):
        files.append({
            "path": path.relative_to(tree).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    canonical = "\n".join(item["sha256"] + "  " + item["path"] for item in files)
    return files, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_inventory_file(path: Path) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2:
            raise SystemExit("malformed inventory line in " + str(path) + ": " + line)
        entries.append((parts[0].strip().lower(), parts[1].strip()))
    return entries


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--vendor", default=str(DEFAULT_VENDOR), help="packaging/vendor directory")
    parser.add_argument("--json", action="store_true", help="print JSON only")
    parser.add_argument("--report", help="write JSON report here")
    args = parser.parse_args(argv)

    vendor = Path(args.vendor).resolve()
    tree = vendor / TREE_NAME
    manifest_path = vendor / "MANIFEST.json"
    inventory_path = vendor / INVENTORY_NAME
    problems: list[str] = []
    result: dict = {
        "vendor": str(vendor),
        "tree": str(tree),
        "manifest": str(manifest_path),
        "inventoryFile": str(inventory_path),
        "iscc": None,
        "inventory": None,
        "checks": [],
        "ok": False,
        "problems": problems,
    }

    def check(name: str, ok: bool, detail: str) -> None:
        result["checks"].append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})
        if not ok:
            problems.append(name + ": " + detail)

    manifest: dict = {}
    if not manifest_path.is_file():
        check("manifest-exists", False, str(manifest_path))
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            check("manifest-exists", True, str(manifest_path))
        except Exception as exc:  # noqa: BLE001 - evidence tool
            check("manifest-exists", False, "unreadable: " + repr(exc))

    if not tree.is_dir():
        check("tree-exists", False, str(tree))
        payload = json.dumps(result, indent=2)
        print(payload)
        if args.report:
            Path(args.report).write_text(payload + "\n", encoding="utf-8")
        return 1
    check("tree-exists", True, str(tree))

    files, inventory_sha = inventory(tree)
    expected_inventory_sha = str((manifest.get("compiler") or {}).get("extractedTreeInventorySha256") or "").strip().lower()
    result["inventory"] = {
        "fileCount": len(files),
        "totalBytes": sum(int(f["bytes"]) for f in files),
        "inventorySha256": inventory_sha,
        "expectedInventorySha256": expected_inventory_sha or None,
    }
    check(
        "inventory-sha256",
        bool(expected_inventory_sha) and inventory_sha == expected_inventory_sha,
        "recomputed=" + inventory_sha + " expected=" + (expected_inventory_sha or "<missing in MANIFEST>"),
    )

    expected_entries: dict[str, str] = {}
    if not inventory_path.is_file():
        check("inventory-file-exists", False, str(inventory_path))
    else:
        try:
            for sha, rel in parse_inventory_file(inventory_path):
                expected_entries[rel.replace("\\", "/")] = sha
            check("inventory-file-exists", True, str(inventory_path) + " (" + str(len(expected_entries)) + " entries)")
        except SystemExit as exc:
            check("inventory-file-exists", False, str(exc))

    if expected_entries:
        actual = {item["path"]: item["sha256"] for item in files}
        missing = sorted(set(expected_entries) - set(actual))
        extra = sorted(set(actual) - set(expected_entries))
        mismatched = sorted(rel for rel in set(expected_entries) & set(actual) if expected_entries[rel] != actual[rel])
        check(
            "inventory-per-file",
            not missing and not extra and not mismatched,
            "missing=" + repr(missing[:5]) + " extra=" + repr(extra[:5]) + " mismatched=" + repr(mismatched[:5]),
        )

    compiler = manifest.get("compiler") or {}
    for name, key in (("ISCC.exe", "isccSha256"), ("ISCmplr.dll", "iscCmplrDllSha256")):
        expected = str(compiler.get(key) or "").strip().lower()
        path = tree / name
        if not path.is_file():
            check("hash-" + name, False, "missing " + str(path))
            continue
        actual = sha256_file(path)
        check("hash-" + name, bool(expected) and actual == expected, "sha256=" + actual + " expected=" + (expected or "<missing>"))
        if name == "ISCC.exe":
            result["iscc"] = {"path": str(path), "sha256": actual, "bytes": path.stat().st_size}

    extraction = manifest.get("extraction") or {}
    tool_dir = vendor / "tools" / "innoextract-1.9"
    for filename, key in (("innoextract-1.9-windows.zip", "toolZipSha256"), ("innoextract.exe", "toolExeSha256")):
        expected = str(extraction.get(key) or "").strip().lower()
        path = tool_dir / filename
        if not path.is_file():
            check("tool-" + filename, False, "missing " + str(path))
            continue
        actual = sha256_file(path)
        check("tool-" + filename, bool(expected) and actual == expected, "sha256=" + actual + " expected=" + (expected or "<missing>"))

    check(
        "compiler-version",
        bool(str(compiler.get("version") or "").strip()),
        "declared=" + str(compiler.get("version") or "<missing>"),
    )

    result["ok"] = not problems
    payload = json.dumps(result, indent=2)
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(payload + "\n", encoding="utf-8")
    if args.json:
        print(payload)
    else:
        print("Inno Setup vendor provenance - " + str(tree))
        for item in result["checks"]:
            print("[{0:4}] {1}: {2}".format(item["status"], item["name"], item["detail"]))
        print()
        print("RESULT: " + ("PASS" if result["ok"] else "FAIL") + " (" + str(len(result["checks"])) + " checks)")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
