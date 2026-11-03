"""Capture a real (test-fixture) feature wire survey from the host gateway.

The device candidate gateway is NOT hardware: it is run over real TCP from
deployment/echo_feature_closure_20261025/ps/build/host/test-feature-server.exe
with the explicit INTERFACE_REGISTRY.json and a deterministic fixture profile.
This script talks JSON-lines on the control port (48120-equivalent random port)
and stores the real ``schema`` (including actualProducerLayout) plus a bounded
head of raw words for every captured result.  Output is clearly marked
sourceKind=test-fixture / hardwareState=NOT_TESTED; it is layout evidence only,
never acoustic measurement data.

Usage (from repo root, after starting the host server):
    <venv-python> tests/frontend/fixtures/features/capture_host_gateway.py \
        <controlPort> <output.json> [featureId ...]
"""
from __future__ import annotations

import json
import socket
import sys
import time

PROTOCOL = "sixmic-analysis"
VERSION = 1
HEAD_WORDS = 64


class Control:
    def __init__(self, host: str, port: int) -> None:
        self.sock = socket.create_connection((host, int(port)), timeout=20)
        self.file = self.sock.makefile("rwb")
        self.counter = 0
        self.session = ""

    def close(self) -> None:
        try:
            self.file.close()
        finally:
            self.sock.close()

    def request(self, op: str, args: dict | None = None) -> dict:
        self.counter += 1
        payload = {"protocol": PROTOCOL, "version": VERSION,
                   "requestId": str(self.counter), "op": op,
                   "args": dict(args or {})}
        if self.session:
            payload["sessionId"] = self.session
        self.file.write((json.dumps(payload) + "\n").encode("utf-8"))
        self.file.flush()
        while True:
            line = self.file.readline()
            if not line:
                raise RuntimeError("gateway closed the control connection")
            message = json.loads(line)
            if str(message.get("requestId")) != str(self.counter):
                continue  # notification line
            if message.get("status") == "error":
                raise RuntimeError(json.dumps({"op": op,
                                               "error": message.get("error")}))
            result = message.get("result")
            return result if isinstance(result, dict) else {}

    def hello(self) -> dict:
        result = self.request("hello", {"clientName": "echo-pc-capture",
                                        "clientVersion": "1",
                                        "maxBinaryPayloadBytes": 1048576})
        self.session = str(result.get("sessionId") or "")
        return result

    def claim(self) -> str:
        result = self.request("control.claim", {"leaseSeconds": 60})
        return str(result.get("controlToken") or "")


def list_catalog(control: Control) -> list[dict]:
    pages: list[dict] = []
    cursor: object = 0
    seen: set = set()
    while cursor is not None:
        if cursor in seen:
            raise RuntimeError("catalog cursor repeated")
        seen.add(cursor)
        page = control.request("feature.list", {"cursor": cursor, "limit": 8})
        pages.append(page)
        cursor = page.get("nextCursor")
    return pages


def fetch_result(control: Control, job_id: str) -> dict:
    offset, schema, first = 0, None, None
    head: list[int] = []
    total = 0
    pages = 0
    while True:
        page = control.request("feature.result", {"jobId": job_id,
                                                  "offsetWords": offset,
                                                  "maxWords": 1024})
        if first is None:
            first = {key: page.get(key) for key in
                     ("jobId", "featureId", "state", "sourceKind",
                      "configuration", "totalWords")}
            schema = page.get("schema")
            total = int(page.get("totalWords") or 0)
        words = page.get("words") or []
        if len(head) < HEAD_WORDS:
            head.extend(int(word) for word in words[:HEAD_WORDS - len(head)])
        offset += len(words)
        pages += 1
        if not page.get("more"):
            break
        if pages > 20000:
            raise RuntimeError("result pagination runaway")
    return {"jobId": first["jobId"], "featureId": first["featureId"],
            "state": first["state"], "sourceKind": first["sourceKind"],
            "configuration": first["configuration"],
            "totalWords": total, "pages": pages, "schema": schema,
            "head_u32": head}


def run_feature(control: Control, token: str, feature_id: str,
                params: dict | None = None, *, timeout: float = 60.0) -> dict:
    started = control.request("feature.start",
                              {"featureId": feature_id,
                               "params": dict(params or {}),
                               "controlToken": token})
    job_id = str(started.get("jobId") or "")
    if not job_id:
        raise RuntimeError("no jobId for " + feature_id)
    deadline = time.monotonic() + timeout
    interval = 0.1
    while time.monotonic() < deadline:
        status = control.request("feature.get", {"jobId": job_id})
        state = str(status.get("state") or "")
        if state == "completed":
            return {"start": started, "get": status,
                    "result": fetch_result(control, job_id)}
        if state in ("failed", "canceled"):
            return {"start": started, "get": status, "result": None}
        time.sleep(min(interval, 0.5))
        interval = min(2.0, interval * 1.5)
    raise TimeoutError("feature timed out: " + feature_id)


