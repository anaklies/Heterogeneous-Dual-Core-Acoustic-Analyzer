"""Lead-owned facade contract tests (runtime injected as a fake)."""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = APP_ROOT / "ui" / "config" / "feature_view_spec.json"


class FakeRuntime:
    instances: list["FakeRuntime"] = []

    def __init__(self, spec, *, call, read_buffer, release_handle, notify, **kwargs):
        self.spec = spec
        self.call = call
        self.read_buffer = read_buffer
        self.release_handle = release_handle
        self.notify = notify
        self.change_cb = None
        self.calls: list[tuple] = []
        self.responses: list[tuple] = []
        self.api = (False, {})
        self.catalog_requests = 0
        self.workspace_payload = {
            "open": True, "featureId": "psd", "name": "Welch PSD",
            "shortZh": "Welch PSD", "shortEn": "PSD", "icon": "chart-line",
            "page": "spectrum", "tier": "P0", "mode": "p1", "state": "completed",
            "lifecycle": "ready", "message": "ok", "error": None,
            "available": True, "disabledReason": "", "elapsedMs": 321,
            "sourceKind": "test-fixture",
            "validity": "requires fresh PL DONE", "units": "FS squared/Hz",
            "notes": ["note"], "provenance": ["from host fixture"],
            "params": {"channel": 0}, "paramForm": [{"key": "channel"}],
            "resultSummary": {"jobId": "feature-1", "totalWords": 1026,
                              "schemaKind": "tensor", "units": "FS squared/Hz"},
            "freshness": {"sampleIndex": "123", "generation": "9",
                          "sourceFrame": "12", "capturedAt": "2026-10-26T00:00:00",
                          "stale": False},
            "references": {"referenceJobId": "", "hasReference": False,
                           "compatible": True, "note": ""},
            "flow": {"kind": "single", "step": 0, "steps": ["采集"],
                     "note": "",
                     "actions": [{"id": "run", "labelZh": "开始", "labelEn": "Run",
                                  "icon": "play", "enabled": True,
                                  "reason": {"zh": "", "en": ""}, "tone": "primary"},
                                 {"id": "save", "labelZh": "保存", "labelEn": "Save",
                                  "icon": "save", "enabled": True,
                                  "reason": {"zh": "无结果", "en": "No result"},
                                  "tone": "secondary"}],
                     "confirmations": [{"id": "referenceConfirmed", "type": "bool",
                                        "labelZh": "参考确认", "labelEn": "Reference",
                                        "value": False, "required": True,
                                        "enabled": True, "reason": {"zh": "", "en": ""},
                                        "options": []}]},
            "variants": [{"id": "default", "labelZh": "默认", "labelEn": "Default",
                          "state": "completed",
                          "chart": {"kind": "capability", "chartRevision": "3",
                                    "title": "变体", "emptyReason": ""}}],
            "chart": {
                "kind": "stft", "chartRevision": "7", "title": "STFT",
                "subtitle": "", "units": "FS squared/Hz",
                "xAxis": {"min": 0, "max": 1, "scale": "linear", "label": "",
                          "unit": "s"},
                "yAxis": {"min": 20, "max": 20000, "scale": "log", "label": "",
                          "unit": "Hz"},
                "series": [], "categories": [],
                "colorScale": {"min": 0, "max": 1, "palette": "viridis",
                               "label": "", "unit": ""},
                "markers": [], "referenceLines": [], "referenceBands": [],
                "frames": [{"time": 0.0, "points": [[100.0, 1.0]]}],
                "scalarRows": [], "text": "", "emptyReason": "",
                "raster": {"matrix": [[0.0, 0.5], [1.0, 0.25]],
                           "palette": "viridis", "min": 0.0, "max": 1.0},
            },
        }
        FakeRuntime.instances.append(self)

    def on_change(self, callback):
        self.change_cb = callback

    def set_feature_api(self, enabled, info):
        self.api = (bool(enabled), dict(info))

    def refresh_catalog(self):
        self.catalog_requests += 1

    def entries(self, page):
        features = [item for item in self.spec["features"].values()
                    if item.get("page") == page]
        return [{"featureId": item["featureId"], "shortZh": item["shortZh"],
                 "shortEn": item["shortEn"], "name": item["name"],
                 "nameEn": item["nameEn"], "icon": item["icon"],
                 "tier": item["tier"], "mode": item["mode"], "page": page,
                 "group": item["group"], "state": "idle",
                 "available": self.api[0], "hasResult": False, "running": False,
                 "needsConfirmation": bool((item.get("launch") or {}).get(
                     "confirmation")),
                 "disabledReason": {"zh": "设备软件需要更新",
                                    "en": "Device software update required"}}
                for item in features]

    def workspace(self):
        return json.loads(json.dumps(self.workspace_payload))

    def status(self):
        return {"apiVersion": "echo-features-1" if self.api[0] else "",
                "featureApiEnabled": self.api[0], "featureCount": 45,
                "catalogComplete": self.api[0], "sourceKind": "test-fixture",
                "taskSlots": {"active": 0, "max": 8}, "queueDepth": 0}

    def open(self, feature_id):
        self.calls.append(("open", feature_id))

    def close(self):
        self.calls.append(("close",))

    def run(self, feature_id):
        self.calls.append(("run", feature_id))

    def stop(self, feature_id):
        self.calls.append(("stop", feature_id))

    def refresh(self, feature_id):
        self.calls.append(("refresh", feature_id))

    def confirm(self, feature_id, key, value):
        self.calls.append(("confirm", feature_id, key, value))

    def action(self, feature_id, action_id):
        self.calls.append(("action", feature_id, action_id))

    def set_view_option(self, feature_id, key, value):
        self.calls.append(("view", feature_id, key, value))

    def on_page_changed(self, page_id):
        self.calls.append(("page", page_id))

    def tick(self):
        self.calls.append(("tick",))

    def export_raw(self, feature_id):
        self.calls.append(("export", feature_id))
        return {"featureId": feature_id, "jobId": "feature-1", "words": [1, 2, 3],
                "totalWords": 3, "sourceKind": "test-fixture", "schema": {},
                "configuration": {}}

    def on_response(self, request_id, op, result, error):
        self.responses.append((request_id, op, result, error))

    def shutdown(self):
        self.calls.append(("shutdown",))


