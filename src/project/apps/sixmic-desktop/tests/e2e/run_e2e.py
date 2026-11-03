"""Run the feature-wiring E2E suite and persist evidence + a pytest log.

Usage (from the repository root):
    apps/sixmic-desktop/.venv/Scripts/python.exe apps/sixmic-desktop/tests/e2e/run_e2e.py

The suite launches the host fixture gateway (SIMULATED / test-fixture) for every
test and drives it through the real application stack.  Exit code mirrors
pytest's.  Evidence JSON files land in apps/sixmic-desktop/tests/e2e/evidence/.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

E2E_DIR = Path(__file__).resolve().parent
APP_ROOT = E2E_DIR.parents[1]
evidence = E2E_DIR / "evidence"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    evidence.mkdir(parents=True, exist_ok=True)
    for stale in evidence.glob("*.json"):
        try:
            stale.unlink()
        except OSError:
            pass
    command = [sys.executable, "-m", "pytest", str(E2E_DIR), "-q", "-p", "no:cacheprovider"]
    command.extend(argv)
    started = time.monotonic()
    completed = subprocess.run(command, cwd=str(APP_ROOT), text=True,
                               capture_output=True)
    elapsed = time.monotonic() - started
    output = (completed.stdout or "") + (completed.stderr or "")
    print(output, end="" if output.endswith("\n") else "\n")
    (evidence / "pytest.log").write_text(output, encoding="utf-8")
    summary_path = evidence / "e2e_summary.json"
    print(f"E2E_RUN exit={completed.returncode} elapsed={elapsed:.1f}s "
          f"summary={summary_path}")
    if summary_path.is_file():
        document = json.loads(summary_path.read_text(encoding="utf-8"))
        payload = document.get("payload", document)
        print(json.dumps({"counts": payload.get("counts"),
                          "pytestExitStatus": payload.get("pytestExitStatus"),
                          "durationSeconds": payload.get("durationSeconds"),
                          "fixtureProcessStarts": payload.get("fixtureProcessStarts")},
                         ensure_ascii=False, indent=2))
    else:
        print(f"E2E_RUN_MISSING_SUMMARY {summary_path}")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