def main() -> int:
    control_port = int(sys.argv[1])
    output = sys.argv[2]
    requested = sys.argv[3:]
    control = Control("127.0.0.1", control_port)
    captured: dict = {"capturedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                      "transport": "real TCP 127.0.0.1 control port",
                      "server": "ps/build/host/test-feature-server.exe",
                      "registry": "registry/INTERFACE_REGISTRY.json",
                      "sourceKind": "test-fixture", "hardwareState": "NOT_TESTED",
                      "note": "deterministic fixture gateway; not hardware, not "
                              "acoustic acceptance; values are fixture constants",
                      "features": {}}
    try:
        hello = control.hello()
        captured["hello"] = hello
        token = control.claim()
        pages = list_catalog(control)
        captured["catalog"] = {
            "pages": pages,
            "pageSizes": [len(page.get("features") or []) for page in pages],
            "total": sum(len(page.get("features") or []) for page in pages),
            "version": pages[0].get("version") if pages else "",
        }
        captured["capabilities"] = control.request("capabilities.get", {})
        cases = requested or [
            "levels_core", "fft", "psd", "stft", "octave", "csd", "io_pcm",
            "frequency_time_weighting", "level_statistics", "noise_rating",
            "spectral_kurtosis", "full_das", "room_decay",
        ]
        for feature_id in cases:
            try:
                if feature_id == "io_pcm":
                    outcome = run_feature(control, token, "io_pcm",
                                          {"samples": 4096, "channels": 6,
                                           "channel": 0})
                elif feature_id == "frequency_time_weighting":
                    outcome = run_feature(control, token, feature_id,
                                          {"weighting": "A", "timeResponse": False})
                elif feature_id == "noise_rating":
                    outcome = run_feature(control, token, feature_id,
                                          {"family": "NR", "channel": 0,
                                           "referenceConfirmed": True,
                                           "referenceOffsetDb": 0,
                                           "calibrationSource": "capture nominal"})
                elif feature_id == "room_decay":
                    outcome = run_feature(control, token, feature_id,
                                          {"stimulus": "clap", "channel": 0})
                elif feature_id in ("stft",):
                    outcome = run_feature(control, token, feature_id,
                                          {"frames": 4, "channel": 0})
                else:
                    outcome = run_feature(control, token, feature_id, {})
                captured["features"][feature_id] = outcome
                print("captured", feature_id,
                      (outcome.get("result") or {}).get("totalWords"))
            except Exception as exc:  # noqa: BLE001 - keep the survey going
                captured["features"][feature_id] = {"exception": str(exc)[:400]}
                print("capture-failed", feature_id, str(exc)[:160])
        # reference flows (need a completed reference job first)
        try:
            reference = run_feature(control, token, "relative_insulation",
                                    {"action": "reference", "channel": 0})
            captured["features"]["relative_insulation_reference"] = reference
            ref_id = str((reference.get("result") or {}).get("jobId")
                         or (reference.get("start") or {}).get("jobId") or "")
            measure = run_feature(control, token, "relative_insulation",
                                  {"action": "measure", "channel": 0,
                                   "referenceJobId": ref_id, "confirmed": True})
            captured["features"]["relative_insulation_measure"] = measure
            print("captured relative_insulation reference+measure")
        except Exception as exc:  # noqa: BLE001
            captured["features"]["relative_insulation_measure"] = {
                "exception": str(exc)[:400]}
            print("capture-failed relative_insulation", str(exc)[:160])
        try:
            reference = run_feature(control, token, "spectrum_freeze",
                                    {"action": "reference", "channel": 0})
            captured["features"]["spectrum_freeze_reference"] = reference
            ref_id = str((reference.get("result") or {}).get("jobId")
                         or (reference.get("start") or {}).get("jobId") or "")
            compare = run_feature(control, token, "spectrum_freeze",
                                  {"action": "compare", "channel": 0,
                                   "referenceJobId": ref_id})
            captured["features"]["spectrum_freeze_compare"] = compare
            print("captured spectrum_freeze reference+compare")
        except Exception as exc:  # noqa: BLE001
            captured["features"]["spectrum_freeze_compare"] = {
                "exception": str(exc)[:400]}
            print("capture-failed spectrum_freeze", str(exc)[:160])
    finally:
        control.close()
    with open(output, "w", encoding="utf-8") as handle:
        json.dump(captured, handle, ensure_ascii=False, indent=1)
    print("wrote", output, "features:", len(captured.get("features") or {}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
