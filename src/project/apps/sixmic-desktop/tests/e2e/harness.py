"""E2E harness for the 51-feature wiring.

The harness is deliberately explicit about what is and is not being tested:

* SIMULATED / test-fixture: every byte here comes from the host fixture
  gateway deployment/echo_feature_closure_20261025/ps/build/host/test-feature-server.exe
  (a deterministic MMIO model, numericDSPVerified=false).  It is not a
  PL bitstream, not the board, not acoustic data, and it establishes no numeric
  acceptance.
* The application stack is real: sixmic_backend.session.DeviceSession
  (frozen control/binary transport, DataStore, identity validation) plus the
  stock pc_client.FeatureClient that the product UI layer consumes.  The stock
  client (Lead change 2026-10-26) paces its own control requests with a
  64 req/s / 64 burst token bucket, so this harness exercises the shipping
  client unchanged.
* No CPU DSP, no PC-side acoustic algorithm, no fabricated words.

The fixture gateway rate-limits the control channel to 64 requests/second with
a burst of 128 (ps/gateway/include/gateway.h); the stock client keeps below it.
Raw protocol probes in this harness acquire the same client budget instead of
opening an independent faster path.

Each fixture process exits on its own after 60 s of wall clock
(ps/gateway/tests/test_feature_server.c), so tests start a fresh fixture rather
than sharing one globally.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(APP_ROOT / "backend"))

DEPLOY_ROOT = REPO_ROOT / "deployment" / "echo_feature_closure_20261025"
SERVER_EXE = DEPLOY_ROOT / "ps" / "build" / "host" / "test-feature-server.exe"
REGISTRY_JSON = DEPLOY_ROOT / "registry" / "INTERFACE_REGISTRY.json"
PROFILE_INIT = DEPLOY_ROOT / "ps" / "profiles" / "default" / "profile_init.smi"
SPEC_JSON = APP_ROOT / "ui" / "config" / "feature_view_spec.json"

E2E_DIR = Path(__file__).resolve().parent
TMP_ROOT = E2E_DIR / "_tmp"
EVIDENCE_DIR = Path(os.environ.get("SIXMIC_E2E_EVIDENCE_DIR",
                                   str(E2E_DIR / "evidence")))

#: Human-readable marker that must accompany every artifact emitted by the harness.
SIMULATED_BANNER = (
    "SIMULATED / test-fixture - host fixture gateway "
    "(deployment/echo_feature_closure_20261025/ps/build/host/test-feature-server.exe); "
    "sourceKind=test-fixture; numericDSPVerified=false; hardwareState=NOT_TESTED; "
    "this is not pl-live, not a board, not acoustic acceptance."
)

#: Gateway control channel contract: 64 requests/second, burst 128.
RATE_PER_SECOND = 64.0
PROTOCOL_VERSION = "echo-features-1"

#: Every fixture start is recorded for the evidence summary (fresh-per-test rule).
GATEWAY_STARTS: list[dict] = []


class FixtureError(RuntimeError):
    """The host fixture gateway could not be launched or violated its contract."""


class GatewayProcess:
    """One test-feature-server.exe process, ready-line contract checked."""

    def __init__(self, label: str = "e2e") -> None:
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex[:10]
        self.work_dir = TMP_ROOT / f"{label}-{token}"
        self.spool = self.work_dir / "spool"
        self.userdata = self.work_dir / "userdata"
        self.spool.mkdir(parents=True, exist_ok=True)
        self.userdata.mkdir(parents=True, exist_ok=True)
        if not SERVER_EXE.is_file():
            raise FixtureError(f"fixture executable missing: {SERVER_EXE}")
        self.started_at = time.time()
        self.proc = subprocess.Popen(
            [str(SERVER_EXE), str(REGISTRY_JSON), str(PROFILE_INIT), str(self.spool)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            cwd=str(REPO_ROOT))
        self.ready = self._read_ready_line()
        self.stderr_text = ""
        self._verify_ready()
        GATEWAY_STARTS.append({"label": label, "startedAt": self.started_at,
                               "ready": dict(self.ready),
                               "workDir": str(self.work_dir)})

    def _read_ready_line(self, timeout: float = 30.0) -> dict:
        box: dict[str, object] = {}

        def reader() -> None:
            try:
                box["line"] = self.proc.stdout.readline()
            except Exception as exc:  # noqa: BLE001 - surface any read failure
                box["error"] = repr(exc)

        thread = threading.Thread(target=reader, name="fixture-ready", daemon=True)
        thread.start()
        thread.join(timeout)
        line = box.get("line")
        if not line:
            detail = ""
            if self.proc.poll() is not None:
                detail = (self.proc.stderr.read() or "")[-2000:]
            self.stop()
            raise FixtureError(f"fixture did not print a ready line ({detail!r})")
        try:
            return json.loads(str(line))
        except ValueError as exc:
            self.stop()
            raise FixtureError(f"fixture ready line is not JSON: {line!r}") from exc

    def _verify_ready(self) -> None:
        ready = self.ready
        for key in ("controlPort", "binaryPort"):
            value = ready.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                self.stop()
                raise FixtureError(f"fixture ready.{key} invalid: {value!r}")
        if ready.get("sourceKind") != "test-fixture":
            self.stop()
            raise FixtureError(f"fixture sourceKind must be test-fixture: {ready!r}")
        if ready.get("numericDSPVerified") is not False:
            self.stop()
            raise FixtureError(f"fixture must report numericDSPVerified=false: {ready!r}")

    # -- paths for the app stack ------------------------------------------
    def user_dirs(self) -> dict[str, Path]:
        layout: dict[str, Path] = {}
        for name in ("logs", "data", "recordings", "events", "exports", "evidence"):
            path = self.userdata / name
            path.mkdir(parents=True, exist_ok=True)
            layout[name] = path
        layout["root"] = self.userdata
        return layout

    def server_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["SIXMIC_USER_DATA_DIR"] = str(self.userdata)
        return env

    def stop(self) -> str:
        proc = getattr(self, "proc", None)
        if proc is None:
            return self.stderr_text
        if proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        try:
            self.stderr_text = proc.stderr.read() or ""
        except (OSError, ValueError):
            self.stderr_text = ""
        return self.stderr_text


TERMINAL_STATES = ("completed", "failed", "canceled")


class AppStack:
    """Real application transport stack against one fixture gateway process."""

    def __init__(self, label: str = "e2e") -> None:
        self.label = label
        self.gateway = GatewayProcess(label)
        self.ready = self.gateway.ready
        from pc_client import FeatureClient
        from sixmic_backend.data.config_store import ConfigStore
        from sixmic_backend.session import DeviceSession

        user_dirs = self.gateway.user_dirs()
        self.session = DeviceSession(
            host="127.0.0.1",
            control_port=int(self.ready["controlPort"]),
            binary_port=int(self.ready["binaryPort"]),
            user_dirs=user_dirs,
            config_store=ConfigStore(path=user_dirs["root"] / "config.json"),
            auto_reconnect=False)
        self.hello = self.session.connect()
        # Stock shipping client (paced); NOT a test-local subclass.
        self.client = FeatureClient(self.session)
        self.request_count = 0

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        stderr = ""
        try:
            self.session.close()
        finally:
            stderr = self.gateway.stop()
        if stderr and "usage:" in stderr:
            raise FixtureError(f"fixture usage error: {stderr[-500:]}")

    # -- low level (still the application's transport adapter) -------------
    def _pace(self) -> None:
        limiter = getattr(self.client, "_limiter", None)
        if limiter is not None:
            limiter.acquire()

    def raw_request(self, op: str, args: dict | None = None) -> dict:
        from pc_client.transport import request as feature_request

        self._pace()
        self.request_count += 1
        return feature_request(self.session.control, op, dict(args or {}))

    def raw_session_request(self, op: str, args: dict | None = None) -> dict:
        """Frozen control op (e.g. event.list) through the frozen ControlClient."""
        self._pace()
        self.request_count += 1
        return self.session.control.request(op, dict(args or {}))

    # -- app-level helpers -------------------------------------------------
    def start(self, feature_id: str, params: dict | None = None) -> dict:
        accepted = self.client.start_feature(feature_id, params or {})
        self.assert_identity(accepted, feature_id)
        return accepted

    def get(self, job_id: str) -> dict:
        return self.client.get_feature(job_id)

    def stop(self, job_id: str) -> dict:
        return self.client.stop_feature(job_id)

    def wait(self, job_id: str, *, timeout: float = 15.0,
             states: tuple[str, ...] = TERMINAL_STATES, feature_id: str | None = None,
             interval: float = 0.005) -> dict:
        deadline = time.monotonic() + timeout
        last: dict | None = None
        while True:
            last = self.client.get_feature(job_id)
            if feature_id is not None:
                self.assert_identity(last, feature_id)
            if last["state"] in states:
                return last
            if time.monotonic() >= deadline:
                raise AssertionError(
                    f"job {job_id} not in {states} within {timeout}s: "
                    f"state={last.get('state')!r} progress={last.get('progress')!r}")
            time.sleep(interval)

    def wait_completed(self, accepted: dict, *, timeout: float = 15.0) -> dict:
        return self.wait(accepted["jobId"], timeout=timeout,
                         feature_id=accepted.get("featureId"))

    def result_page(self, job_id: str, offset: int = 0, max_words: int = 1024) -> dict:
        return self.raw_request("feature.result", {
            "jobId": job_id, "offsetWords": int(offset), "maxWords": int(max_words)})

    def catalog_scan(self, limit: int = 8) -> dict:
        cursor, pages, ids = 0, [], []
        while cursor is not None:
            page = self.raw_request("feature.list", {"cursor": cursor, "limit": int(limit)})
            pages.append(page)
            ids.extend(feature["featureId"] for feature in page["features"])
            cursor = page.get("nextCursor")
        return {"pages": pages, "featureIds": ids, "pageCount": len(pages)}

    # -- identity contract -------------------------------------------------
    @staticmethod
    def assert_test_fixture(kind: str, value: dict) -> None:
        if value.get("sourceKind") != "test-fixture":
            raise AssertionError(f"{kind}.sourceKind must be test-fixture: {value!r}")

    @classmethod
    def assert_identity(cls, value: dict, feature_id: str | None = None) -> None:
        if not isinstance(value.get("jobId"), str) or not value["jobId"]:
            raise AssertionError(f"missing jobId: {value!r}")
        if feature_id is not None and value.get("featureId") != feature_id:
            raise AssertionError(
                f"featureId mismatch: {value.get('featureId')!r} != {feature_id!r}")
        cls.assert_test_fixture("operation", value)
        configuration = value.get("configuration")
        if not isinstance(configuration, dict):
            raise AssertionError(f"missing configuration: {value!r}")
        for key in ("session", "config", "generation", "sourceFrame"):
            if key not in configuration:
                raise AssertionError(f"configuration.{key} missing: {configuration!r}")
        for key in ("generation", "sourceFrame"):
            # Counters cross the wire as decimal strings; FeatureClient keeps them.
            raw = configuration[key]
            if not isinstance(raw, str) or not raw.isdigit():
                raise AssertionError(
                    f"configuration.{key} must be a decimal string, got {raw!r}")

    @classmethod
    def assert_result(cls, result) -> dict:
        payload = result.to_dict()
        cls.assert_identity(payload)
        data_ref = payload["dataRef"]
        if data_ref.get("sourceKind") != "test-fixture":
            raise AssertionError(f"dataRef.sourceKind must be test-fixture: {data_ref!r}")
        if data_ref.get("elementType") != "uint32":
            raise AssertionError(f"dataRef.elementType must be uint32: {data_ref!r}")
        if data_ref.get("count") != payload["totalWords"]:
            raise AssertionError("dataRef.count != totalWords")
        return payload

    # -- evidence ----------------------------------------------------------
    def fixture_note(self) -> dict:
        limiter = getattr(self.client, "_limiter", None)
        return {
            "banner": SIMULATED_BANNER,
            "sourceKind": "test-fixture",
            "simulated": True,
            "numericDSPVerified": False,
            "hardwareState": "NOT_TESTED",
            "fixtureExe": str(SERVER_EXE.relative_to(REPO_ROOT)),
            "fixtureReady": dict(self.ready),
            "fixtureExeSha256": file_sha256(SERVER_EXE),
            "clientPacing": {
                "class": type(self.client).__module__ + "." + type(self.client).__name__,
                "rate": getattr(limiter, "rate", None),
                "capacity": getattr(limiter, "capacity", None),
                "requests": getattr(limiter, "requests", None),
                "waitedSeconds": round(getattr(limiter, "waited_seconds", 0.0), 3),
            },
        }


def file_sha256(path: Path) -> str:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""


def load_spec() -> dict:
    return json.loads(SPEC_JSON.read_text(encoding="utf-8"))


def ensure_evidence_dir() -> Path:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    return EVIDENCE_DIR


def record_artifact(name: str, payload: dict) -> Path:
    """Write one evidence JSON; every artifact carries the simulated marker."""
    directory = ensure_evidence_dir()
    path = directory / (name if name.endswith(".json") else name + ".json")
    document = {
        "artifact": path.stem,
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "banner": SIMULATED_BANNER,
        "sourceKind": "test-fixture",
        "simulated": True,
        "numericDSPVerified": False,
        "hardwareState": "NOT_TESTED",
        "payload": payload,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(path)
    return path


def read_artifact(name: str) -> dict | None:
    path = ensure_evidence_dir() / (name if name.endswith(".json") else name + ".json")
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def cleanup_stale_tmp(max_age_seconds: float = 3600.0) -> None:
    if not TMP_ROOT.is_dir():
        return
    now = time.time()
    for child in TMP_ROOT.iterdir():
        try:
            if not child.is_dir() or now - child.stat().st_mtime < max_age_seconds:
                continue
            shutil.rmtree(child, ignore_errors=True)
        except OSError:
            continue