class FakeBridge:
    def __init__(self):
        self.requests: list[tuple] = []
        self.buffer = b"" + bytes(range(16))

    def _id(self, op):
        request_id = f"ui-{len(self.requests) + 1:08d}"
        self.requests.append((request_id, op))
        return request_id

    def listFeatures(self):
        return self._id("listFeatures")

    def startFeature(self, feature_id, params_json):
        assert json.loads(params_json) == {} or isinstance(json.loads(params_json), dict)
        return self._id("startFeature")

    def stopFeature(self, job_id):
        return self._id("stopFeature")

    def getFeature(self, job_id):
        return self._id("getFeature")

    def getFeatureResult(self, job_id):
        return self._id("getFeatureResult")

    def releaseFeatureResult(self, handle_id):
        return self._id("releaseFeatureResult")

    def readBuffer(self, handle_id, offset, count):
        return self.buffer


def _install_fake_runtime(monkeypatch):
    module = types.ModuleType("ui.features")
    module.FeatureRuntime = FakeRuntime
    monkeypatch.setitem(sys.modules, "ui.features", module)


def _install_missing_runtime(monkeypatch):
    # A module without FeatureRuntime => the facade degrades explicitly.
    monkeypatch.setitem(sys.modules, "ui.features", types.ModuleType("ui.features"))


def _facade(monkeypatch, qapp):
    from ui.viewmodels.feature_workspace import FeatureWorkspaceFacade
    from ui.viewmodels.plot_images import PlotImageProvider
    bridge = FakeBridge()
    images = PlotImageProvider()
    language = {"value": "zh"}
    facade = FeatureWorkspaceFacade(SPEC_PATH, bridge, images,
                                    language=lambda: language["value"])
    return facade, bridge, images, language


def test_spec_pages_cover_45_unique_features():
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    assert spec["interfaceVersion"] == "echo-features-1"
    features = spec["features"]
    assert len(features) == 45
    seen: list[str] = []
    for page_id, page in spec["pages"].items():
        for group in page["groups"]:
            assert group["features"], page_id
            seen.extend(group["features"])
    assert len(seen) == 45
    assert len(set(seen)) == 45
    for feature_id, item in features.items():
        assert item["launch"]["policy"] == "fixed-hidden"
        assert item["launch"]["userEditable"] is False
        assert item["icon"] and item["shortZh"] and item["shortEn"]
        assert item["chart"] in {
            "spectrum", "zoom-spectrum", "bands", "stft", "das-map",
            "pair-spectra", "coherence-phase", "lag-series", "beam-spectrum",
            "room-decay", "room-clarity", "spectral-decay", "insulation-bars",
            "stipa", "statistics", "weighting", "noise-rating", "ab-spectrum",
            "level-bars", "waveform", "scalars", "capability", "events",
            "harmonic-bars",
        }


