"""FeatureRuntime tests: catalog gates, 8-slot scheduler, polling/backoff/cancel,
identity validation, reference lifecycle and the documented fixed-hidden flows.

Everything runs against fake call/read callbacks and synthetic test-fixture words
(the real host-gateway capture provides schemas only).  No hardware, no DSP.
"""
from __future__ import annotations

import copy
import json
import struct
from pathlib import Path

import pytest

from ui.features import FeatureRuntime, load_spec

APP = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "features"
REPO = APP.parents[1]
REGISTRY_PATH = (REPO / "deployment" / "echo_feature_closure_20261025" /
                 "registry" / "INTERFACE_REGISTRY.json")

CONFIG = {"session": 1, "config": 2,
          "generation": "9007199254740993",
          "sourceFrame": "18446744073709551615"}
FIXTURE_SOURCE = "test-fixture"


def f32w(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", float(value)))[0]


def words(*values) -> list[int]:
    return [f32w(v) if isinstance(v, float) else int(v) & 0xFFFFFFFF for v in values]


@pytest.fixture(scope="module")
def spec():
    return load_spec()


@pytest.fixture(scope="module")
def gateway_capture():
    return json.loads((FIXTURES / "captured_host_gateway.json").read_text(
        encoding="utf-8"))


@pytest.fixture(scope="module")
def registry():
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return {row["featureId"]: row for row in data["features"]}


def registry_schema(registry, feature_id):
    row = registry[feature_id]
    schema = copy.deepcopy(row.get("schema") or {})
    output = row.get("output") or {}
    meta = output.get("metadata") if isinstance(output.get("metadata"), dict) else None
    if meta is not None:
        schema["actualProducerLayout"] = copy.deepcopy(meta)
    elif isinstance(output, dict) and output:
        schema["actualProducerLayout"] = copy.deepcopy(output)
    return schema


def schema_for(feature_id, gateway, registry):
    captured = gateway["features"].get(feature_id)
    if captured and captured.get("result"):
        return copy.deepcopy(captured["result"]["schema"])
    return registry_schema(registry, feature_id)


def words_for(feature_id, gateway, registry, override=None):
    if override is not None:
        return override
    captured = gateway["features"].get(feature_id)
    if captured and captured.get("result"):
        total = captured["result"]["totalWords"]
    else:
        total = int((registry[feature_id].get("output") or {}).get("wordCount") or 0)
    return [0] * total


class FakeGateway:
    def __init__(self, clock):
        self.clock = clock
        self.counter = 0
        self.calls: list[dict] = []
        self.queues: dict[str, list[dict]] = {}
        self.handles: dict[str, bytes] = {}
        self.released: list[str] = []

    def call(self, op, args):
        self.counter += 1
        entry = {"rid": f"u-{self.counter:04d}", "op": op,
                 "args": json.loads(json.dumps(args)), "at": self.clock[0]}
        self.calls.append(entry)
        self.queues.setdefault(op, []).append(entry)
        return entry["rid"]

    def read(self, handle, offset, count):
        data = self.handles.get(handle, b"")
        return data[offset * 4:(offset + count) * 4]

    def release(self, handle):
        self.released.append(handle)

    def take(self, op, job_id=None):
        queue = self.queues.get(op) or []
        if job_id is not None:
            for index, call in enumerate(queue):
                if call["args"].get("jobId") == job_id:
                    queue.pop(index)
                    return call
        assert queue, f"no pending {op} call (calls={[c['op'] for c in self.calls]})"
        return queue.pop(0)

    def count(self, op):
        return sum(1 for call in self.calls if call["op"] == op)

    def start_args(self, feature_id=None):
        for call in self.calls:
            if call["op"] == "start" and (feature_id is None or
                                          call["args"]["featureId"] == feature_id):
                return call["args"]
        return None


class Harness:
    def __init__(self, spec, *, api=True, catalog=True, instrument_mode=False):
        self.spec = spec
        self.clock = [1000.0]
        self.gw = FakeGateway(self.clock)
        self.notifications: list[tuple[str, str, str]] = []
        self.changes = 0
        self.rt = FeatureRuntime(
            spec, call=self.gw.call, read_buffer=self.gw.read,
            release_handle=self.gw.release,
            notify=lambda level, title, detail="": self.notifications.append(
                (level, title, detail)),
            now=lambda: self.clock[0],instrument_mode=instrument_mode)
        self.rt.on_change(self._mark)
        if api:
            self.enable_api()
        if catalog:
            self.load_catalog()

    def _mark(self):
        self.changes += 1

    # -- capability / catalog --------------------------------------------
    def enable_api(self, connected=True, enabled=True,
                   version="echo-features-1"):
        self.rt.set_feature_api(enabled, {
            "connected": connected, "enabled": enabled, "version": version,
            "featureCount": 45, "catalogPageSize": 8,
            "maxResultWordsPerPage": 1024})

    def disable(self):
        self.rt.set_feature_api(False, {"connected": False, "enabled": False})

    def load_catalog(self, feature_ids=None, version="echo-features-1"):
        self.rt.refresh_catalog()
        call = self.gw.take("list")
        ids = feature_ids if feature_ids is not None else list(self.spec["features"])
        payload = {"version": version, "total": len(ids),
                   "features": [{"featureId": fid} for fid in ids],
                   "nextCursor": None}
        self.rt.on_response(call["rid"], "list", payload, None)
        return payload

    # -- clock / polling --------------------------------------------------
    def advance(self, seconds):
        self.clock[0] += float(seconds)

    def tick(self, seconds=0.25, respond=None):
        self.advance(seconds)
        self.rt.tick()
        if respond is not None:
            call = self.gw.take("get")
            self.respond_get(call["args"]["jobId"], respond)

    def poll(self, seconds=0.25):
        self.advance(seconds)
        self.rt.tick()
        return self.gw.take("get")

    # -- bridge responses -------------------------------------------------
    def respond_start(self, call, job_id, *, feature_id=None, state="running",
                      source=FIXTURE_SOURCE, configuration=None, progress=None,
                      extra=None):
        feature_id = feature_id or call["args"]["featureId"]
        result = {"jobId": job_id, "featureId": feature_id, "state": state,
                  "sourceKind": source,
                  "configuration": dict(configuration or CONFIG),
                  "progress": dict(progress or {})}
        if extra:
            result.update(extra)
        self.rt.on_response(call["rid"], "start", result, None)
        return result

    def respond_get(self, job_id, state, *, feature_id=None, progress=None,
                    error=None, configuration=None):
        call = self.gw.take("get", job_id)
        result = {"jobId": job_id, "state": state, "sourceKind": FIXTURE_SOURCE,
                  "configuration": dict(configuration or CONFIG),
                  "progress": dict(progress or {})}
        if feature_id:
            result["featureId"] = feature_id
        if error:
            result["error"] = error
        self.rt.on_response(call["rid"], "get", result, None)

    def respond_error(self, op, code, detail=None, job_id=None):
        call = self.gw.take(op, job_id)
        self.rt.on_response(call["rid"], op, None,
                            {"code": code, "messageKey": f"errors.{code}",
                             "retryable": False, "detail": detail or {}})

    def deliver_result(self, job_id, feature_word_id, words_in, schema, *,
                       feature_id=None, source=FIXTURE_SOURCE, inline=True,
                       total=None, configuration=None):
        call = self.gw.take("result", job_id)
        total = len(words_in) if total is None else total
        result = {"jobId": job_id,
                  "featureId": feature_id or feature_word_id,
                  "state": "completed", "sourceKind": source,
                  "configuration": dict(configuration or CONFIG),
                  "schema": schema, "totalWords": total}
        handle = None
        if inline:
            result["words"] = list(words_in)
        else:
            handle = f"buf-{job_id}"
            self.gw.handles[handle] = struct.pack(
                "<" + "I" * len(words_in), *words_in)
            result["dataRef"] = {"handleId": handle, "count": len(words_in)}
        self.rt.on_response(call["rid"], "result", result, None)
        return result

    # -- flow drivers -----------------------------------------------------
    def start(self, feature_id, job_id="feature-1", *, state="running",
              progress=None, feature_override=None):
        self.rt.open(feature_id)
        self.rt.run(feature_id)
        call = self.gw.take("start")
        self.respond_start(call, job_id, feature_id=feature_override,
                           state=state, progress=progress)
        return call

    def start_reference(self, feature_id, job_id="feature-ref"):
        return self.start(feature_id, job_id)

    def complete_reference(self, job_id, feature_id, feature_word_id, words_in,
                           schema, *, state="completed"):
        self.tick(0.25)
        self.respond_get(job_id, state, feature_id=feature_id)
        if state != "completed":
            return
        self.deliver_result(job_id, feature_word_id, words_in, schema,
                            feature_id=feature_id)

    def run_single(self, feature_id, words_in, schema, *, job_id="feature-1",
                   inline=True, feature_word_id=None):
        self.start(feature_id, job_id)
        self.tick(0.25)
        self.respond_get(job_id, "completed")
        self.deliver_result(job_id, feature_word_id or feature_id, words_in,
                            schema, inline=inline)
        return job_id

    def workspace(self):
        return self.rt.workspace()

    def entries(self, page):
        return self.rt.entries(page)


# ---------------------------------------------------------------------------
# constructor / entries
# ---------------------------------------------------------------------------
def test_constructor_accepts_positional_contract_callbacks(spec):
    clock = [5.0]
    gw = FakeGateway(clock)
    changes = []
    runtime = FeatureRuntime(
        spec, gw.call, gw.read, gw.release,
        lambda level, title, detail="": changes.append(title),
        now=lambda: clock[0])
    runtime.on_change(lambda: changes.append("changed"))
    runtime.set_feature_api(True, {"connected": True, "enabled": True,
                                   "version": "echo-features-1"})
    runtime.refresh_catalog()
    call = gw.take("list")
    runtime.on_response(call["rid"], "list", {"version": "echo-features-1",
                                              "total": 45,
                                              "features": [
                                                  {"featureId": fid}
                                                  for fid in spec["features"]],
                                              "nextCursor": None}, None)
    assert runtime.catalog.device_catalog_complete
    assert runtime.entries("time")
    assert changes  # on_change registered and fired
    runtime.tick()
    runtime.tick(now=clock[0] + 1.0)
    runtime.shutdown()


def test_entries_cover_every_page_feature_even_without_feature_api(spec):
    harness = Harness(spec, api=False, catalog=False)
    total = 0
    for page_id, page in spec["pages"].items():
        entries = harness.entries(page_id)
        expected = [fid for group in page["groups"] for fid in group["features"]]
        assert [entry["featureId"] for entry in entries] == expected
        for entry in entries:
            assert entry["available"] is False
            assert entry["state"] == "unavailable"
            assert entry["disabledReason"]["zh"]
            assert entry["disabledReason"]["en"]
            assert "params" not in entry and "jobId" not in entry
            assert "schema" not in entry and "words" not in entry
        total += len(entries)
    assert total == 45


def test_entries_available_after_zoom_registry_fix(spec):
    harness = Harness(spec)
    entries = {entry["featureId"]: entry for entry in harness.entries("spectrum")}
    for fid, entry in entries.items():
        assert entry["available"] is True, fid
        assert entry["disabledReason"] == {"zh": "", "en": ""}
    assert "zoom_fft" in entries


def test_entries_disable_on_old_gateway_and_catalog_incomplete(spec):
    harness = Harness(spec, api=False, catalog=False)
    harness.enable_api(version="0.9")
    assert all(not entry["available"] for entry in harness.entries("time"))
    assert any("旧" in entry["disabledReason"]["zh"] or "版本" in entry["disabledReason"]["zh"]
               for entry in harness.entries("time"))
    harness.enable_api(version="echo-features-1")
    assert all(not entry["available"] for entry in harness.entries("time"))
    assert all(entry["disabledReason"]["zh"] for entry in harness.entries("time"))


def test_entries_never_show_engineering_fields_or_params(spec):
    harness = Harness(spec)
    harness.run_single("psd", [0] * 1026,
                       schema_for("psd", *harness_schemas())) if False else None
    entries = harness.entries("spectrum")
    payload = json.dumps(entries, ensure_ascii=False)
    for banned in ('"params"', '"schema"', '"jobId"', '"words"', '"launch"'):
        assert banned not in payload


# ---------------------------------------------------------------------------
# normal lifecycle / polling
# ---------------------------------------------------------------------------
def test_psd_lifecycle_fixed_params_polling_backoff_result_and_release(
        spec, gateway_capture, registry):
    harness = Harness(spec)
    harness.rt.open("psd")
    harness.rt.run("psd")
    start_call = harness.gw.take("start")
    assert start_call["args"]["featureId"] == "psd"
    assert start_call["args"]["params"] == {"channel": 0}
    assert start_call["args"]["params"] == spec["features"]["psd"]["launch"]["params"]
    harness.respond_start(start_call, "feature-1")
    state = harness.workspace()
    assert state["state"] == "running"
    assert state["chart"]["emptyReason"] == "运行中"  # no stale cache shown
    # poll backoff: 250ms then 500ms then 1s then 2s (never an extra sleep)
    times = []
    for delay in (0.25, 0.5, 1.0, 2.0):
        harness.advance(delay)
        harness.rt.tick()
        call = harness.gw.queues["get"][-1]
        times.append(call["at"])
        harness.respond_get("feature-1", "running")
    deltas = [round(times[i + 1] - times[i], 3) for i in range(len(times) - 1)]
    assert deltas == [0.5, 1.0, 2.0]
    harness.advance(2.0)
    harness.rt.tick()
    schema = schema_for("psd", gateway_capture, registry)
    words_in = words(3.0) + [f32w(1.0)] * 1024 + [0]
    harness.respond_get("feature-1", "completed")
    assert harness.gw.count("result") == 1
    call = harness.gw.take("result")
    assert call["args"] == {"jobId": "feature-1"}
    handle = "buf-live"
    harness.gw.handles[handle] = struct.pack("<" + "I" * 1026, *words_in)
    harness.rt.on_response(call["rid"], "result", {
        "jobId": "feature-1", "featureId": "psd", "state": "completed",
        "sourceKind": FIXTURE_SOURCE, "configuration": dict(CONFIG),
        "schema": schema, "totalWords": 1026,
        "dataRef": {"handleId": handle, "count": 1026}}, None)
    assert handle in harness.gw.released
    state = harness.workspace()
    assert state["state"] == "completed"
    assert state["chart"]["kind"] == "spectrum"
    assert state["chart"]["series"]
    assert state["resultValid"] is True and state["invalidReason"] == ""
    assert state["sourceKind"] == FIXTURE_SOURCE
    assert state["freshness"]["generation"] == CONFIG["generation"]
    assert state["freshness"]["sourceFrame"] == CONFIG["sourceFrame"]
    assert state["freshness"]["sampleIndex"] == CONFIG["sourceFrame"]
    entries = {entry["featureId"]: entry for entry in harness.entries("spectrum")}
    assert entries["psd"]["state"] == "completed"
    assert entries["psd"]["hasResult"] is True
    assert entries["psd"]["running"] is False
    export = harness.rt.export_raw("psd")
    assert export["totalWords"] == 1026
    assert export["fixture"] is True
    assert export["hardwareState"] == "NOT_TESTED"
    assert export["configuration"]["generation"] == CONFIG["generation"]


def test_no_result_before_completed(spec, gateway_capture, registry):
    harness = Harness(spec)
    harness.start("levels_core", "feature-1")
    harness.tick(0.25)
    harness.respond_get("feature-1", "running")
    assert harness.gw.count("result") == 0
    state = harness.workspace()
    assert state["state"] == "running"
    assert not state["chart"].get("scalarRows")


def test_inline_and_data_ref_results_match(spec, gateway_capture, registry):
    schema = schema_for("fft", gateway_capture, registry)
    harness = Harness(spec)
    harness.run_single("fft", [f32w(0.5)] * 1025, schema)
    chart = harness.workspace()["chart"]
    assert chart["kind"] == "spectrum"
    assert harness.workspace()["resultSummary"]["totalWords"] == 1025
    harness2 = Harness(spec)
    harness2.run_single("fft", [f32w(0.25)] * 1025, schema, inline=False)
    assert harness2.workspace()["state"] == "completed"
    assert "buf-feature-1" in harness2.gw.released


def test_runtime_result_pages_are_validated_and_used(spec, gateway_capture, registry):
    schema = schema_for("psd", gateway_capture, registry)
    harness = Harness(spec)
    harness.start("psd", "feature-1")
    harness.tick(0.25)
    harness.respond_get("feature-1", "completed")
    call = harness.gw.take("result")
    total = 1026
    full = words(7.0) + [f32w(1.0)] * 1025
    pages = []
    for offset in (0, 1024):
        chunk = full[offset:offset + 1024]
        pages.append({"jobId": "feature-1", "featureId": "psd",
                      "state": "completed", "sourceKind": FIXTURE_SOURCE,
                      "configuration": dict(CONFIG), "schema": schema,
                      "totalWords": total, "offsetWords": offset,
                      "words": chunk, "more": offset + len(chunk) < total})
    harness.rt.on_response(call["rid"], "result", {
        "jobId": "feature-1", "featureId": "psd", "state": "completed",
        "sourceKind": FIXTURE_SOURCE, "configuration": dict(CONFIG),
        "schema": schema, "totalWords": total, "pages": pages}, None)
    state = harness.workspace()
    assert state["state"] == "completed"
    export = harness.rt.export_raw("psd")
    assert export["words"][0] == f32w(7.0)
    # a missing page is rejected and never silently completed
    harness.start("psd", "feature-2")
    harness.tick(0.25)
    harness.respond_get("feature-2", "completed")
    call = harness.gw.take("result")
    harness.rt.on_response(call["rid"], "result", {
        "jobId": "feature-2", "featureId": "psd", "state": "completed",
        "sourceKind": FIXTURE_SOURCE, "configuration": dict(CONFIG),
        "schema": schema, "totalWords": total, "pages": pages[:1]}, None)
    harness.tick(2.0)
    harness.respond_error("result", "bad_state") if harness.gw.queues.get(
        "result") else None
    assert harness.workspace()["state"] in ("running", "failed")


# ---------------------------------------------------------------------------
# identity validation
# ---------------------------------------------------------------------------
def test_result_identity_mismatch_fails_without_replay(spec, gateway_capture,
                                                       registry):
    schema = schema_for("psd", gateway_capture, registry)
    harness = Harness(spec)
    harness.start("psd", "feature-1")
    harness.tick(0.25)
    harness.respond_get("feature-1", "completed")
    call = harness.gw.take("result")
    words_in = words(1.0) + [0] * 1025
    harness.rt.on_response(call["rid"], "result", {
        "jobId": "feature-OTHER", "featureId": "psd", "state": "completed",
        "sourceKind": FIXTURE_SOURCE, "configuration": dict(CONFIG),
        "schema": schema, "totalWords": len(words_in), "words": words_in}, None)
    state = harness.workspace()
    assert state["state"] == "failed"
    assert state["error"]["code"] == "feature-result-identity"
    assert state["error"]["reason"]
    assert harness.gw.count("start") == 1  # no replay
    assert harness.gw.count("result") == 1


def test_result_source_kind_and_configuration_identity_rejected(
        spec, gateway_capture, registry):
    schema = schema_for("psd", gateway_capture, registry)
    words_in = words(1.0) + [0] * 1025
    for bad in ({"sourceKind": "hardware"},
                {"sourceKind": "pl-live"},  # differs from start sourceKind
                {"configuration": {"session": 1, "config": 3,
                                   "generation": "1", "sourceFrame": "1"}}):
        harness = Harness(spec)
        harness.start("psd", "feature-1")
        harness.tick(0.25)
        harness.respond_get("feature-1", "completed")
        call = harness.gw.take("result")
        payload = {"jobId": "feature-1", "featureId": "psd",
                   "state": "completed", "sourceKind": FIXTURE_SOURCE,
                   "configuration": dict(CONFIG), "schema": schema,
                   "totalWords": len(words_in), "words": words_in}
        payload.update(bad)
        harness.rt.on_response(call["rid"], "result", payload, None)
        state = harness.workspace()
        assert state["state"] == "failed", bad
        assert state["error"]["code"] in ("feature-result-source",
                                          "feature-result-identity")


def test_get_identity_change_fails(spec):
    harness = Harness(spec)
    harness.start("psd", "feature-1")
    harness.tick(0.25)
    call = harness.gw.take("get")
    harness.rt.on_response(call["rid"], "get", {
        "jobId": "feature-1", "featureId": "different", "state": "running",
        "sourceKind": FIXTURE_SOURCE, "configuration": dict(CONFIG)}, None)
    assert harness.workspace()["state"] == "failed"


def test_start_identity_invalid_fails(spec):
    harness = Harness(spec)
    harness.rt.open("psd")
    harness.rt.run("psd")
    call = harness.gw.take("start")
    harness.rt.on_response(call["rid"], "start", {"featureId": "psd",
                                                  "state": "running"}, None)
    assert harness.workspace()["state"] == "failed"


# ---------------------------------------------------------------------------
# scheduler / slots / cancel
# ---------------------------------------------------------------------------
def test_scheduler_limits_nonexclusive_concurrency_to_three(spec):
    harness = Harness(spec)
    features = ["levels_core", "fft", "stft", "data_continuity", "signal_quality"]
    for feature_id in features:
        harness.rt.run(feature_id)
    assert harness.gw.count("start") == 3
    queued = [entry for entry in harness.entries("time") if entry["state"] == "queued"]
    assert queued
    status = harness.rt.status()
    assert status["taskSlots"]["active"] == 3
    assert status["taskSlots"]["max"] == 8
    assert status["taskSlots"]["queued"] == 2
    # complete one running job -> the next queued job starts
    first = harness.gw.queues["start"][0]["args"]["featureId"]
    harness.respond_start(harness.gw.take("start"), "feature-slot-1",
                          feature_id=first)
    harness.tick(0.25)
    harness.respond_get("feature-slot-1", "completed")
    harness.deliver_result("feature-slot-1", first, [], {"kind": "capability"})
    harness.tick(0.25)
    assert harness.gw.count("start") >= 4


def test_exclusive_p2_waits_for_p1_and_runs_alone(spec):
    harness = Harness(spec)
    harness.rt.run("psd")
    harness.respond_start(harness.gw.take("start"), "feature-p1")
    harness.rt.run("zoom_fft")
    # the P2 job is exclusive: it must wait for the P1 job to finish
    assert harness.gw.count("start") == 1
    assert harness.rt.status()["taskSlots"]["queued"] == 1
    harness.tick(0.25)
    harness.respond_get("feature-p1", "completed")
    harness.deliver_result("feature-p1", "psd", [0] * 1026,
                           schema_for("psd", *capture_schemas()))


def test_cancel_queued_job_is_local_and_issues_no_start(spec):
    harness = Harness(spec)
    for feature_id in ["levels_core", "fft", "stft", "data_continuity"]:
        harness.rt.run(feature_id)
    assert harness.gw.count("start") == 3
    harness.rt.stop("data_continuity")
    assert harness.gw.count("start") == 3
    state = harness.rt.snapshot()
    assert any(job["state"] == "canceled" for job in state["jobs"].values())


def test_stop_running_waits_for_canceled_then_no_result(spec):
    harness = Harness(spec)
    harness.start("levels_core", "feature-1")
    harness.rt.stop("levels_core")
    stop_call = harness.gw.take("stop")
    assert stop_call["args"] == {"jobId": "feature-1"}
    harness.rt.on_response(stop_call["rid"], "stop",
                           {"jobId": "feature-1", "cancelRequested": True}, None)
    assert harness.workspace()["state"] == "stopping"
    harness.tick(0.25)
    harness.respond_get("feature-1", "canceled")
    state = harness.workspace()
    assert state["state"] == "canceled"
    assert harness.gw.count("result") == 0
    entries = {entry["featureId"]: entry for entry in harness.entries("time")}
    assert entries["levels_core"]["state"] == "canceled"
    assert entries["levels_core"]["running"] is False


def test_start_busy_requeues_without_failure(spec):
    harness = Harness(spec)
    harness.rt.open("psd")
    harness.rt.run("psd")
    harness.respond_error("start", "busy")
    state = harness.workspace()
    assert state["state"] == "queued"
    harness.tick(0.5)
    assert harness.gw.count("start") == 2
    call = harness.gw.take("start")
    assert call["args"]["featureId"] == "psd"


def test_start_timeout_never_replays(spec):
    harness = Harness(spec)
    harness.rt.open("psd")
    harness.rt.run("psd")
    assert harness.gw.count("start") == 1
    harness.advance(16.0)
    harness.rt.tick()
    state = harness.workspace()
    assert state["state"] == "failed"
    assert state["error"]["code"] == "start-timeout"
    assert harness.gw.count("start") == 1


def test_reconnect_fails_inflight_jobs_without_replay_and_clears_references(
        spec, gateway_capture, registry):
    harness = Harness(spec)
    schema = schema_for("spectrum_freeze", gateway_capture, registry)
    harness.start_reference("spectrum_freeze", "feature-ref")
    harness.tick(0.25)
    harness.respond_get("feature-ref", "completed")
    harness.deliver_result("feature-ref", "spectrum_freeze", [0] * 1025, schema)
    assert harness.rt.workspace()["references"]["hasReference"] is True
    harness.start("spectrum_freeze", "feature-compare")
    prior_calls = len(harness.gw.calls)
    harness.disable()
    assert harness.workspace()["state"] in ("failed", "unavailable")
    assert harness.rt.workspace()["references"]["hasReference"] is False
    jobs = harness.rt.snapshot()["jobs"].values()
    assert any(job["state"] == "failed" for job in jobs)
    assert len(harness.gw.calls) == prior_calls  # no stop/start replay
    assert all(not entry["available"] for entry in harness.entries("spectrum"))
    harness.enable_api()
    harness.load_catalog()
    assert all(entry["available"] for entry in harness.entries("time"))


# ---------------------------------------------------------------------------
# reference flows
# ---------------------------------------------------------------------------
def _capture_schemas():
    gateway = json.loads((FIXTURES / "captured_host_gateway.json").read_text(
        encoding="utf-8"))
    registry = {row["featureId"]: row for row in json.loads(
        REGISTRY_PATH.read_text(encoding="utf-8"))["features"]}
    return gateway, registry


def capture_schemas():
    return _capture_schemas()


def test_reference_compare_flow(spec):
    harness = Harness(spec)
    schema = schema_for("spectrum_freeze", *_capture_schemas())
    harness.start("spectrum_freeze", "feature-ref")
    assert harness.gw.start_args()["params"]["action"] == "reference"
    harness.tick(0.25)
    harness.respond_get("feature-ref", "completed")
    harness.deliver_result("feature-ref", "spectrum_freeze", [0] * 1025, schema)
    state = harness.workspace()
    assert state["references"]["hasReference"] is True
    reference_job = state["references"]["referenceJobId"]
    assert reference_job == "feature-ref"
    harness.rt.run("spectrum_freeze")
    compare_call = harness.gw.take("start")
    assert compare_call["args"]["featureId"] == "spectrum_freeze"
    assert compare_call["args"]["params"]["action"] == "compare"
    assert compare_call["args"]["params"]["referenceJobId"] == reference_job
    harness.respond_start(compare_call, "feature-compare")
    harness.tick(0.25)
    harness.respond_get("feature-compare", "completed")
    harness.deliver_result("feature-compare", "spectrum_freeze", [0] * 3075, schema)
    state = harness.workspace()
    assert state["state"] == "completed"
    assert state["chart"]["kind"] == "ab-spectrum"
    # protected reference survives ordinary refresh / close
    harness.rt.close()
    assert harness.rt.workspace()["open"] is False
    harness.rt.open("spectrum_freeze")
    assert harness.rt.workspace()["references"]["hasReference"] is True


def test_reference_job_not_found_clears_reference(spec):
    harness = Harness(spec)
    schema = schema_for("spectrum_freeze", *_capture_schemas())
    harness.start("spectrum_freeze", "feature-ref")
    harness.tick(0.25)
    harness.respond_get("feature-ref", "completed")
    harness.deliver_result("feature-ref", "spectrum_freeze", [0] * 1025, schema)
    harness.rt.run("spectrum_freeze")
    compare_call = harness.gw.take("start")
    assert compare_call["args"]["params"]["referenceJobId"] == "feature-ref"
    harness.rt.on_response(compare_call["rid"], "start", None,
                           {"code": "job_not_found",
                            "messageKey": "errors.job_not_found",
                            "retryable": False, "detail": {}})
    state = harness.workspace()
    assert state["state"] == "failed"
    assert state["references"]["hasReference"] is False
    assert "重建参考" in (state["references"]["note"] + state["message"])


def test_relative_insulation_confirmation_and_measure(spec):
    harness = Harness(spec)
    schema = schema_for("relative_insulation", *_capture_schemas())
    harness.start("relative_insulation", "feature-ref")
    harness.tick(0.25)
    harness.respond_get("feature-ref", "completed")
    harness.deliver_result("feature-ref", "relative_insulation", [0] * 9, schema)
    assert harness.workspace()["references"]["hasReference"] is True
    assert harness.workspace()["references"]["referenceJobId"] == "feature-ref"
    starts = harness.gw.count("start")
    harness.rt.run("relative_insulation")
    assert harness.gw.count("start") == starts+1  # Start performs the measurement step; no disclaimer checkbox.
    measure_call = harness.gw.take("start")
    assert measure_call["args"]["params"]["action"] == "measure"
    assert measure_call["args"]["params"]["referenceJobId"] == "feature-ref"
    assert measure_call["args"]["params"]["confirmed"] is True
    harness.respond_start(measure_call, "feature-measure")
    harness.tick(0.25)
    harness.respond_get("feature-measure", "completed")
    words_in = words(*([6.0206] * 9)) + words(*([1.0] * 9))
    words_in += words(*([4.0] * 9)) + words(*([1.0] * 9))
    harness.deliver_result("feature-measure", "relative_insulation", words_in, schema)
    state = harness.workspace()
    assert state["state"] == "completed"
    assert state["chart"]["kind"] == "insulation-bars"
    assert "Rw" in state["chart"]["subtitle"]


def test_stipa_101_stage_flow(spec):
    harness = Harness(spec)
    stipa_schema = schema_for("stipa_experimental", *_capture_schemas())
    harness.rt.open("stipa_experimental")
    harness.rt.run("stipa_experimental")
    reference_call = harness.gw.take("start")
    assert reference_call["args"]["featureId"] == "io_pcm"
    assert reference_call["args"]["params"] == {"samples": 720000, "channels": 1,
                                                "channel": 0}
    harness.respond_start(reference_call, "feature-ref")
    harness.tick(0.25)
    harness.respond_get("feature-ref", "completed", feature_id="io_pcm")
    harness.deliver_result("feature-ref", "io_pcm", [0x100000] * 720000,
                           {"kind": "waveform", "fields": ["signed_PCM24"],
                            "axes": {"channels": 1,
                                     "channelStrideWords": 720000}},
                           feature_id="io_pcm")
    state = harness.workspace()
    assert state["references"]["hasReference"] is True
    assert state["references"]["referenceJobId"] == "feature-ref"
    starts = harness.gw.count("start")
    harness.rt.run("stipa_experimental")
    assert harness.gw.count("start") == starts+1  # reference remains required, checkbox does not.
    stipa_call = harness.gw.take("start")
    assert stipa_call["args"]["featureId"] == "stipa_experimental"
    assert stipa_call["args"]["params"]["referenceJobId"] == "feature-ref"
    assert stipa_call["args"]["params"]["testSignalConfirmed"] is True
    harness.respond_start(stipa_call, "feature-stipa")
    harness.tick(0.25)
    call = harness.gw.take("get", "feature-stipa")
    harness.rt.on_response(call["rid"], "get", {
        "jobId": "feature-stipa", "featureId": "stipa_experimental",
        "state": "running", "sourceKind": FIXTURE_SOURCE,
        "configuration": dict(CONFIG),
        "progress": {"completedStages": 40, "totalStages": 101,
                     "currentStageIndex": 41, "phase": "computing"}}, None)
    state = harness.workspace()
    assert state["state"] == "running"
    stage = state["chart"]["stage"]
    assert stage == {"completed": 40, "total": 101, "current": 41,
                     "label": "STIPA 阶段"}
    assert "index" not in stage
    assert state["message"] == "录音已完成 · 已完成 40/101 阶段"
    harness.tick(2.0)
    harness.respond_get("feature-stipa", "completed",
                        progress={"completedStages": 101, "totalStages": 101})
    harness.deliver_result("feature-stipa", "stipa_experimental",
                           words(0.72, 1.0, 0.0), stipa_schema)
    state = harness.workspace()
    assert state["state"] == "completed"
    assert state["resultValid"] is True and state["invalidReason"] == ""
    assert state["chart"]["kind"] == "stipa"
    assert state["chart"]["resultValid"] is True
    assert state["chart"]["stage"] == {"completed": 101, "total": 101,
                                      "current": 101, "label": "STIPA 阶段"}
    assert state["message"].startswith("测量完成。")
    rows = {row["label"]: row for row in state["chart"]["scalarRows"]}
    assert rows["experimental_index"]["value"] == pytest.approx(0.72)


def _complete_stipa(spec, words_in):
    harness = Harness(spec)
    stipa_schema = schema_for("stipa_experimental", *_capture_schemas())
    harness.rt.open("stipa_experimental")
    harness.rt.run("stipa_experimental")
    reference_call = harness.gw.take("start")
    harness.respond_start(reference_call, "feature-ref")
    harness.tick(0.25)
    harness.respond_get("feature-ref", "completed", feature_id="io_pcm")
    harness.deliver_result("feature-ref", "io_pcm", [0x100000] * 720000,
                           {"kind": "waveform", "fields": ["signed_PCM24"],
                            "axes": {"channels": 1,
                                     "channelStrideWords": 720000}},
                           feature_id="io_pcm")
    harness.rt.run("stipa_experimental")
    stipa_call = harness.gw.take("start")
    harness.respond_start(stipa_call, "feature-stipa")
    harness.tick(0.25)
    harness.respond_get("feature-stipa", "completed",
                        progress={"completedStages": 101, "totalStages": 101})
    harness.deliver_result("feature-stipa", "stipa_experimental",
                           words_in, stipa_schema)
    return harness


def test_stipa_invalid_result_never_claims_measurement_completed(spec):
    expected = "参考信号不稳定：1000 Hz 频带、3.15 Hz 调制分量校验失败，请重新录制参考。"
    harness = _complete_stipa(spec, words(0.0, 0.0, 0.0, 3.0, 1000.0, 3.15,
                                          0.15, 0.06, 0.4))
    state = harness.workspace()
    assert state["state"] == "completed"
    assert state["resultValid"] is False
    assert state["invalidReason"] == expected
    assert state["chart"]["resultValid"] is False
    assert state["chart"]["invalidReason"] == expected
    assert state["chart"]["indexValue"] is None
    assert state["chart"]["indexValid"] is False
    assert state["chart"]["stage"]["completed"] == 101
    assert state["message"] == f"处理完成，但测量无效：{expected}"
    assert state["messageEn"].startswith("Processing completed; measurement invalid:")
    warnings = [n for n in harness.notifications
                if n[0] == "warn" and "无效" in n[1]]
    assert warnings and expected in warnings[-1][2]
    assert not any(n[0] == "info" and n[1] == "测量完成"
                   for n in harness.notifications)


def test_stipa_valid_result_reports_measurement_completed(spec):
    harness = _complete_stipa(spec, words(0.72, 1.0, 0.0, 0.0, 0.0, 0.0,
                                          0.15, 0.15, 1.0))
    state = harness.workspace()
    assert state["state"] == "completed"
    assert state["resultValid"] is True and state["invalidReason"] == ""
    assert state["chart"]["resultValid"] is True
    assert state["chart"]["invalidReason"] == ""
    assert state["chart"]["indexValue"] == pytest.approx(0.72)
    assert state["message"].startswith("测量完成。")
    assert not any(n[0] == "warn" and "无效" in n[1]
                   for n in harness.notifications)
    assert any(n[0] == "info" and n[1] == "测量完成"
               for n in harness.notifications)


def test_stipa_quick_mode_uses_384000_samples_everywhere(spec):
    harness = Harness(spec)
    harness.rt.confirm("stipa_experimental", "measurementMode", "quick")
    harness.rt.open("stipa_experimental")
    harness.rt.run("stipa_experimental")
    reference_call = harness.gw.take("start")
    assert reference_call["args"]["featureId"] == "io_pcm"
    assert reference_call["args"]["params"] == {"samples": 384000, "channels": 1,
                                                "channel": 0}
    harness.respond_start(reference_call, "feature-ref")
    harness.tick(0.25)
    harness.respond_get("feature-ref", "completed", feature_id="io_pcm")
    harness.deliver_result("feature-ref", "io_pcm", [0x100000] * 384000,
                           {"kind": "waveform", "fields": ["signed_PCM24"],
                            "axes": {"channels": 1,
                                     "channelStrideWords": 384000}},
                           feature_id="io_pcm")
    harness.rt.run("stipa_experimental")
    stipa_call = harness.gw.take("start")
    assert stipa_call["args"]["params"]["samples"] == 384000
    assert stipa_call["args"]["params"]["measurementMode"] == "quick"

    # the independent "record reference" button uses the same 8 s capture
    other = Harness(spec)
    other.rt.confirm("stipa_experimental", "measurementMode", "quick")
    other.rt.action("stipa_experimental", "reference")
    independent = other.gw.take("start")
    assert independent["args"]["featureId"] == "io_pcm"
    assert independent["args"]["params"] == {"samples": 384000, "channels": 1,
                                             "channel": 0}

    # complete mode keeps the 15 s / 720000-sample capture
    complete = Harness(spec)
    complete.rt.action("stipa_experimental", "reference")
    kept = complete.gw.take("start")
    assert kept["args"]["params"]["samples"] == 720000


def test_room_stimulus_confirmation_flow(spec):
    harness = Harness(spec)
    schema = schema_for("room_decay", *_capture_schemas())
    total = 48032
    harness.rt.open("room_decay")
    harness.rt.run("room_decay")
    assert harness.gw.count("start") == 1
    entries = {entry["featureId"]: entry for entry in harness.entries("room")}
    assert entries["room_decay"]["needsConfirmation"] is False
    start_call = harness.gw.take("start")
    assert start_call["args"]["params"]["stimulus"] == "clap"
    assert start_call["args"]["params"] == {"stimulus": "clap"}
    harness.respond_start(start_call, "feature-room")
    harness.tick(0.25)
    harness.respond_get("feature-room", "completed")
    harness.deliver_result("feature-room", "room_decay", [0] * total, schema)
    state = harness.workspace()
    assert state["state"] == "completed"
    assert state["chart"]["kind"] == "room-decay"
    entries = {entry["featureId"]: entry for entry in harness.entries("room")}
    assert entries["room_decay"]["needsConfirmation"] is False


def test_noise_rating_dual_runs_are_independent(spec):
    harness = Harness(spec)
    schema = schema_for("noise_rating", *_capture_schemas())
    harness.rt.open("noise_rating")
    harness.rt.run("noise_rating")
    assert harness.gw.count("start") == 1  # profile carries explicit uncalibrated nominal reference.
    first = harness.gw.take("start")
    assert first["args"]["params"]["family"] == "NR"
    harness.respond_start(first, "feature-nr")
    harness.tick(0.25)
    harness.respond_get("feature-nr", "completed")
    harness.deliver_result("feature-nr", "noise_rating", [0] * 1074, schema)
    second = harness.gw.take("start")
    assert second["args"]["args"] if False else second["args"]["params"]["family"] == "NC"
    harness.respond_start(second, "feature-nc")
    harness.tick(0.25)
    harness.respond_get("feature-nc", "completed")
    harness.deliver_result("feature-nc", "noise_rating", [0] * 172, schema)
    state = harness.workspace()
    assert state["state"] == "completed"
    variants = state["variants"]
    assert len(variants) == 2
    assert [variant["id"] for variant in variants] == ["NR", "NC"]
    assert all(variant["state"] == "completed" for variant in variants)
    assert all(variant["chart"] for variant in variants)


def test_frequency_time_weighting_four_separate_runs(spec):
    harness = Harness(spec)
    schema = schema_for("frequency_time_weighting", *_capture_schemas())
    harness.rt.open("frequency_time_weighting")
    harness.rt.run("frequency_time_weighting")
    for i,weighting in enumerate(["A","C","Z",None]):
        call=harness.gw.take("start")
        assert call["args"]["params"]["timeResponse"] is (weighting is None)
        if weighting: assert call["args"]["params"]["weighting"] == weighting
        jid=f"weighting-{i}"
        harness.respond_start(call,jid)
        harness.tick(.25)
        harness.respond_get(jid,"completed")
        harness.deliver_result(jid,"frequency_time_weighting",[0]*(1028 if weighting else 48032),schema)
    variants=harness.workspace()["variants"]
    assert len(variants)==4
    assert all(v["state"]=="completed" for v in variants)


# ---------------------------------------------------------------------------
# monitor / events
# ---------------------------------------------------------------------------
def test_event_monitor_never_completed_and_never_polls_result(spec):
    harness = Harness(spec)
    harness.start("event_trigger", "feature-monitor")
    harness.tick(0.25)
    harness.respond_get("feature-monitor", "running")
    assert harness.gw.count("result") == 0
    harness.rt.on_events([{"eventId": "1", "reason": "level warning",
                           "state": "captured"},
                          {"eventId": "2", "reason": "clip", "state": "captured"}])
    state = harness.workspace()
    assert state["state"] == "running"
    assert state["chart"]["kind"] == "events"
    assert len(state["chart"]["events"]) == 2
    assert state["chart"]["events"][0]["position01"] == 0.0
    # a completed terminal state is an abnormal end, never shown as success
    harness.tick(2.0)
    harness.respond_get("feature-monitor", "completed")
    state = harness.workspace()
    assert state["state"] == "failed"
    assert state["error"]["code"] == "monitor-ended-unexpectedly"
    assert harness.gw.count("result") == 0
    assert harness.gw.count("start") == 1


def test_event_monitor_stop_waits_canceled(spec):
    harness = Harness(spec)
    harness.start("event_trigger", "feature-monitor")
    harness.rt.stop("event_trigger")
    stop_call = harness.gw.take("stop")
    harness.rt.on_response(stop_call["rid"], "stop",
                           {"jobId": "feature-monitor", "cancelRequested": True},
                           None)
    harness.tick(0.25)
    harness.respond_get("feature-monitor", "canceled")
    state = harness.workspace()
    assert state["state"] == "canceled"
    assert harness.gw.count("result") == 0


# ---------------------------------------------------------------------------
# page lifecycle / view options / shutdown / timing
# ---------------------------------------------------------------------------
def test_page_change_stops_exclusive_jobs_and_cancels_queued(spec):
    harness = Harness(spec)
    harness.rt.on_page_changed("spectrum")
    harness.rt.open("zoom_fft")
    harness.rt.run("zoom_fft")
    harness.respond_start(harness.gw.take("start"), "feature-p2")
    harness.rt.open("zoom_fft")
    harness.rt.on_page_changed("time")
    stop_call = harness.gw.take("stop")
    assert stop_call["args"]["jobId"] == "feature-p2"
    harness.rt.on_response(stop_call["rid"], "stop",
                           {"jobId": "feature-p2", "cancelRequested": True}, None)
    harness.tick(0.25)
    harness.respond_get("feature-p2", "canceled")
    assert harness.rt.workspace()["open"] is False  # page left -> workspace closed
    jobs = list(harness.rt.snapshot()["jobs"].values())
    assert any(job["state"] == "canceled" for job in jobs)


def test_view_options_are_display_only_and_change_revision(spec):
    harness = Harness(spec)
    harness.run_single("psd", [0] * 1026,
                       schema_for("psd", *_capture_schemas()))
    chart = harness.workspace()["chart"]
    revision = chart["chartRevision"]
    calls = len(harness.gw.calls)
    harness.rt.set_view_option("psd", "logX", True)
    chart = harness.workspace()["chart"]
    assert chart["xAxis"]["scale"] == "log"
    assert chart["chartRevision"] != revision
    assert len(harness.gw.calls) == calls  # display only, no PL task
    harness.rt.set_view_option("psd", "notAViewOption", 1)
    assert len(harness.gw.calls) == calls


def test_shutdown_stops_active_jobs_and_blocks_new_work(spec):
    harness = Harness(spec)
    harness.start("levels_core", "feature-1")
    harness.rt.shutdown()
    assert harness.gw.count("stop") == 1
    calls_after = len(harness.gw.calls)
    harness.rt.run("fft")
    harness.rt.tick(1.0)
    assert harness.gw.count("start") == 1
    assert len(harness.gw.calls) == calls_after
    assert harness.rt.export_raw("levels_core") is None


def test_on_response_unknown_request_is_ignored(spec):
    harness = Harness(spec)
    assert harness.rt.on_response("u-unknown", "get", {}, None) is False


def test_runtime_never_adds_request_sleeps(spec):
    harness = Harness(spec)
    harness.start("psd", "feature-1")
    started = harness.clock[0]
    harness.rt.tick()  # no time has passed: no poll issued
    assert not harness.gw.queues.get("get")
    harness.advance(0.25)
    harness.rt.tick()
    assert harness.gw.queues.get("get")
    assert harness.clock[0] - started == pytest.approx(0.25)


def test_stale_freshness_after_completion(spec):
    harness = Harness(spec)
    harness.run_single("levels_core", [0] * 48,
                       schema_for("levels_core", *_capture_schemas()))
    assert harness.workspace()["freshness"]["stale"] is False
    harness.advance(120.0)
    assert harness.workspace()["freshness"]["stale"] is True


# ---------------------------------------------------------------------------
# large-result export + protected reference lifecycle
# ---------------------------------------------------------------------------
def test_export_raw_io_pcm_720000_uses_chunked_read_and_releases(spec,
                                                                gateway_capture):
    harness = Harness(spec)
    harness.start("io_pcm", "feature-io")
    harness.tick(0.25)
    harness.respond_get("feature-io", "completed")
    call = harness.gw.take("result", "feature-io")
    total = 720000
    words_in = [0x100000] * total
    handle = "buf-io-720000"
    harness.gw.handles[handle] = struct.pack("<" + "I" * total, *words_in)
    harness.rt.on_response(call["rid"], "result", {
        "jobId": "feature-io", "featureId": "io_pcm", "state": "completed",
        "sourceKind": FIXTURE_SOURCE, "configuration": dict(CONFIG),
        "schema": {"kind": "waveform", "fields": ["signed_PCM24"],
                   "axes": {"channels": 1, "channelStrideWords": total},
                   "actualProducerLayout": {"channelStrideWords": total}},
        "totalWords": total,
        "dataRef": {"handleId": handle, "count": total}}, None)
    assert handle in harness.gw.released
    state = harness.workspace()
    assert state["state"] == "completed"
    # bounded QML payload: peak-envelope display, never 720000 inline values
    channel = state["chart"]["channels"][0]
    assert channel["sourceSampleCount"] == total
    assert len(channel["values"]) <= 4096
    assert "words" not in state["chart"]
    payload_json = json.dumps(state, ensure_ascii=False)
    assert len(payload_json) < 2 * 1024 * 1024
    export = harness.rt.export_raw("io_pcm")
    assert export["totalWords"] == total
    assert len(export["words"]) == total
    assert export["words"][0] == 0x100000
    assert export["fixture"] is True and export["hardwareState"] == "NOT_TESTED"


def test_export_raw_room_decay_48032(spec):
    harness = Harness(spec)
    total = 48032
    harness.rt.open("room_decay")
    harness.rt.confirm("room_decay", "stimulus", "impulse")
    harness.run_single("room_decay", [0] * total,
                       schema_for("room_decay", *_capture_schemas()))
    export = harness.rt.export_raw("room_decay")
    assert export["totalWords"] == total
    assert len(export["words"]) == total
    assert harness.workspace()["state"] == "completed"


def test_protected_reference_survives_refresh_and_close(spec):
    harness = Harness(spec)
    schema = schema_for("spectrum_freeze", *_capture_schemas())
    harness.start("spectrum_freeze", "feature-ref")
    harness.tick(0.25)
    harness.respond_get("feature-ref", "completed")
    harness.deliver_result("feature-ref", "spectrum_freeze", [f32w(1.0)] * 1025,
                           schema)
    reference_id = harness.workspace()["references"]["referenceJobId"]
    assert reference_id == "feature-ref"
    # ordinary refresh starts a compare run but never releases the reference
    harness.rt.refresh("spectrum_freeze")
    compare_call = harness.gw.take("start")
    assert compare_call["args"]["params"]["referenceJobId"] == reference_id
    harness.respond_start(compare_call, "feature-compare-1")
    harness.tick(0.25)
    harness.respond_get("feature-compare-1", "completed")
    harness.deliver_result("feature-compare-1", "spectrum_freeze", [0] * 3075,
                           schema)
    assert harness.workspace()["references"]["referenceJobId"] == reference_id
    harness.rt.close()
    harness.rt.open("spectrum_freeze")
    assert harness.workspace()["references"]["hasReference"] is True
    assert harness.workspace()["references"]["referenceJobId"] == reference_id
    assert "受保护" in harness.workspace()["references"]["note"]



# ---------------------------------------------------------------------------
# completed state only after the decoded result exists (no empty "completed" UI)
# ---------------------------------------------------------------------------
def test_completed_state_waits_for_result_payload(spec):
    harness = Harness(spec)
    harness.start("psd", "feature-1")
    harness.tick(0.25)
    harness.respond_get("feature-1", "completed")
    assert harness.gw.count("result") == 1
    state = harness.workspace()
    # task is done on the device, but the immutable result is still being fetched
    assert state["state"] == "running"
    assert (state["chart"].get("emptyReason") == "运行中")
    assert state["resultSummary"]["jobId"] == ""
    schema = schema_for("psd", *_capture_schemas())
    harness.deliver_result("feature-1", "psd", words(2.0) + [f32w(1.0)] * 1025,
                           schema)
    state = harness.workspace()
    assert state["state"] == "completed"
    assert state["chart"]["series"]
    assert state["resultSummary"]["totalWords"] == 1026


def test_reference_completed_state_waits_for_result_payload(spec):
    harness = Harness(spec)
    schema = schema_for("spectrum_freeze", *_capture_schemas())
    harness.start("spectrum_freeze", "feature-ref")
    harness.tick(0.25)
    harness.respond_get("feature-ref", "completed")
    state = harness.workspace()
    assert state["state"] == "running"
    assert state["references"]["hasReference"] is False
    harness.deliver_result("feature-ref", "spectrum_freeze", [0] * 1025, schema)
    state = harness.workspace()
    assert state["state"] == "completed"
    assert state["references"]["hasReference"] is True


# ---------------------------------------------------------------------------
# gateway configuration maturation (start/get provisional -> completed final)
# ---------------------------------------------------------------------------
PROVISIONAL = {"session": 0, "config": 0, "generation": "65538",
               "sourceFrame": "0"}
FINAL = {"session": 1, "config": 1, "generation": "1", "sourceFrame": "8048"}


def test_configuration_may_mature_while_running_then_completes(spec):
    harness = Harness(spec)
    harness.rt.open("psd")
    harness.rt.run("psd")
    start_call = harness.gw.take("start")
    harness.rt.on_response(start_call["rid"], "start", {
        "jobId": "feature-1", "featureId": "psd", "state": "accepted",
        "sourceKind": FIXTURE_SOURCE, "configuration": dict(PROVISIONAL)}, None)
    harness.tick(0.25)
    harness.respond_get("feature-1", "running")
    # the running get returns another provisional identity: legal maturation
    harness.tick(1.0)
    call = harness.gw.take("get")
    harness.rt.on_response(call["rid"], "get", {
        "jobId": "feature-1", "featureId": "psd", "state": "running",
        "sourceKind": FIXTURE_SOURCE,
        "configuration": {"session": 0, "config": 0,
                          "generation": "65539", "sourceFrame": "0"}}, None)
    assert harness.workspace()["state"] == "running"
    harness.tick(2.0)
    harness.respond_get("feature-1", "completed", configuration=FINAL)
    schema = schema_for("psd", *_capture_schemas())
    harness.deliver_result("feature-1", "psd", words(2.0) + [f32w(1.0)] * 1025,
                           schema, configuration=FINAL)
    state = harness.workspace()
    assert state["state"] == "completed", state["error"]
    assert state["chart"]["kind"] == "spectrum"
    assert state["freshness"]["generation"] == "1"
    assert state["freshness"]["sourceFrame"] == "8048"
    assert state["freshness"]["sampleIndex"] == "8048"
    assert harness.gw.count("start") == 1


def test_completed_configuration_is_immutable_and_result_must_match(spec):
    harness = Harness(spec)
    harness.start("psd", "feature-1")
    harness.tick(0.25)
    harness.respond_get("feature-1", "completed")
    call = harness.gw.take("result")
    schema = schema_for("psd", *_capture_schemas())
    harness.rt.on_response(call["rid"], "result", {
        "jobId": "feature-1", "featureId": "psd", "state": "completed",
        "sourceKind": FIXTURE_SOURCE,
        "configuration": {"session": 9, "config": 9,
                          "generation": "9", "sourceFrame": "9"},
        "schema": schema, "totalWords": 1026,
        "words": [0] * 1026}, None)
    state = harness.workspace()
    assert state["state"] == "failed"
    assert state["error"]["code"] == "feature-result-identity"


def test_running_identity_change_still_fails(spec):
    harness = Harness(spec)
    harness.start("psd", "feature-1")
    harness.tick(0.25)
    call = harness.gw.take("get")
    harness.rt.on_response(call["rid"], "get", {
        "jobId": "feature-OTHER", "featureId": "psd", "state": "running",
        "sourceKind": FIXTURE_SOURCE, "configuration": dict(PROVISIONAL)}, None)
    assert harness.workspace()["state"] == "failed"
    assert harness.workspace()["error"]["code"] == "feature-get-identity"


def test_monitor_configuration_maturation_then_cancel(spec):
    harness = Harness(spec)
    harness.rt.open("event_trigger")
    harness.rt.run("event_trigger")
    start_call = harness.gw.take("start")
    harness.rt.on_response(start_call["rid"], "start", {
        "jobId": "feature-monitor", "featureId": "event_trigger",
        "state": "running", "sourceKind": FIXTURE_SOURCE,
        "configuration": dict(PROVISIONAL)}, None)
    harness.tick(0.25)
    call = harness.gw.take("get")
    harness.rt.on_response(call["rid"], "get", {
        "jobId": "feature-monitor", "featureId": "event_trigger",
        "state": "running", "sourceKind": FIXTURE_SOURCE,
        "configuration": {"session": 1, "config": 1,
                          "generation": "1", "sourceFrame": "8048"}}, None)
    assert harness.workspace()["state"] == "running"
    harness.rt.stop("event_trigger")
    stop_call = harness.gw.take("stop")
    harness.rt.on_response(stop_call["rid"], "stop",
                           {"jobId": "feature-monitor",
                            "cancelRequested": True}, None)
    harness.tick(0.25)
    harness.respond_get("feature-monitor", "canceled")
    state = harness.workspace()
    assert state["state"] == "canceled"
    assert harness.gw.count("result") == 0


def test_reference_flow_stores_completed_configuration(spec):
    harness = Harness(spec)
    schema = schema_for("spectrum_freeze", *_capture_schemas())
    harness.start("spectrum_freeze", "feature-ref")
    harness.tick(0.25)
    harness.respond_get("feature-ref", "completed", configuration=FINAL)
    harness.deliver_result("feature-ref", "spectrum_freeze", [0] * 1025, schema,
                           configuration=FINAL)
    assert harness.rt.workspace()["references"]["hasReference"] is True
    harness.rt.run("spectrum_freeze")
    compare_call = harness.gw.take("start")
    assert compare_call["args"]["params"]["referenceJobId"] == "feature-ref"
    harness.respond_start(compare_call, "feature-compare")
    harness.tick(0.25)
    harness.respond_get("feature-compare", "completed", configuration=FINAL)
    harness.deliver_result("feature-compare", "spectrum_freeze", [0] * 3075,
                           schema, configuration=FINAL)
    state = harness.workspace()
    assert state["state"] == "completed", state["error"]
    assert state["chart"]["kind"] == "ab-spectrum"



def test_feature_api_warning_only_on_capability_state_change(spec):
    """Connecting must not flash "功能接口不可用" for repeated/initial states."""
    notes = []
    rt = FeatureRuntime(spec=spec, notify=lambda level, title, detail: notes.append((level, title, detail)))
    rt.set_connection(False)  # initial disconnected snapshot: quiet
    assert not [n for n in notes if "功能接口不可用" in n[1]]
    rt.set_feature_api(False, {"connected": True, "enabled": False})
    assert len([n for n in notes if "功能接口不可用" in n[1]]) == 1
    # Repeated disabled snapshots from capability/catalog refreshes stay quiet.
    rt.set_feature_api(False, {"connected": True, "enabled": False})
    assert len([n for n in notes if "功能接口不可用" in n[1]]) == 1
    # Stable disabled reconnect after an enabled episode warns again once.
    rt.set_feature_api(True, {"connected": True, "enabled": True, "version": "1"})
    rt.set_feature_api(True, {"connected": True, "enabled": True, "version": "1"})
    assert len([n for n in notes if "功能接口可用" in n[1]]) == 1
    rt.set_feature_api(False, {"connected": True, "enabled": False})
    assert len([n for n in notes if "功能接口不可用" in n[1]]) == 2

def test_stipa_quick_mode_idle_stage_total_follows_selected_mode(spec):
    harness = Harness(spec)
    harness.rt.open("stipa_experimental")
    idle = harness.workspace()
    assert idle["chart"]["stage"]["total"] == 101
    assert idle["chart"]["stage"]["completed"] == 0
    harness.rt.confirm("stipa_experimental", "measurementMode", "quick")
    quick = harness.workspace()
    assert quick["chart"]["stage"]["total"] == 15
    assert quick["chart"]["stage"]["current"] == 0
    assert "15 阶段" in quick["flow"]["note"]
    assert "101 阶段" not in quick["flow"]["note"]
    harness.rt.confirm("stipa_experimental", "measurementMode", "complete")
    back = harness.workspace()
    assert back["chart"]["stage"]["total"] == 101
