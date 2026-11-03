"""Pytest configuration + evidence summary for the feature-wiring E2E suite.

Every test in this directory drives the *real* application transport stack
(DeviceSession + stock pc_client.FeatureClient) against the deterministic host
fixture gateway.  Read harness.py first: nothing here is pl-live, board data or
numerically verified.
"""
from __future__ import annotations

import json
import platform
import re
import sys
import time
from pathlib import Path

E2E_DIR = Path(__file__).resolve().parent
APP_ROOT = E2E_DIR.parents[1]
for extra in (str(APP_ROOT), str(APP_ROOT / "backend")):
    if extra not in sys.path:
        sys.path.insert(0, extra)

import pytest  # noqa: E402

import harness  # noqa: E402

_RESULTS: dict[str, dict] = {}
_SESSION_START = time.time()


def pytest_configure(config) -> None:
    config.addinivalue_line(
        "markers",
        "e2e: end-to-end host-fixture test (SIMULATED/test-fixture, not pl-live)")
    harness.ensure_evidence_dir()
    harness.cleanup_stale_tmp()


def pytest_collection_modifyitems(config, items) -> None:
    if harness.SERVER_EXE.is_file():
        return
    skip = pytest.mark.skip(reason=f"host fixture executable missing: {harness.SERVER_EXE}")
    for item in items:
        item.add_marker(skip)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    node = _RESULTS.setdefault(report.nodeid, {
        "nodeid": report.nodeid, "name": report.nodeid.split("::")[-1],
        "outcome": "unknown", "durationSeconds": 0.0, "phases": {}})
    node["durationSeconds"] = round(node["durationSeconds"] + report.duration, 4)
    node["phases"][report.when] = {
        "outcome": report.outcome,
        "durationSeconds": round(report.duration, 4),
        "wasxfail": getattr(report, "wasxfail", None),
    }
    if report.when == "call":
        if report.outcome == "passed":
            node["outcome"] = "passed"
        elif report.outcome == "skipped":
            node["outcome"] = "xfailed" if getattr(report, "wasxfail", None) else "skipped"
        else:
            node["outcome"] = "failed"
    elif report.when == "setup" and report.outcome != "passed":
        node["outcome"] = "skipped" if report.outcome == "skipped" else "failed"


def pytest_sessionfinish(session, exitstatus) -> None:
    tests = sorted(_RESULTS.values(), key=lambda row: row["nodeid"])
    counts = {name: sum(1 for row in tests if row["outcome"] == name)
              for name in ("passed", "failed", "skipped", "xfailed")}
    payload = {
        "suite": "apps/sixmic-desktop/tests/e2e",
        "pytestExitStatus": int(exitstatus),
        "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(_SESSION_START)),
        "finishedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "durationSeconds": round(time.time() - _SESSION_START, 3),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "fixtureExecutable": str(harness.SERVER_EXE),
        "fixtureExecutableSha256": harness.file_sha256(harness.SERVER_EXE),
        "specPath": str(harness.SPEC_JSON),
        "specSha256": harness.file_sha256(harness.SPEC_JSON),
        "registryPath": str(harness.REGISTRY_JSON),
        "registrySha256": harness.file_sha256(harness.REGISTRY_JSON),
        "fixtureProcessStarts": len(harness.GATEWAY_STARTS),
        "counts": counts,
        "tests": tests,
    }
    path = harness.record_artifact("e2e_summary", payload)
    print(f"\nE2E_SUMMARY {json.dumps(counts, sort_keys=True)} -> {path}")


@pytest.fixture()
def stack(request):
    label = re.sub(r"[^a-z0-9]+", "-", request.node.name.lower()).strip("-")[:40] or "e2e"
    app = harness.AppStack(label=label)
    try:
        yield app
    finally:
        app.close()