def test_degrades_explicitly_without_runtime(monkeypatch, qapp):
    _install_missing_runtime(monkeypatch)
    facade, _bridge, _images, _lang = _facade(monkeypatch, qapp)
    total = 0
    for page_id in ("time", "spectrum", "bands", "periodic", "multichannel",
                    "events", "room"):
        entries = facade.entries(page_id)
        total += len(entries)
        assert all(entry["available"] is False for entry in entries)
        assert all(entry["disabledReason"] for entry in entries)
    assert total == 45
    status = facade.status()
    assert status["connected"] is False
    workspace = facade.workspace()
    assert workspace["open"] is False
    assert workspace["chart"]["kind"] == "capability"


def test_feature_api_missing_disables_entries(monkeypatch, qapp):
    _install_fake_runtime(monkeypatch)
    facade, _bridge, _images, _lang = _facade(monkeypatch, qapp)
    facade.set_connection(True, {"enabled": False, "reason": "feature-api-missing"})
    status = facade.status()
    assert status["connected"] is True
    assert status["featureApiEnabled"] is False
    assert "设备软件" in status["deviceSoftwareNote"]
    entries = facade.entries("spectrum")
    assert all(entry["available"] is False for entry in entries)
    assert sum(len(facade.entries(page)) for page in (
        "time", "spectrum", "bands", "periodic", "multichannel", 
        "events", "room")) == 45


def test_enabled_api_catalogs_runs_and_localizes(monkeypatch, qapp):
    _install_fake_runtime(monkeypatch)
    facade, bridge, images, language = _facade(monkeypatch, qapp)
    runtime = FakeRuntime.instances[-1]
    facade.set_connection(True, {"enabled": True, "version": "1",
                                 "featureCount": 45})
    assert runtime.catalog_requests == 1
    entries = facade.entries("spectrum")
    assert [entry["featureId"] for entry in entries][:2] == ["fft", "psd"]
    assert entries[0]["shortName"] == "FFT幅度谱"
    assert entries[0]["units"]
    assert entries[0]["prerequisitesText"]
    # entries must not leak editable parameters
    assert all("params" not in entry for entry in entries)

    groups = facade.page_groups("spectrum")
    # The prompt's logical category is the only visible group on a page.
    assert [group["label"] for group in groups] == ["频谱及比较"]
    assert [len(group["features"]) for group in groups] == [9]

    facade.open("psd")
    facade.run("psd")
    facade.stop("psd")
    facade.refresh("psd")
    facade.confirm("noise_rating", "referenceConfirmed", True)
    facade.action("psd", "run")
    facade.set_view_option("psd", "logX", False)
    facade.page_changed("spectrum")
    facade.tick()
    assert ("open", "psd") in runtime.calls
    assert ("run", "psd") in runtime.calls
    assert ("confirm", "noise_rating", "referenceConfirmed", True) in runtime.calls
    assert ("view", "psd", "logX", False) in runtime.calls
    assert ("page", "spectrum") in runtime.calls

    workspace = facade.workspace()
    assert workspace["stateLabel"] == "已完成"
    assert workspace["sourceLabel"] == "测试数据（非实测）"
    assert "params" not in workspace and "paramForm" not in workspace
    assert workspace["chart"]["imageUrl"].startswith("image://plots/psd/")
    assert workspace["flow"]["actions"][0]["label"] == "开始"
    assert workspace["flow"]["actions"][1]["reason"] == "无结果"
    assert workspace["flow"]["confirmations"][0]["label"] == "参考确认"
    assert workspace["variants"][0]["chart"]["title"] == "变体"

    language["value"] = "en"
    workspace_en = facade.workspace()
    assert workspace_en["stateLabel"] == "Completed"
    assert workspace_en["flow"]["actions"][0]["label"] == "Run"
    entries_en = facade.entries("spectrum")
    assert entries_en[0]["shortName"] == "FFT"

    # Bridge call adapter: request ids are registered and responses routed.
    request_id = facade._call("start", {"featureId": "psd", "params": {}})
    _, op = bridge.requests[-1]
    assert op == "startFeature"
    assert facade.on_response(request_id, {"jobId": "feature-1"}, None) is True
    assert runtime.responses[-1][1] == "start"
    assert facade.on_response("missing-id", {}, None) is False

    exported = facade.export_raw("psd")
    assert exported and exported["words"] == [1, 2, 3]
    path = facade.artifact_path("psd", "png", APP_ROOT / "tmp")
    assert path.endswith(".png") and "psd" in path

    facade.shutdown()
    assert ("shutdown",) in runtime.calls


def test_connection_loss_reports_disconnected(monkeypatch, qapp):
    _install_fake_runtime(monkeypatch)
    facade, _bridge, _images, _lang = _facade(monkeypatch, qapp)
    facade.set_connection(True, {"enabled": True})
    facade.set_connection(False)
    status = facade.status()
    assert status["connected"] is False
    assert status["featureApiEnabled"] is False
    assert "设备未连接" in status["deviceSoftwareNote"]
