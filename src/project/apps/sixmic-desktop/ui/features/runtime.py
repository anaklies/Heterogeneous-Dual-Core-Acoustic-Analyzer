"""Pure-Python FeatureRuntime for echo-features-1 (UI state machine + scheduler).

No Qt import: the Lead-owned AppViewModel facade adapts App slots and the frozen
BackendBridge to this class.  Responsibilities:

* merge the device feature catalog (51 unique primary entries) and expose
  page-scoped icon entries; measurement parameters are always the fixed-hidden
  spec.launch values and are never exposed to QML;
* schedule the 8 bounded device task slots: P2 / staged / events run exclusively
  and serially, P0/P1 run concurrently (<=3), queued jobs show "waiting for slot";
* start -> accept -> poll get with 250ms->2s backoff -> fetch result only when
  completed -> decode -> release the PC buffer handle; never replay start/stop
  after a timeout/disconnect;
* validate every identity (jobId/featureId/sourceKind/configuration/totalWords)
  and keep generation/sourceFrame as decimal strings;
* sustain the reference lifecycle (A/B, relative insulation, STIPA reference job
  protected; job_not_found clears and asks for a rebuild);
* implement the documented flows: reference/compare, reference/measure,
  staged STIPA (101 stages), room stimulus confirmation, NC/NR explicit nominal
  reference, frequency/time weighting dual runs, event monitoring without
  feature.result polling, manual DAS capability, fixed directed DAS angles;
* bound every QML payload through the decoder (peak-envelope extraction etc.).
"""
from __future__ import annotations

import json
import math
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from .catalog import (EXPECTED_FEATURE_COUNT, INTERFACE_VERSION, MAX_JOB_SLOTS,
                      FeatureCatalog, CatalogError, load_spec, reason as catalog_reason)
from .decoder import (DecodeError, ResultPageAssembler, decode_result, seal_chart,
                      u32_words)
from . import flows as flow_specs

ACTIVE_STATES = ("starting", "accepted", "running", "stopping")
TERMINAL_STATES = ("completed", "failed", "canceled", "stopped")
JOB_STATES = ("idle", "queued") + ACTIVE_STATES + ("stopped", "completed",
                                                   "failed", "canceled")
EXCLUSIVE_MODES = {"p2", "staged", "events"}
NONEXCLUSIVE_CONCURRENCY = 3
POLL_INITIAL = 0.05
POLL_MAX = 0.2
START_TIMEOUT = 15.0
REQUEST_TIMEOUT = 15.0
STOP_TIMEOUT = 30.0
STALE_AFTER_SECONDS = 60.0
READ_CHUNK_WORDS = 262144
RESULT_PAGE_WORDS = 1024
MAX_RESULT_WORDS = 16 * 1024 * 1024
RAW_BUDGET_BYTES = 64 * 1024 * 1024
MAX_EVENTS = 200
ALLOWED_SOURCE_KINDS = {"pl-live", "test-fixture"}
# Only these view preferences are display-only and never trigger a PL task.
VIEW_OPTIONS = {"logX", "legend", "2D3D", "cursor", "colorLock"}
CONFIRMATION_IDS = {"stimulus", "chain-confirm", "testSignalConfirmed",
                    "referenceConfirmed"}
CONFIRMATION_REASON = {
    "stimulus": {"zh": "请先选择房间激励方式（拍手 / 脉冲）。",
                 "en": "Select the room stimulus (clap / impulse) first."},
    "chain-confirm": {"zh": "请确认同激励 / 增益 / 测量链已保持。",
                      "en": "Confirm the same excitation / gain / measurement chain."},
    "testSignalConfirmed": {"zh": "请先完成 io_pcm 参考并确认测试信号。",
                            "en": "Capture the io_pcm reference and confirm the test signal first."},
    "referenceConfirmed": {"zh": "请先声明显式名义数字参考（不是声学校准）。",
                           "en": "Declare the explicit nominal digital reference first."},
}
STATE_MESSAGES = {
    "idle": ("待启动", "Idle"),
    "queued": ("等待任务槽", "Waiting for a task slot"),
    "starting": ("启动中", "Starting"),
    "accepted": ("已受理", "Accepted"),
    "running": ("运行中", "Running"),
    "stopping": ("停止中", "Stopping"),
    "stopped": ("已停止", "Stopped"),
    "completed": ("已完成", "Completed"),
    "failed": ("失败", "Failed"),
    "canceled": ("已取消", "Canceled"),
    "unavailable": ("不可用", "Unavailable"),
    "blocked": ("等待前提", "Blocked"),
}


def _bilingual(zh: str, en: str = "") -> dict[str, str]:
    return {"zh": zh, "en": en or zh}


def _empty_reason() -> dict[str, str]:
    return {"zh": "", "en": ""}


def _clean_error(error: Any) -> dict[str, Any]:
    """Normalise the bridge error payload to {code,reason,detail}."""
    if isinstance(error, dict):
        code = str(error.get("code") or error.get("error") or "backend-error")
        detail = error.get("detail")
        reason = error.get("reason")
        if not reason and isinstance(detail, dict):
            reason = detail.get("reason") or detail.get("detail")
        if not reason:
            reason = error.get("messageKey") or error.get("message") or code
        return {"code": code, "reason": str(reason)[:300],
                "detail": detail if isinstance(detail, dict) else {}}
    if error is None:
        return {"code": "backend-error", "reason": "unknown error", "detail": {}}
    return {"code": "backend-error", "reason": str(error)[:300], "detail": {}}


@dataclass
class _Job:
    job_id: str = ""
    feature_id: str = ""
    owner: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    role: str = "primary"
    variant_id: str = ""
    launch_kind: str = "single"
    tier: str = "P0"
    mode: str = "p0"
    exclusive: bool = False
    expected_result: bool = True
    inject: list[str] = field(default_factory=list)
    state: str = "queued"
    seq: int = 0
    started_at: float | None = None
    sent_at: float | None = None
    completed_at: float | None = None
    poll_at: float | None = None
    poll_interval: float = POLL_INITIAL
    poll_pending: bool = False
    fetching_result: bool = False
    stop_requested: bool = False
    stop_deadline: float | None = None
    result_requested: bool = False
    result_requested_at: float | None = None
    result_retries: int = 0
    reference_job_id: str | None = None
    source_kind: str = ""
    configuration: dict[str, Any] = field(default_factory=dict)
    final_configuration: dict[str, Any] | None = None
    progress: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    schema: dict[str, Any] = field(default_factory=dict)
    total_words: int = 0
    request_id: str = ""

    def active(self) -> bool:
        return self.state in ACTIVE_STATES


class FeatureRuntime:
    """UI-layer feature runtime; the Lead facade owns the QML properties."""

    def __init__(self, spec: dict[str, Any] | None = None,
                 call: Callable[[str, dict[str, Any]], str] | None = None,
                 read_buffer: Callable[[str, int, int], bytes] | None = None,
                 release_handle: Callable[[str], Any] | None = None,
                 notify: Callable[[str, str, str], Any] | None = None,
                 now: Callable[[], float] | None = None,
                 clock: Callable[[], float] | None = None, *,
                 spec_path: str | Path | None = None,
                 instrument_mode: bool = False) -> None:
        if spec is None:
            spec = load_spec(spec_path)
        elif isinstance(spec, (str, Path)):
            spec = load_spec(spec)
        self.catalog = FeatureCatalog(spec)
        self._instrument_mode=bool(instrument_mode)
        self._call = call or (lambda op, args: (_ for _ in ()).throw(
            RuntimeError("feature bridge is not attached")))
        self._read_buffer = read_buffer or (lambda handle, offset, count: b"")
        self._release_handle = release_handle or (lambda handle: None)
        self._notify = notify or (lambda level, title, detail: None)
        self._clock = clock or now or time.monotonic
        self._callbacks: list[Callable[[], None]] = []
        # connection / capability
        self._connected = False
        self._api_enabled = False
        self._api_info: dict[str, Any] = {}
        self._api_version = ""
        self._paused_reason = "not-connected"
        self._catalog_pending = False
        self._shutdown = False
        self._live_requested: set[str] = set()
        self._live_due: dict[str, float] = {}
        # Backoff for auto-start retries: a failing start must not be re-issued
        # on every 50 ms tick (that flooded the gateway and the UI signal path).
        self._auto_start_last: dict[str, float] = {}
        self._auto_stopped: set[str] = set()
        self._stream_active=False
        self._auto_input_features=set()
        self._input_channels={}
        self._manual_direction={"azimuth_deg":0.0,"elevation_deg":0.0}
        self._scalar_history={}
        self._live_stft=[]
        self._live_stft_key=None
        self._live_stft_render=0.0
        self._background_feature=""
        # Page -> last feature the user was viewing, so returning to a page
        # restores that workspace (paused with its retained chart) instead of
        # silently switching to the page's first feature.
        self._last_feature_by_page: dict[str, str] = {}
        # Features whose only data is a chart restored from a previous app
        # session; they render paused even while the device is disconnected.
        self._history_features: set[str] = set()
        # jobs
        self._jobs: dict[str, _Job] = {}
        self._queue: list[_Job] = []
        self._seq = 0
        self._pending: dict[str, dict[str, Any]] = {}
        # view state
        self._page = ""
        self._open_feature = ""
        self._confirmations: dict[str, dict[str, Any]] = {}
        self._view_options: dict[str, dict[str, Any]] = {}
        self._messages: dict[str, dict[str, str]] = {}
        self._errors: dict[str, dict[str, Any]] = {}
        # results / references / variants
        self._results: dict[str, dict[str, Any]] = {}
        self._references: dict[str, dict[str, Any]] = {}
        self._reference_notes: dict[str, str] = {}
        self._variants: dict[str, list[dict[str, Any]]] = {}
        self._variant_pending: dict[str, list[dict[str, Any]]] = {}
        self._selected_variants: dict[str, int] = {}
        self._weighting_history: dict[str, list[tuple[float,float]]] = {}
        self._raw_total = 0
        self._raw_order: list[str] = []
        # events (external event service forward)
        self._events: list[dict[str, Any]] = []
        self._observed_sources: set[str] = set()
        self._last_change = 0.0

    # ------------------------------------------------------------------
    # change notification
    # ------------------------------------------------------------------
    def on_change(self, callback: Callable[[], None]) -> None:
        if callable(callback) and callback not in self._callbacks:
            self._callbacks.append(callback)

    def _changed(self) -> None:
        for callback in list(self._callbacks):
            try:
                callback()
            except Exception:  # noqa: BLE001 - UI notification must not break runtime
                pass

    def _notify_safe(self, level: str, title: str, detail: str = "") -> None:
        try:
            self._notify(str(level), str(title), str(detail))
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # connection / capability / catalog
    # ------------------------------------------------------------------
    def set_feature_api(self, enabled: bool, info: dict[str, Any] | None = None) -> None:
        """Apply the gateway featureApi capability (Lead facade calls this)."""
        info = dict(info or {})
        connected = bool(info.get("connected", enabled))
        was_connected = self._connected
        was_enabled = self._api_enabled and self._connected
        self._connected = connected
        self._api_enabled = bool(enabled) and connected
        self._api_info = info
        self._api_version = str(info.get("version") or info.get("apiVersion") or "")
        state_changed = ((was_connected != self._connected)
                         or (was_enabled != self._api_enabled))
        if self._api_enabled:
            self._paused_reason = ""
            if not was_enabled:
                self._messages.pop("__api__", None)
                self._errors.pop("__api__", None)
                self._notify_safe("info", "功能接口可用 / featureApi available",
                                  f"version={self._api_version or '?'}")
        else:
            # Only warn when the capability state actually changed.  Initial
            # disconnected snapshots and repeated disabled snapshots must not
            # toast "功能接口不可用" on every settings edit / connection retry.
            self._on_capability_lost(connected, notify=state_changed)
        self._changed()

    def set_connection(self, connected: bool,
                       info: dict[str, Any] | None = None) -> None:
        """Optional convenience: connection state without a full capability dict."""
        info = dict(info or {})
        info["connected"] = bool(connected)
        enabled = bool(info.get("enabled", self._api_enabled)) and bool(connected)
        self.set_feature_api(enabled, info)

    def _on_capability_lost(self, connected: bool, *, notify: bool = True) -> None:
        self._live_requested.clear()
        self._live_due.clear()
        key = "connection-lost" if not connected else "feature-api-disabled"
        self._paused_reason = key
        if not connected:
            self._connected = False
        for job in self._active_jobs():
            self._fail_job(job, {"code": key,
                                 "reason": "断线/能力丢失：不会自动重放 start/stop，"
                                           "先恢复 capabilities/session 再决定"})
        if self._references:
            for owner in list(self._references):
                self._clear_reference(owner, "设备连接/能力丢失，参考已失效，请重建参考")
        self._catalog_pending = False
        note = ("设备未连接" if not connected
                else "设备 featureApi 未启用（设备软件需要更新到 echo-features-1）")
        self._messages["__api__"] = _bilingual(
            note + "；禁止退回 PC 计算或假装成功。",
            "Device not connected / featureApi disabled. PC computation is never "
            "substituted for PL results.")
        if notify:
            self._notify_safe("warn", "功能接口不可用", note)

    def refresh_catalog(self) -> bool:
        """Issue feature.list (op='list'); the facade calls this on connect."""
        if self._shutdown:
            return False
        if not (self._connected and self._api_enabled):
            self._messages["__api__"] = _bilingual(
                "功能接口不可用，无法获取目录。",
                "Feature API unavailable; catalog cannot be fetched.")
            self._changed()
            return False
        if self._catalog_pending:
            return False
        request_id = self._issue("list", {}, purpose="list")
        if request_id:
            self._catalog_pending = True
        self._changed()
        return bool(request_id)

    def set_features(self, catalog_result: Any) -> Any:
        """Merge a device feature.list result (also used by tests/facade)."""
        self._auto_input_features=set(catalog_result.get("autoInputFeatures",[])) if isinstance(catalog_result,dict) else set()
        report = self.catalog.merge_device_catalog(catalog_result)
        if report.complete:
            for fid,error in list(self._errors.items()):
                if error.get("code")=="unavailable" and self._availability(fid)[0]:
                    self._errors.pop(fid,None);self._messages.pop(fid,None)
            self._messages.pop("__catalog__", None)
            self._notify_safe("info", "功能目录已就绪",
                              f"{report.version} · {len(report.features)} 项")
        else:
            detail = "; ".join(report.errors[:3] + report.duplicates[:3] +
                               report.missing[:3])
            self._messages["__catalog__"] = _bilingual(
                "设备功能目录校验失败：请重新刷新目录。",
                "Device feature catalog validation failed; refresh the catalog.")
            self._notify_safe("warn", "功能目录校验失败", detail)
        self._changed()
        return report

    # ------------------------------------------------------------------
    # availability helpers
    # ------------------------------------------------------------------
    def _availability(self, feature_id: str) -> tuple[bool, dict[str, str]]:
        if feature_id not in self.catalog.features:
            return False, _empty_reason()
        if not self._connected:
            return False, catalog_reason("not-connected")
        if not self._api_enabled:
            return False, catalog_reason("feature-api-disabled")
        if self._api_version and self._api_version not in (INTERFACE_VERSION, "1",
                                                           "echo-features-1"):
            return False, catalog_reason("old-gateway")
        if not self.catalog.device_catalog_complete:
            return False, catalog_reason("catalog-pending")
        if feature_id not in self.catalog.device:
            return False, catalog_reason("not-in-device-catalog")
        # Known device-side gaps (e.g. zoom_fft acquisitionPreparationPlan lacks
        # inputWords/inputWordOffset): start disabled with the device reason; the
        # wired request path stays visible in the spec/registry for evidence and
        # the PC never recomputes or fakes success.
        device_path = self.catalog.feature(feature_id).get("devicePath")
        gap = device_path.get("knownGap") if isinstance(device_path, dict) else None
        if isinstance(gap, dict) and gap:
            reason = _empty_reason()
            reason["zh"] = str(gap.get("zh") or gap.get("reason") or "设备侧已知缺口，功能不可用。")
            reason["en"] = str(gap.get("en") or "Known device-side gap; feature unavailable.")
            return False, reason
        return True, _empty_reason()

    # ------------------------------------------------------------------
    # jobs
    # ------------------------------------------------------------------
    def _active_jobs(self) -> list[_Job]:
        return [job for job in self._jobs.values() if job.active()]

    def _feature_jobs(self, feature_id: str) -> list[_Job]:
        return [job for job in self._jobs.values() if job.owner == feature_id]

    def _active_feature_job(self, feature_id: str) -> _Job | None:
        for job in self._jobs.values():
            if job.owner == feature_id and job.active():
                return job
        return None

    def _last_feature_job(self, feature_id: str) -> _Job | None:
        jobs = self._feature_jobs(feature_id)
        return jobs[-1] if jobs else None

    def _issue(self, op: str, args: dict[str, Any], *, purpose: str,
               job: _Job | None = None, feature_id: str = "") -> str:
        try:
            request_id = self._call(str(op), dict(args))
        except Exception as exc:  # noqa: BLE001 - surface as explicit failure
            error = {"code": "feature-call-failed",
                     "reason": f"{op} 调用失败: {exc}"[:300], "detail": {}}
            if job is not None:
                self._fail_job(job, error)
            else:
                self._notify_safe("error", "功能接口调用失败", f"{op}: {exc}")
            return ""
        if not isinstance(request_id, str) or not request_id:
            if job is not None:
                self._fail_job(job, {"code": "feature-call-invalid",
                                     "reason": "call() 未返回 requestId", "detail": {}})
            return ""
        if job is not None:
            job.request_id = request_id
        self._pending[request_id] = {
            "op": str(op), "purpose": str(purpose),
            "jobId": job.job_id if job else "",
            "pendingKey": (f"pending-{job.seq}" if job is not None and not job.job_id
                           else ""),
            "featureId": feature_id, "sentAt": self._clock(),
        }
        return request_id

    def _create_job(self, owner: str, feature: dict[str, Any], run: dict[str, Any],
                    *, role: str, device_feature: str | None = None) -> _Job:
        feature_id = str(device_feature or owner)
        mode = str(feature.get("mode") or "p0")
        launch = feature.get("launch") if isinstance(feature.get("launch"), dict) else {}
        kind = str(launch.get("kind") or "single")
        exclusive = mode in EXCLUSIVE_MODES or kind in ("staged_stipa", "monitor") or \
            bool((feature.get("runtime") or {}).get("exclusive"))
        monitor = flow_specs.flow_kind(feature) == "monitor"
        self._seq += 1
        job = _Job(feature_id=feature_id, owner=owner,
                   params=dict(run.get("params") or {}), role=str(role),
                   variant_id=str(run.get("variantId") or ""),
                   launch_kind=kind, tier=str(feature.get("tier") or "P0"),
                   mode=mode, exclusive=exclusive,
                   expected_result=not monitor,
                   inject=list(run.get("inject") or []),
                   seq=self._seq, state="queued")
        return job

    def _enqueue(self, job: _Job) -> None:
        self._jobs[job.job_id or f"pending-{job.seq}"] = job
        self._queue.append(job)

    def _schedule(self) -> None:
        """Start queued jobs respecting the 8 slots / exclusive / concurrency rules."""
        if self._shutdown or self._paused_reason:
            return
        now = self._clock()
        while True:
            active = [job for job in self._jobs.values() if job.active()]
            if len(active) >= self.catalog.max_slots:
                return
            exclusive_active = any(job.exclusive for job in active)
            if exclusive_active:
                return
            pending = [job for job in self._queue if job.state == "queued"]
            if not pending:
                return
            next_job = min(pending, key=lambda job: job.seq)
            nonexclusive_active = sum(1 for job in active if not job.exclusive)
            if not next_job.exclusive:
                if nonexclusive_active >= NONEXCLUSIVE_CONCURRENCY:
                    return
                self._queue.remove(next_job)
                self._start_job(next_job, now)
                continue
            # Exclusive job: only when nothing else is active and no queued
            # non-exclusive job was selected earlier (FIFO is preserved).
            if active:
                return
            self._queue.remove(next_job)
            self._start_job(next_job, now)
            return

    def _start_job(self, job: _Job, now: float) -> None:
        job.state = "starting"
        job.started_at = job.started_at or now
        job.sent_at = now
        self._messages[job.owner] = {
            "zh": f"启动 {self._feature_name(job.owner)}…",
            "en": f"Starting {self._feature_name(job.owner)}…",
        }
        if self._variant_pending.get(job.owner):
            for variant in self._variants.get(job.owner) or []:
                if variant.get("id") == job.variant_id:
                    variant["state"] = "running"
        params = dict(job.params)
        if job.owner=="noise_rating":
            params["referenceOffsetDb"]=self._ensure_confirmations(job.owner).get("noiseReferenceOffsetDb",123.01)
            params["calibrationSource"]="INMP441 nominal sensitivity conversion, editable reference"
        if job.owner=="directed_das":params.update(self._manual_direction)
        for key in job.inject:
            if key == "referenceJobId":
                reference = self._references.get(job.owner) or {}
                if reference.get("jobId"):
                    params["referenceJobId"] = str(reference["jobId"])
            elif key == "confirmed":
                params["confirmed"] = True
            elif key == "testSignalConfirmed":
                params["testSignalConfirmed"] = True
            elif key == "stimulus":
                value = self._confirmation_value(job.owner, "stimulus")
                if value:
                    params["stimulus"] = value
        if "io_pcm" not in str(job.feature_id):
            self._ensure_confirmations(job.owner)
        job.params = params
        self._messages[job.owner] = {
            "zh": f"{self._feature_name(job.owner)} 启动中（{job.state}）",
            "en": f"{self._feature_name(job.owner)} starting",
        }
        self._issue("start", {"featureId": job.feature_id, "params": params},
                    purpose="start", job=job, feature_id=job.owner)
        self._changed()

    # ------------------------------------------------------------------
    # user actions
    # ------------------------------------------------------------------
    def _feature_name(self, feature_id: str) -> str:
        feature = self.catalog.feature(feature_id)
        return str(feature.get("name") or feature_id)

    def _ensure_confirmations(self, feature_id: str) -> dict[str, Any]:
        if feature_id not in self._confirmations:
            feature = self.catalog.feature(feature_id)
            self._confirmations[feature_id] = flow_specs.confirmation_defaults(feature)
            for item in flow_specs.flow_definition(feature)["confirmations"]:
                if item.get("type")!="enum":self._confirmations[feature_id][item["id"]]=True
            if feature_id in {"room_decay","room_clarity","spectral_decay"}:self._confirmations[feature_id]["stimulus"]="clap"
        return self._confirmations[feature_id]

    def _confirmation_value(self, feature_id: str, confirmation_id: str) -> Any:
        return self._ensure_confirmations(feature_id).get(confirmation_id)

    def _required_confirmations(self, feature_id: str) -> list[str]:
        feature = self.catalog.feature(feature_id)
        definition = flow_specs.flow_definition(feature)
        kind = definition["kind"]
        values = self._ensure_confirmations(feature_id)
        required: list[str] = []
        for item in definition["confirmations"]:
            cid = str(item["id"])
            if kind == "room_stimulus" and cid == "stimulus":
                required.append(cid)
            elif kind in ("reference_compare",):
                continue
            elif kind == "reference_measure" and cid == "chain-confirm":
                if self._references.get(feature_id):
                    required.append(cid)
            elif kind == "staged_stipa" and cid == "testSignalConfirmed":
                if self._references.get(feature_id):
                    required.append(cid)
            elif kind == "dual_variant" and cid == "referenceConfirmed":
                required.append(cid)
            elif cid not in values or values.get(cid) in (None, False):
                required.append(cid)
        return [cid for cid in required if not bool(self._confirmation_value(feature_id, cid))]

    def open(self, feature_id: str, *, resume: bool = True) -> bool:
        """Open a feature workspace.

        resume=False is used when a page is re-entered: the last chart of
        that feature stays visible (paused) until the user explicitly
        starts it again.
        """
        feature_id = str(feature_id or "")
        if self._shutdown or feature_id not in self.catalog.features:
            return False
        if self._open_feature and self._open_feature != feature_id:
            previous=self._open_feature
            previous_feature=self.catalog.feature(previous);next_feature=self.catalog.feature(feature_id)
            previous_big=self._instrument_mode and previous_feature.get('mode') in EXCLUSIVE_MODES
            next_big=next_feature.get('mode') in EXCLUSIVE_MODES
            if previous_big and not next_big and (self._active_feature_job(previous) or previous in self._live_requested):
                self._background_feature=previous
            else:self.close()
        if self.catalog.feature(feature_id).get('mode') in EXCLUSIVE_MODES:
            for job in list(self._active_jobs()):
                if job.owner!=feature_id and job.exclusive and not job.stop_requested:self.stop(job.owner)
            for owner in list(self._live_requested):
                if owner!=feature_id and self.catalog.feature(owner).get('mode') in EXCLUSIVE_MODES:self.stop(owner)
            if self._background_feature!=feature_id:self._background_feature=""
        if flow_specs.flow_kind(self.catalog.feature(feature_id)) == "dual_variant" and feature_id not in self._variants:
            self._variants[feature_id] = [flow_specs.variant_definition(self.catalog.feature(feature_id), r) for r in flow_specs.run_plan(self.catalog.feature(feature_id))]
        self._open_feature = feature_id
        page = str(self.catalog.feature(feature_id).get("page") or "")
        if page:
            self._last_feature_by_page[page] = feature_id
        self._messages.pop(feature_id, None)
        self._errors.pop(feature_id, None)
        if resume:
            self._auto_stopped.discard(feature_id)
        elif feature_id in self._results and not self._active_feature_job(feature_id):
            # Returning to a previously measured workspace: keep the last chart
            # and wait for an explicit start instead of silently re-running.
            self._auto_stopped.add(feature_id)
            self._messages[feature_id] = _bilingual(
                "已暂停：显示上次结果；点击“开始测量”继续。",
                "Paused: last result kept; press Run to continue.")
        self._reuse_room_result_view(feature_id)
        self._reuse_spatial_result_view(feature_id)
        self._ensure_confirmations(feature_id)
        self._changed()
        return True

    def _reuse_spatial_result_view(self, target: str) -> None:
        aliases={"band_das","spatial_grid","spatial_peaks"}
        if target not in aliases:return
        sources=[r for fid,r in self._results.items() if fid in aliases and fid!=target and r.get("spaceSchema") and r.get("raw_bytes")]
        if not sources:return
        source=max(sources,key=lambda r:r.get("capturedAt",0));existing=self._results.get(target)
        if existing and existing.get("capturedAt",0)>=source.get("capturedAt",0):return
        schema=source["spaceSchema"];layout=schema.get("actualProducerLayout") or {}
        if layout.get("service")!="manual_DAS_power_map":return
        chart=decode_result(self.catalog.feature(target),{"schema":schema,"configuration":source.get("configuration",{})},u32_words(source["raw_bytes"]))
        chart.pop("decodeMeta",None);chart["subtitle"]=str(chart.get("subtitle", ""))+" · 共用上次扫描，采集时间不变"
        result=dict(source,featureId=target,chart=seal_chart(chart))
        self._drop_raw(target);self._results[target]=result;self._raw_total+=len(result["raw_bytes"]);self._raw_order.append(target);self._evict_raw()
        for key,job in list(self._jobs.items()):
            if job.owner==target and job.state in TERMINAL_STATES and job.role!="reference":self._jobs.pop(key,None)

    def _reuse_room_result_view(self, target: str) -> None:
        # Re-display an already measured unfiltered PL IR summary. No device
        # job, new acoustic computation, or new capture timestamp is created.
        pair={"room_decay":"room_clarity","room_clarity":"room_decay"}
        if target not in pair:return
        source=self._results.get(pair[target]);current=self._results.get(target)
        if not source or not source.get("raw_bytes") or not source.get("roomSchema"):return
        schema=source["roomSchema"];layout=schema.get("actualProducerLayout") or schema.get("producerLayout") or {}
        if layout.get("service")!="room_ir_unfiltered":return
        if current and current.get("capturedAt",0)>=source.get("capturedAt",0):return
        payload={"featureId":source.get("sourceFeatureId",pair[target]),"state":"completed","sourceKind":source.get("sourceKind"),"configuration":source.get("configuration"),"schema":schema}
        chart=decode_result(self.catalog.feature(target),payload,u32_words(source["raw_bytes"]))
        meta=chart.pop("decodeMeta",{});alias=dict(source);alias.update(featureId=target,chart=chart,decodeMeta=meta,sourceFeatureId=payload["featureId"])
        if current:self._raw_total-=len(current.get("raw_bytes") or b"")
        self._results[target]=alias;self._raw_total+=len(alias["raw_bytes"])
        if target in self._raw_order:self._raw_order.remove(target)
        self._raw_order.append(target)
        for key,job in list(self._jobs.items()):
            if job.owner==target and job.state in TERMINAL_STATES and job.role!="reference":self._jobs.pop(key,None)
        self._errors.pop(target,None)
        self._messages[target]=_bilingual("同一次拍手的PL结果 · 切换视图，无需再拍一次","Same captured PL impulse · alternate view, no new clap required")
        self._evict_raw()

    def close(self, *, pause: bool = False) -> None:
        feature_id = self._open_feature
        if not feature_id:
            return
        self._live_requested.discard(feature_id)
        self._live_due.pop(feature_id, None)
        for job in list(self._feature_jobs(feature_id)):
            if job.active():
                self._request_stop(job)
        if pause and feature_id in self._results:
            # Leaving the page pauses continuous features and keeps the last
            # chart available; returning shows it stopped, not empty.
            self._auto_stopped.add(feature_id)
            self._messages[feature_id] = _bilingual(
                "已暂停：已保留离开前的最近结果；点击“开始测量”继续。",
                "Paused: the last result is kept; press Run to continue.")
        self._open_feature = ""
        self._changed()

    def run(self, feature_id: str) -> None:
        feature_id = str(feature_id or "")
        if self._shutdown:
            return
        feature = self.catalog.feature(feature_id)
        if not feature:
            return
        # An explicit start always overrides an automatic page-leave pause.
        self._auto_stopped.discard(feature_id)

        if not self._open_feature:
            self.open(feature_id)
        available, reason = self._availability(feature_id)
        if not available:
            self._errors[feature_id] = {"code": "unavailable",
                                        "reason": reason.get("zh", ""),
                                        "reasonEn": reason.get("en", ""),
                                        "detail": {}}
            self._messages[feature_id] = {
                "zh": reason.get("zh", "不可用"), "en": reason.get("en", "Unavailable")}
            if self._connected and self._api_enabled and not self.catalog.device_catalog_complete:
                self.refresh_catalog()
                self._messages[feature_id]=_bilingual("正在同步功能目录，请稍候","Synchronizing feature catalog")
            else:self._notify_safe("warn", "功能暂不可用", reason.get("zh", ""))
            self._changed()
            return
        if self._active_feature_job(feature_id):
            self._messages[feature_id] = _bilingual("任务已在运行；可先停止。",
                                                    "A job is already running; stop it first.")
            self._changed()
            return
        self._errors.pop(feature_id, None)
        kind = flow_specs.flow_kind(feature)
        plan = flow_specs.run_plan(feature)
        values = self._ensure_confirmations(feature_id)
        if kind == "staged_stipa":
            selected = values.get("measurementMode", "complete")
            samples = 384000 if selected == "quick" else 720000
            plan[0]["params"]["samples"] = samples
            plan[1]["params"].update(samples=samples, measurementMode=selected)
        if kind == "room_stimulus":
            if not values.get("stimulus"):
                self._messages[feature_id] = CONFIRMATION_REASON["stimulus"]
                self._notify_safe("info", "需要流程确认", "请选择房间激励方式")
                self._changed()
                return
            self._start_primary(feature, plan[0], owner=feature_id)
            return
        if kind == "reference_compare":
            if not self._references.get(feature_id):
                self._start_primary(feature, plan[0], owner=feature_id, role="reference")
                return
            compatible, note = self._reference_compatible(feature_id, feature)
            if not compatible:
                self._messages[feature_id] = {
                    "zh": f"参考不兼容：{note}；请重新建立参考。",
                    "en": f"Reference incompatible: {note}; capture a new reference."}
                self._notify_safe("warn", "参考不兼容", note)
                self._changed()
                return
            self._start_primary(feature, plan[1], owner=feature_id)
            return
        if kind == "reference_measure":
            if not self._references.get(feature_id):
                self._start_primary(feature, plan[0], owner=feature_id, role="reference")
                return
            if not bool(values.get("chain-confirm")):
                self._messages[feature_id] = CONFIRMATION_REASON["chain-confirm"]
                self._notify_safe("info", "需要流程确认", "请确认同激励/增益/测量链")
                self._changed()
                return
            self._start_primary(feature, plan[1], owner=feature_id)
            return
        if kind == "staged_stipa":
            reference = self._references.get(feature_id)
            if not reference:
                reference_feature = str(plan[0].get("referenceFeature") or "io_pcm")
                self._start_primary(feature, plan[0], owner=feature_id,
                                    role="reference", device_feature=reference_feature)
                return
            if not bool(values.get("testSignalConfirmed")):
                self._messages[feature_id] = CONFIRMATION_REASON["testSignalConfirmed"]
                self._notify_safe("info", "需要流程确认", "请确认 STIPA 测试信号")
                self._changed()
                return
            self._start_primary(feature, plan[1], owner=feature_id)
            return
        if kind == "dual_variant":
            missing = self._required_confirmations(feature_id)
            if missing:
                self._messages[feature_id] = CONFIRMATION_REASON.get(
                    missing[0], _bilingual("请先完成流程确认。", "Complete the workflow confirmation first."))
                self._notify_safe("info", "需要流程确认", "请先完成流程确认")
                self._changed()
                return
            self._start_dual(feature, plan, feature_id)
            return
        self._start_primary(feature, plan[0], owner=feature_id)

    def _start_primary(self, feature: dict[str, Any], run: dict[str, Any], *,
                       owner: str, role: str = "primary",
                       device_feature: str | None = None) -> None:
        if self._instrument_mode and role == "primary" and (feature.get("runtime") or {}).get("continuous"):
            self._live_requested.add(owner)
            self._auto_stopped.discard(owner)
        if self._instrument_mode and self._stream_active and role=="primary" and owner in {"fft","io_pcm","stft","levels_core","levels_extended"} and (owner not in self._auto_input_features or owner in self._input_channels):
            self._live_due.pop(owner,None)
            self._messages[owner]=_bilingual("正在接收连续PL帧","Receiving continuous PL frames")
            self._changed();return
        job = self._create_job(owner, feature, run, role=role,
                               device_feature=device_feature)
        if owner in self._auto_input_features:
            locked=self._input_channels.get(owner)
            if locked:job.params["channel"]=locked["channel"]
            else:job.params["autoChannel"]=True
            if job.mode=="p1":job.exclusive=True
        self._enqueue(job)
        self._schedule()
        self._changed()

    def _start_dual(self, feature: dict[str, Any], plan: list[dict[str, Any]],
                    owner: str) -> None:
        """Two independent PL runs (never merged); results are kept per variant."""
        if self._instrument_mode and (feature.get("runtime") or {}).get("continuous"):
            self._live_requested.add(owner)
        previous = {v.get("id"):v for v in self._variants.get(owner,[])}
        variants = [flow_specs.variant_definition(feature, run) for run in plan]
        for variant in variants:
            if variant.get("id") in previous:variant["chart"]=previous[variant["id"]].get("chart")
        self._variants[owner] = variants
        selected=self._selected_variants.get(owner,0) if self._instrument_mode and owner in {"frequency_time_weighting","noise_rating"} else None
        runs=[plan[min(selected,len(plan)-1)]] if selected is not None and plan else plan
        self._variant_pending[owner] = [dict(run) for run in runs]
        if not variants:
            return
        first = self._variant_pending[owner].pop(0)
        for variant in variants:
            variant["state"]="running" if variant["id"]==first.get("variantId") else "idle"
        self._start_primary(feature, first, owner=owner, role="variant")

    def stop(self, feature_id: str) -> None:
        feature_id = str(feature_id or "")
        self._input_channels.pop(feature_id,None)
        was_live=feature_id in self._live_requested
        self._live_requested.discard(feature_id)
        self._live_due.pop(feature_id,None)
        self._auto_stopped.add(feature_id)
        jobs = [job for job in self._feature_jobs(feature_id) if job.active()
                or job.state == "queued"]
        if not jobs:
            self._messages[feature_id] = _bilingual("持续测量已停止。" if was_live else "没有可停止的任务。",
                                                    "Continuous measurement stopped." if was_live else "No running job to stop.")
            last=self._last_feature_job(feature_id)
            if was_live and last is not None:last.state="stopped"
            self._changed()
            return
        for job in jobs:
            self._request_stop(job)
        self._changed()

    def _request_stop(self, job: _Job) -> None:
        job.stop_requested = True
        if job.state == "queued":
            job.state = "canceled"
            job.completed_at = self._clock()
            if job in self._queue:
                self._queue.remove(job)
            self._messages[job.owner] = _bilingual("已取消排队任务。",
                                                   "Queued job canceled.")
            return
        if not job.job_id:
            job.state = "canceled"
            return
        job.stop_requested = True
        job.state = "stopping"
        job.stop_deadline = self._clock() + STOP_TIMEOUT
        job.poll_at = self._clock() + POLL_INITIAL
        job.poll_interval = POLL_INITIAL
        self._messages[job.owner] = _bilingual("停止中：等待设备确认 canceled…",
                                               "Stopping: waiting for canceled…")
        self._issue("stop", {"jobId": job.job_id}, purpose="stop", job=job,
                    feature_id=job.owner)

    def refresh(self, feature_id: str) -> None:
        feature_id = str(feature_id or "")
        if self._active_feature_job(feature_id):
            self._messages[feature_id] = _bilingual("任务运行中，刷新需先停止。",
                                                    "Job running; stop before refresh.")
            self._changed()
            return
        self.run(feature_id)

    def confirm(self, feature_id: str, confirmation_id: str, value: Any) -> None:
        feature_id = str(feature_id or "")
        confirmation_id = str(confirmation_id or "")
        feature = self.catalog.feature(feature_id)
        if feature_id in {"frequency_time_weighting", "noise_rating"} and confirmation_id == "variantIndex":
            try: selected = int(value)
            except (TypeError, ValueError): return
            runs=flow_specs.run_plan(feature)
            if not 0<=selected<len(runs):return
            was_live=feature_id in self._live_requested
            if self._active_feature_job(feature_id):self.stop(feature_id)
            self._variant_pending[feature_id]=[]
            self._selected_variants[feature_id]=selected
            self._errors.pop(feature_id,None)
            if was_live:
                self._live_requested.add(feature_id);self._live_due[feature_id]=self._clock()+.1;self._auto_stopped.discard(feature_id)
            self._changed();return
        if feature_id=="noise_rating" and confirmation_id=="noiseReferenceOffsetDb":
            try:offset=float(value)
            except (TypeError,ValueError):return
            if math.isfinite(offset) and -200<=offset<=200 and not self._active_feature_job(feature_id):
                self._ensure_confirmations(feature_id)[confirmation_id]=offset;self._changed()
            return
        if feature_id == "stipa_experimental" and confirmation_id == "measurementMode":
            if value not in ("complete", "quick") or self._active_feature_job(feature_id):
                return
            values = self._ensure_confirmations(feature_id)
            if values.get("measurementMode", "complete") != value:
                values["measurementMode"] = value
                self._references.pop(feature_id, None)
                self._drop_raw(feature_id)
                self._results.pop(feature_id, None)
                for key, old in list(self._jobs.items()):
                    if old.owner == feature_id and not old.active(): self._jobs.pop(key, None)
                self._messages.pop(feature_id, None)
                self._changed()
            return
        if feature_id=="directed_das" and confirmation_id in ("azimuth_deg","elevation_deg"):
            try:v=float(value)
            except (TypeError,ValueError):return
            bound=360 if confirmation_id=="azimuth_deg" else 90
            if math.isfinite(v) and -bound<=v<=bound and not self._active_feature_job(feature_id):
                self._manual_direction[confirmation_id]=v;self._changed()
            return
        if not feature or confirmation_id not in CONFIRMATION_IDS:
            self._notify_safe("warn", "未知确认项", confirmation_id)
            return
        definition = flow_specs.flow_definition(feature)
        allowed = {str(item["id"]): item for item in definition["confirmations"]}
        if confirmation_id not in allowed:
            self._notify_safe("warn", "该流程不需要此确认", confirmation_id)
            return
        item = allowed[confirmation_id]
        if item.get("type") == "enum":
            options = [str(option.get("value")) for option in item.get("options") or []]
            if value not in options:
                self._notify_safe("warn", "确认值无效", f"{confirmation_id}={value!r}")
                return
            stored: Any = value
        else:
            stored = bool(value) and value not in ("false", "0", 0)
        self._ensure_confirmations(feature_id)[confirmation_id] = stored
        self._messages[feature_id] = _bilingual(
            "流程确认已记录。", "Workflow confirmation recorded.")
        self._notify_safe("info", "流程确认", f"{confirmation_id}={stored}")
        self._changed()

    def action(self, feature_id: str, action_id: str) -> None:
        feature_id = str(feature_id or "")
        action_id = str(action_id or "")
        feature = self.catalog.feature(feature_id)
        if not feature:
            return
        if action_id in ("run", "measure", "compare"):
            self.run(feature_id)
        elif action_id == "stop":
            self.stop(feature_id)
        elif action_id == "refresh":
            self.refresh(feature_id)
        elif action_id in ("reference",):
            self._start_reference_action(feature_id)
        elif action_id in ("save", "export"):
            self._messages[feature_id] = _bilingual(
                "图像/原始数据导出由界面按钮完成（保留测试数据标识）。",
                "Image/raw export is executed by the UI button (test-data marker kept).")
            self._notify_safe("info", "导出", "使用界面保存/导出按钮")
            self._changed()
        else:
            self._notify_safe("warn", "未知动作", action_id)

    def _start_reference_action(self, feature_id: str) -> None:
        feature = self.catalog.feature(feature_id)
        if not feature:
            return
        available, reason = self._availability(feature_id)
        if not available:
            if self._connected and self._api_enabled and not self.catalog.device_catalog_complete:
                self.refresh_catalog()
                self._messages[feature_id]=_bilingual("正在同步功能目录，请稍候","Synchronizing feature catalog")
            else:self._notify_safe("warn", "功能暂不可用", reason.get("zh", ""))
            return
        if self._active_feature_job(feature_id):
            self._notify_safe("warn", "任务运行中", "请先停止再建立参考")
            return
        kind = flow_specs.flow_kind(feature)
        if kind not in ("reference_compare", "reference_measure", "staged_stipa"):
            self._notify_safe("warn", "该功能不需要参考", feature_id)
            return
        self._live_requested.discard(feature_id)
        self._live_due.pop(feature_id,None)
        self._auto_stopped.add(feature_id)
        plan = flow_specs.run_plan(feature)
        if kind=="staged_stipa":
            plan[0]["params"]["samples"]=384000 if self._ensure_confirmations(feature_id).get("measurementMode")=="quick" else 720000
        run = plan[0]
        device_feature = str(run.get("referenceFeature") or feature_id)
        self._start_primary(feature, run, owner=feature_id, role="reference",
                            device_feature=device_feature)

    def set_view_option(self, feature_id: str, key: str, value: Any) -> None:
        feature_id = str(feature_id or "")
        key = str(key or "")
        if key not in VIEW_OPTIONS:
            return
        options = self._view_options.setdefault(feature_id, {})
        options[key] = value
        self._apply_view_options(feature_id)
        self._changed()

    def _apply_view_options(self, feature_id: str) -> None:
        options = self._view_options.get(feature_id) or {}
        result = self._results.get(feature_id)
        if not result:
            return
        chart = result.get("chart") or {}
        changed = False
        if "logX" in options:
            scale = "log" if options.get("logX") else "linear"
            x_axis = chart.get("xAxis") or {}
            if x_axis.get("scale") != scale:
                x_axis["scale"] = scale
                chart["xAxis"] = x_axis
        if "legend" in options:
            chart["legendVisible"] = bool(options.get("legend"))
        if "2D3D" in options:
            chart["view3D"] = bool(options.get("2D3D"))
        if "cursor" in options:
            chart["cursorEnabled"] = bool(options.get("cursor"))
        if "colorLock" in options and isinstance(chart.get("colorScale"), dict):
            chart["colorScale"]["locked"] = bool(options.get("colorLock"))
        result["chart"] = seal_chart(chart)

    # ------------------------------------------------------------------
    # page / lifecycle / clock
    # ------------------------------------------------------------------
    def set_live_stream_active(self, active: bool) -> None:
        was=self._stream_active;self._stream_active=bool(active)
        if was and not active:
            fid=self._open_feature
            if fid in self._live_requested:self._live_due[fid]=self._clock()+.2

    def ingest_live_frame(self, meta: dict[str,Any], body: bytes) -> None:
        fid=self._open_feature
        if not self._stream_active or fid not in self._live_requested or fid not in {"fft","io_pcm","stft","levels_core","levels_extended"}:return
        if fid in self._auto_input_features and (fid not in self._input_channels or int(meta['channel'])!=self._input_channels[fid]['channel']):return
        feature=self.catalog.feature(fid);fs=float(meta['sampleRateHz']);frame=int(meta['frame']);config=int(meta['config']);session=int(meta['session'])
        triplets=struct.unpack_from('<3075I',body)
        schema={'kind':'spectrum','fields':['amplitude'],'axes':{'bins':1025,'fftSize':2048,'sampleRateHz':fs},'units':'FS','validity':'Actual PL FFT frame, continuously streamed, explicit gaps','actualProducerLayout':{'service':'stream_fft2048','bins':1025,'sample_rate':fs}}
        if fid=='fft':values=list(triplets[0::3])
        elif fid in {'levels_core','levels_extended'}:
            values=list(struct.unpack_from('<48I',body,3075*4));schema.update(kind='scalars',fields=['rms_FS','peak_FS','peakToPeak_FS','mean_FS','rms_dBFS','crest','clipCount','nonzeroValid'],axes={'channels':6,'channelStrideWords':8},units='FS, dBFS, ratio, count',actualProducerLayout={'service':'stream_fft2048_levels'})
        elif fid=='io_pcm':
            values=list(struct.unpack_from('<12288I',body,3123*4));schema.update(kind='waveform',fields=['signed_PCM24'],axes={'channels':6,'channelStrideWords':2048,'sampleRateHz':fs},units='signed24 counts',actualProducerLayout={'service':'pcm24','channels':6,'sample_rate':fs})
        else:
            key=(session,config,int(meta['channel']))
            if key!=self._live_stft_key:self._live_stft=[];self._live_stft_key=key
            self._live_stft.append((str(meta['firstSampleIndex']),list(triplets[1::3])));self._live_stft=self._live_stft[-16:]
            if self._clock()-self._live_stft_render<.20:return
            self._live_stft_render=self._clock();values=[x for _,row in self._live_stft for x in row]
            schema.update(kind='timeFrequency',fields=['PSD'],axes={'bins':1025,'fftSize':2048,'sampleRateHz':fs,'frameFirstSampleIndices':[first for first,_ in self._live_stft]},units='FS squared/Hz',actualProducerLayout={'service':'live_PL_STFT','sample_rate':fs})
        configuration={'session':session,'config':config,'generation':'1','sourceFrame':str(frame),'firstSampleIndex':str(meta['firstSampleIndex']),'lastSampleIndex':str(meta['lastSampleIndex'])}
        job=_Job(job_id=f"live-{meta['streamId']}-{frame}",owner=fid,feature_id=fid,state='running',source_kind='pl-live',configuration=configuration,total_words=len(values))
        payload={'jobId':job.job_id,'featureId':fid,'state':'completed','sourceKind':'pl-live','configuration':configuration,'schema':schema,'totalWords':len(values)}
        chart=decode_result(feature,payload,values);decode_meta=chart.pop('decodeMeta',{})
        if meta.get('gap'):chart['subtitle']=str(chart.get('subtitle',''))+' · 采集窗口有间隔'
        self._store_result(job,chart,decode_meta,struct.pack('<'+'I'*len(values),*values))
        self._messages[fid]=_bilingual('连续实测帧 · 自动更新','Continuous measured frames · updating')
        self._changed()
    def on_page_changed(self, page_id: str) -> None:
        page_id = str(page_id or "")
        previous = self._page
        if page_id == previous:
            return
        self._page = page_id
        if previous and not self._instrument_mode:
            self._leave_page(previous)
        elif previous and self._open_feature:
            owner=self._open_feature;f=self.catalog.feature(owner)
            if f.get('mode') in EXCLUSIVE_MODES and (self._active_feature_job(owner) or owner in self._live_requested):
                self._background_feature=owner;self._open_feature=""
            else:
                auto_start=bool((f.get('runtime') or {}).get('autoStart'))
                self.close(pause=auto_start)
        if self._instrument_mode:
            choices=[x['feature'] for x in self.catalog.page_features(page_id) if (x['feature'].get('runtime') or {}).get('autoStart')]
            if not self._open_feature and choices:
                # Prefer the feature the user last viewed on this page so its
                # retained chart reappears (paused) instead of a different one.
                last_id=self._last_feature_by_page.get(page_id)
                target=next((f for f in choices if f.get('featureId')==last_id),None)
                if target is None:
                    preferred={'time':'levels_core','spectrum':'fft','bands':'third_octave'}.get(page_id)
                    target=next((f for f in choices if f.get('featureId')==preferred),choices[0])
                self.open(str(target['featureId']), resume=False)
                if str(target['featureId']) in self._results:
                    return  # paused history; no automatic start on re-entry

        # Keep measured charts/raw records subject to the existing bounded raw
        # budget. Opening another large feature, not a live page, cancels it.
        self._changed()

    def _leave_page(self, page_id: str) -> None:
        if self._open_feature:
            feature = self.catalog.feature(self._open_feature)
            if str(feature.get("page") or "") == page_id:
                self.close()
        for job in list(self._jobs.values()):
            feature = self.catalog.feature(job.owner)
            if str(feature.get("page") or "") != page_id:
                continue
            if job.state == "queued":
                self._request_stop(job)
            elif job.active() and (job.exclusive or job.mode in EXCLUSIVE_MODES):
                self._request_stop(job)
            elif job.expected_result is False and job.active():
                self._request_stop(job)
        for owner, result in list(self._results.items()):
            feature = self.catalog.feature(owner)
            if str(feature.get("page") or "") != page_id:
                continue
            if owner in self._references:
                continue
            self._drop_raw(owner)

    def tick(self, now: float | None = None) -> None:
        if self._shutdown:
            return
        current = float(now) if now is not None else float(self._clock())
        # P0/P1 read views start automatically when their workspace is visible.
        fid=self._open_feature
        if fid and fid not in self._auto_stopped and not self._active_feature_job(fid):
            f=self.catalog.feature(fid)
            if self._instrument_mode and (f.get("runtime") or {}).get("autoStart") and self._availability(fid)[0] and fid not in self._live_due and fid not in self._live_requested and current - self._auto_start_last.get(fid, 0.0) >= 2.0:
                self._auto_start_last[fid] = current
                self.run(fid)
        for owner,due in list(self._live_due.items()):
            if owner not in self._live_requested or owner not in {self._open_feature,self._background_feature}:
                self._live_due.pop(owner,None);continue
            if current>=due and not self._active_feature_job(owner):
                self._live_due.pop(owner,None);self.run(owner)
        changed = False
        # expiring pending requests -> explicit failure, never a replay
        for request_id, entry in list(self._pending.items()):
            if current - float(entry.get("sentAt") or current) <= REQUEST_TIMEOUT:
                continue
            self._pending.pop(request_id, None)
            job = self._jobs.get(str(entry.get("jobId") or ""))
            if job is not None and job.active():
                job.poll_pending = False
                self._fail_job(job, {"code": "request-timeout",
                                     "reason": f"{entry.get('op')} 请求超时；"
                                               "不会自动重放 start/stop",
                                     "detail": {}})
                changed = True
        for job in list(self._jobs.values()):
            if job.fetching_result:
                requested_at = job.result_requested_at
                if requested_at is not None and \
                        current - requested_at > REQUEST_TIMEOUT:
                    self._fail_job(job, {"code": "result-timeout",
                                         "reason": "结果下载超时；不会自动重放 start",
                                         "detail": {}})
                    changed = True
                continue
            if job.state == "starting" and job.sent_at is not None and \
                    current - job.sent_at > START_TIMEOUT:
                self._fail_job(job, {"code": "start-timeout",
                                     "reason": "启动响应超时；不会自动重放 start",
                                     "detail": {}})
                changed = True
                continue
            if job.state == "stopping":
                if job.stop_deadline is not None and current > job.stop_deadline:
                    self._fail_job(job, {"code": "stop-timeout",
                                         "reason": "停止超时：未收到 canceled；不会重放 stop",
                                         "detail": {}})
                    changed = True
                    continue
                if job.poll_at is None or current >= job.poll_at:
                    if not job.poll_pending:
                        job.poll_pending = True
                        job.poll_at = None
                        self._issue("get", {"jobId": job.job_id}, purpose="get",
                                    job=job, feature_id=job.owner)
                        changed = True
                continue
            if job.active() and job.job_id and not job.poll_pending and \
                    job.poll_at is not None and current >= job.poll_at:
                job.poll_pending = True
                job.poll_at = None
                self._issue("get", {"jobId": job.job_id}, purpose="get",
                            job=job, feature_id=job.owner)
                changed = True
        before = len(self._queue)
        self._schedule()
        if len(self._queue) != before:
            changed = True
        if changed:
            self._changed()

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        self._live_requested.clear();self._live_due.clear()
        for job in self._active_jobs():
            if job.job_id:
                try:
                    self._call("stop", {"jobId": job.job_id})
                except Exception:  # noqa: BLE001 - best effort, no replay
                    pass
                job.state = "stopping"
        self._queue.clear()
        self._pending.clear()
        for owner in list(self._results):
            self._drop_raw(owner)
        self._notify_safe("info", "功能运行时已关闭", "feature runtime shutdown")

    # ------------------------------------------------------------------
    # events (event_trigger monitor; event service forwarded by the Lead)
    # ------------------------------------------------------------------
    def on_events(self, events: Any) -> None:
        items: list[dict[str, Any]] = []
        if isinstance(events, dict):
            events = events.get("events")
        if isinstance(events, (list, tuple)):
            for item in events:
                if isinstance(item, dict):
                    items.append(dict(item))
        self._events = items[:MAX_EVENTS]
        if self._results and "event_trigger" in self._results:
            self._results["event_trigger"]["chart"] = self._event_chart()
        self._changed()

    def set_events(self, events: Any) -> None:
        self.on_events(events)

    def events(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._events]

    def refresh_events(self) -> list[dict[str, Any]]:
        self._messages["event_trigger"] = _bilingual(
            "事件列表/下载/确认由事件链（event.list/get/download/ack + 48121）提供；"
            "监测任务不轮询 feature.result。",
            "Events come from the event chain; monitoring never polls feature.result.")
        self._changed()
        return self.events()

    def _event_chart(self) -> dict[str, Any]:
        feature = self.catalog.feature("event_trigger")
        chart = decode_result(feature, {"schema": {"actualProducerLayout": {}}}, [],
                              variant={})
        items = []
        total = len(self._events)
        for index, event in enumerate(self._events):
            event_id = event.get("eventId") or event.get("id")
            reason = str(event.get("reason") or event.get("kind") or "")
            state = str(event.get("state") or "")
            download = event.get("downloadState") or (
                "acked" if event.get("acknowledged") or event.get("acked") else "pending")
            kind = "info"
            lowered = (reason + " " + state).lower()
            if any(word in lowered for word in ("fail", "error", "fault")):
                kind = "error"
            elif any(word in lowered for word in ("lost", "drop", "overrun", "warn")):
                kind = "warn"
            position = float(index) / float(total - 1) if total > 1 else 0.0
            items.append({
                "position01": round(position, 6),
                  "label": (str(event.get("displayName") or "") or reason or state or f"事件 {event_id}")[:80],
                "kind": kind,
                "downloadState": str(download),
                "detail": json.dumps({key: event.get(key) for key in
                                      ("eventId", "reason", "state", "firstSample",
                                       "lastSample") if event.get(key) is not None},
                                     ensure_ascii=False)[:200],
            })
        chart.pop("decodeMeta", None)
        chart["events"] = items
        monitor=self._active_feature_job("event_trigger")
        running=bool(monitor and monitor.active())
        chart["subtitle"] = f"{total} 个事件 · "+("监测已开启" if running else "监测未开启")
        chart["emptyReason"] = "背景学习/变化监测运行中，等待事件片段保存" if running else "尚无事件，点击学习背景并监测"
        chart["text"] = chart["emptyReason"] if not total else ""
        return seal_chart(chart)

    # ------------------------------------------------------------------
    # bridge responses
    # ------------------------------------------------------------------
    def on_response(self, request_id: str, op: str | None = None,
                    result: Any = None, error: Any = None) -> bool:
        """Route one bridge completion.  Returns True when consumed."""
        request_id = str(request_id or "")
        entry = self._pending.pop(request_id, None)
        if entry is None:
            return False
        purpose = str(entry.get("purpose") or "")
        feature_id = str(entry.get("featureId") or "")
        job = self._jobs.get(str(entry.get("jobId") or "")
                              or str(entry.get("pendingKey") or ""))
        if op is not None and str(op):
            entry["op"] = str(op)
        if job is not None:
            job.poll_pending = False
        changed = True
        try:
            if error is not None:
                changed = self._handle_error(entry, job, error)
            elif purpose == "list":
                self._catalog_pending = False
                self.set_features(result if result is not None else {})
            elif purpose == "start":
                changed = self._on_start(job, feature_id, result)
            elif purpose == "get":
                changed = self._on_get(job, result)
            elif purpose == "stop":
                changed = self._on_stop(job, result)
            elif purpose == "result":
                changed = self._on_result(job, result)
            elif purpose == "release":
                changed = False
            else:
                changed = False
        except Exception as exc:  # noqa: BLE001 - never kill the UI thread
            if job is not None:
                self._fail_job(job, {"code": "runtime-error",
                                     "reason": f"{type(exc).__name__}: {exc}"[:300],
                                     "detail": {}})
            else:
                self._notify_safe("error", "功能响应处理失败", f"{purpose}: {exc}")
            changed = True
        if changed:
            self._changed()
        return True

    def _monitor_completed(self, job: _Job) -> bool:
        """event_trigger is continuous: a completed state is an abnormal end."""
        job.completed_at = self._clock()
        if job.stop_requested:
            job.state = "canceled"
            self._cleanup_after_terminal(job)
            self._messages[job.owner] = _bilingual(
                "监测任务已停止（canceled）；事件记录保持在事件链中。",
                "Monitoring stopped (canceled); records stay in the event chain.")
            return True
        job.state = "running"
        self._fail_job(job, {"code": "monitor-ended-unexpectedly",
                             "reason": "监测任务不应结束：未请求停止却收到 completed，"
                                       "不显示为成功且不重放",
                             "detail": {}})
        return True

    def _on_start(self, job: _Job | None, feature_id: str, result: Any) -> bool:
        if job is None:
            return False
        if not isinstance(result, dict):
            self._fail_job(job, {"code": "feature-start-identity",
                                 "reason": "启动响应不是对象", "detail": {}})
            return True
        job_id = result.get("jobId")
        if not isinstance(job_id, str) or not job_id:
            self._fail_job(job, {"code": "feature-start-identity",
                                 "reason": "启动响应缺少 jobId", "detail": {}})
            return True
        reported_feature = result.get("featureId")
        if reported_feature is not None and str(reported_feature) != job.feature_id:
            self._fail_job(job, {"code": "feature-start-identity",
                                 "reason": "启动响应 featureId 不匹配", "detail": {}})
            return True
        source_kind = result.get("sourceKind")
        if source_kind is not None and source_kind not in ALLOWED_SOURCE_KINDS:
            self._fail_job(job, {"code": "feature-start-identity",
                                 "reason": "sourceKind 非法", "detail": {}})
            return True
        if not job.stop_requested and job.owner in self._auto_input_features and isinstance(result.get("selectedChannel"),int):
            selected=result["selectedChannel"]
            if 0<=selected<6:
                job.params["channel"]=selected
                self._input_channels[job.owner]={"channel":selected,"auto":bool(result.get("autoSelected")) or bool(self._input_channels.get(job.owner,{}).get("auto"))}
        job.job_id = job_id
        self._jobs.pop(f"pending-{job.seq}", None)
        self._jobs[job_id] = job
        job.source_kind = str(source_kind or "")
        if job.source_kind:
            self._observed_sources.add(job.source_kind)
            if job.source_kind == "test-fixture":
                self._notify_safe("warn", "测试数据（非实测）",
                                  self._feature_name(job.owner))
        configuration = result.get("configuration")
        if isinstance(configuration, dict):
            job.configuration = self._normalise_configuration(configuration)
        progress = result.get("progress")
        if isinstance(progress, dict):
            job.progress = dict(progress)
        state = str(result.get("state") or "accepted")
        job.state = state if state in ("running", "accepted", "completed",
                                       "failed", "canceled") else "accepted"
        if job.state == "completed" and job.configuration:
            # A start response may already be terminal (e.g. capability); that
            # configuration is the immutable completed snapshot.
            job.final_configuration = dict(job.configuration)
        now = self._clock()
        if job.stop_requested:
            if job.state not in ("completed", "failed", "canceled"):
                self._request_stop(job)
            else:
                job.state = "stopped"
                self._cleanup_after_terminal(job)
            return True
        if job.state == "completed":
            if not job.expected_result:
                return self._monitor_completed(job)
            # The task is done, but the immutable result is not decoded yet: stay
            # "running" until the chart payload exists so the UI never shows a
            # completed state with a stale/empty chart.
            job.state = "running"
            job.fetching_result = True
            self._request_result(job)
            return True
        if job.state in ("failed", "canceled"):
            error = result.get("error") if isinstance(result.get("error"), dict) else {}
            if job.state == "failed":
                job.error = {"code": str(error.get("code") or "job-failed"),
                             "reason": str(error.get("reason") or "任务执行失败")}
            job.completed_at = now
            self._cleanup_after_terminal(job)
            self._messages[job.owner] = _bilingual(
                "设备任务失败" if job.state == "failed" else "设备任务已取消",
                "Device job failed" if job.state == "failed" else "Device job canceled")
            return True
        job.poll_at = now + POLL_INITIAL
        job.poll_interval = POLL_INITIAL
        self._messages[job.owner] = _bilingual(
            "已受理：正在读取设备结果…",
            "Accepted: reading device results…")
        return True

    def _on_get(self, job: _Job | None, result: Any) -> bool:
        if job is None:
            return False
        if not isinstance(result, dict):
            self._fail_job(job, {"code": "feature-get-identity",
                                 "reason": "get 响应不是对象", "detail": {}})
            return True
        reported = result.get("jobId")
        if reported is not None and str(reported) != job.job_id:
            self._fail_job(job, {"code": "feature-get-identity",
                                 "reason": "get 响应 jobId 不匹配", "detail": {}})
            return True
        reported_feature = result.get("featureId")
        if reported_feature is not None and str(reported_feature) != job.feature_id:
            self._fail_job(job, {"code": "feature-get-identity",
                                 "reason": "get 响应 featureId 不匹配", "detail": {}})
            return True
        source_kind = result.get("sourceKind")
        if source_kind is not None:
            if source_kind not in ALLOWED_SOURCE_KINDS:
                self._fail_job(job, {"code": "feature-get-identity",
                                     "reason": "get 响应 sourceKind 非法", "detail": {}})
                return True
            if job.source_kind and str(source_kind) != job.source_kind:
                self._fail_job(job, {"code": "feature-get-identity",
                                     "reason": "sourceKind 在任务期间变化", "detail": {}})
                return True
            job.source_kind = str(source_kind)
            self._observed_sources.add(job.source_kind)
        state = str(result.get("state") or "")
        configuration = result.get("configuration")
        if isinstance(configuration, dict):
            normalised = self._normalise_configuration(configuration)
            if state == "completed":
                # The completed configuration is the immutable result identity.
                if job.final_configuration is not None and \
                        normalised != job.final_configuration:
                    self._fail_job(job, {"code": "feature-get-identity",
                                         "reason": "完成快照 configuration 在完成后变化",
                                         "detail": {}})
                    return True
                job.final_configuration = normalised
                job.configuration = normalised
            else:
                # The candidate gateway reports provisional session/config/
                # generation/sourceFrame while the task is still running and the
                # real values on completion.  Maturation is legal; the stable job
                # identity (jobId/featureId/sourceKind) is checked above.
                job.configuration = normalised
        progress = result.get("progress")
        if isinstance(progress, dict):
            job.progress = dict(progress)
        now = self._clock()
        if state == "completed":
            if job.stop_requested:
                job.state="stopped";job.fetching_result=False;self._cleanup_after_terminal(job)
                self._messages[job.owner]=_bilingual("测量已停止。","Measurement stopped.")
                return True
            if not job.expected_result:
                return self._monitor_completed(job)
            # A P1 view may finish a read of exactly the same immutable source
            # as the last chart. Do not download/decode it again or mark it fresh.
            previous=self._results.get(job.owner)
            if self._instrument_mode and job.mode=="p1" and job.role=="primary" and job.owner in self._live_requested and previous and previous.get("raw_bytes") and previous.get("sourceKind")==job.source_kind:
                prior=previous.get("configuration") or {};keys=("session","config","generation","sourceFrame")
                if all(job.configuration.get(k) is not None and str(job.configuration.get(k))==str(prior.get(k)) for k in keys) and str(job.configuration.get("sourceFrame")) not in ("0",""):
                    self._complete_job(job)
                    self._cached_p1_downloads_skipped=getattr(self,"_cached_p1_downloads_skipped",0)+1
                    self._live_due[job.owner]=now+.10
                    self._messages[job.owner]=_bilingual("等待下一次PL周期结果 · 保留当前实测图","Waiting for next PL update · retaining current measured chart")
                    return True
            # Keep running until the result pages are decoded (see _on_start).
            job.state = "running"
            job.fetching_result = True
            self._request_result(job)
            return True
        if state == "failed":
            error = result.get("error") if isinstance(result.get("error"), dict) else {}
            if job.owner in self._live_requested and job.owner in {"room_decay","room_clarity","spectral_decay"} and error.get("reason")=="no_valid_impulse_detected":
                job.state="completed";self._cleanup_after_terminal(job)
                self._live_due[job.owner]=self._clock()+0.2
                self._messages[job.owner]=_bilingual("等待下一次拍手或脉冲；尚无新的有效测量","Waiting for clap/impulse; no new valid measurement yet")
                return True
            reason=str(error.get("reason") or "任务执行失败")
            if reason=="no_valid_impulse_detected":reason="没有检测到有效拍手/脉冲，请点击重新测试后再拍一次。"
            self._fail_job(job, {"code": str(error.get("code") or "job-failed"),
                                 "reason": reason,
                                 "detail": {}})
            return True
        if state == "canceled":
            job.state = "canceled"
            job.completed_at = now
            self._cleanup_after_terminal(job)
            self._messages[job.owner] = _bilingual("设备任务已取消。",
                                                   "Device job canceled.")
            return True
        if state in ("running", "accepted", "queued", "capturing", ""):
            if job.state != "stopping":
                job.state = "running"
            next_delay = min(POLL_MAX, max(POLL_INITIAL, job.poll_interval * 2))
            job.poll_interval = next_delay
            job.poll_at = now + (POLL_INITIAL if job.state == "stopping" else next_delay)
            captured=job.progress.get("capturedSamples",0);required=job.progress.get("requiredSamples",0)
            if required and job.progress.get("phase")=="capturing":
                self._messages[job.owner]=_bilingual(f"正在采集 {captured}/{required} 个真实样本",f"Acquiring {captured}/{required} real samples")
            elif job.owner=="event_trigger" and job.progress.get("phase")=="monitoring":
                self._messages[job.owner]=_bilingual("背景学习与变化监测已运行；触发后保存前2秒/后3秒音频", "PL background learning/change monitoring is running; triggered clips retain 2s before and 3s after")
            elif job.owner=="full_das" and job.progress.get("phase")=="computing":
                self._messages[job.owner]=_bilingual("全频空间扫描正在计算，当前实现通常约100秒；需要更快请用带限DAS","Full-band spatial scan usually takes about 100s; use band-limited DAS for faster updates")
            elif job.owner=="spectral_kurtosis" and job.progress.get("phase")=="computing":
                self._messages[job.owner]=_bilingual(f"谱峭度正在累计新帧 {job.progress.get('completedStages',0)}/{job.progress.get('totalStages',8)}，首次通常约8秒", "Accumulating distinct frames for spectral kurtosis; first result usually about 8s")
            elif job.owner=="stipa_experimental" and job.progress.get("phase")=="computing":
                completed=int(job.progress.get("completedStages") or 0);total=int(job.progress.get("totalStages") or 101)
                self._messages[job.owner]=_bilingual(f"录音已完成 · 已完成 {completed}/{total} 阶段",f"Recording complete · {completed}/{total} stages completed")
            elif job.owner in {"room_decay","room_clarity","spectral_decay"}:
                self._messages[job.owner]=_bilingual("已捕获瞬态，正在检查衰减" if job.progress.get('excitationDetected') else "采集结束，正在确认脉冲及计算", "Transient captured; checking decay" if job.progress.get('excitationDetected') else "Capture finished; validating impulse")
            elif job.progress.get("phase"):
                phases={"preparing":("正在准备设备运算","Preparing device execution"),"computing":("PL正在计算","PL computing"),"restoring":("正在恢复调度","Restoring scheduling"),"reading":("正在读取最新结果","Reading latest result")}
                self._messages[job.owner]=_bilingual(*phases.get(job.progress['phase'],("正在测量","Measuring")))
            return True
        # Unknown state: keep polling but surface it explicitly.
        job.poll_at = now + POLL_MAX
        self._notify_safe("warn", "未知任务状态", state)
        return True

    def _on_stop(self, job: _Job | None, result: Any) -> bool:
        if job is None:
            return False
        now = self._clock()
        job.state = "stopping"
        job.poll_at = now + POLL_INITIAL
        job.poll_interval = POLL_INITIAL
        self._messages[job.owner] = _bilingual(
            "停止请求已受理：等待 canceled…", "Stop accepted: waiting for canceled…")
        return True

    def _request_result(self, job: _Job) -> None:
        if job.result_requested:
            return
        job.result_requested = True
        job.result_requested_at = self._clock()
        self._issue("result", {"jobId": job.job_id}, purpose="result", job=job,
                    feature_id=job.owner)

    def _on_result(self, job: _Job | None, result: Any) -> bool:
        if job is None:
            return False
        if job.stop_requested or (self._stream_active and job.owner in {"fft","io_pcm","stft","levels_core","levels_extended"}):
            if isinstance(result,dict):
                handle=(result.get("dataRef") or {}).get("handleId")
                if handle:self._release(handle)
            job.fetching_result=False;job.state="stopped" if job.stop_requested else "completed";self._cleanup_after_terminal(job)
            return True
        if not isinstance(result, dict):
            return self._retry_result(job, "result 响应不是对象")
        if not job.expected_result:
            self._fail_job(job, {"code": "monitor-result-unexpected",
                                 "reason": "监测任务不请求 feature.result；"
                                           "收到意外结果，丢弃（不重放）",
                                 "detail": {}})
            return True
        pages_mode = False
        if result.get("pages") is not None:
            try:
                words = self._assemble_pages(job, result.get("pages"))
            except DecodeError as exc:
                return self._retry_result(job, f"分页校验失败: {exc}")
            result = dict(result)
            result["words"] = words
            pages_mode = True
        job_id = result.get("jobId")
        if not isinstance(job_id, str) or job_id != job.job_id:
            self._fail_job(job, {"code": "feature-result-identity",
                                 "reason": "结果 jobId 与任务不匹配（丢弃，不重放）",
                                 "detail": {}})
            return True
        reported_feature = result.get("featureId")
        if reported_feature is not None and str(reported_feature) != job.feature_id:
            self._fail_job(job, {"code": "feature-result-identity",
                                 "reason": "结果 featureId 不匹配（丢弃）", "detail": {}})
            return True
        source_kind = result.get("sourceKind")
        if source_kind not in ALLOWED_SOURCE_KINDS:
            self._fail_job(job, {"code": "feature-result-source",
                                 "reason": "结果 sourceKind 非法或缺失", "detail": {}})
            return True
        if job.source_kind and str(source_kind) != job.source_kind:
            self._fail_job(job, {"code": "feature-result-identity",
                                 "reason": "结果 sourceKind 与任务不一致", "detail": {}})
            return True
        job.source_kind = str(source_kind)
        self._observed_sources.add(job.source_kind)
        total = result.get("totalWords")
        if not isinstance(total, int) or isinstance(total, bool) or total < 0 or \
                total > MAX_RESULT_WORDS:
            return self._retry_result(job, "totalWords 非法")
        configuration = result.get("configuration")
        if not isinstance(configuration, dict):
            return self._retry_result(job, "configuration 缺失")
        normalised = self._normalise_configuration(configuration)
        final = job.final_configuration
        if final is not None and normalised != final:
            self._fail_job(job, {"code": "feature-result-identity",
                                 "reason": "结果 configuration 与已完成快照不一致",
                                 "detail": {}})
            return True
        job.final_configuration = normalised
        job.configuration = normalised
        schema = result.get("schema")
        if not isinstance(schema, dict):
            return self._retry_result(job, "schema 缺失")
        job.schema = dict(schema)
        data_ref = result.get("dataRef") if isinstance(result.get("dataRef"), dict) else {}
        handle_id = data_ref.get("handleId") if isinstance(data_ref, dict) else None
        inline_words = result.get("words") if isinstance(result.get("words"), list) else None
        if isinstance(data_ref.get("count"), int) and data_ref["count"] != total:
            return self._retry_result(job, "dataRef.count 与 totalWords 不一致")
        raw_bytes = b""
        words: list[int] = []
        if pages_mode or inline_words is not None:
            words = [int(word) & 0xFFFFFFFF for word in (inline_words or [])]
            if len(words) != total:
                return self._retry_result(job, "内联 words 数量与 totalWords 不一致")
            if words:
                raw_bytes = struct.pack("<" + "I" * len(words), *words)
        else:
            if total and (not isinstance(handle_id, str) or not handle_id):
                return self._retry_result(job, "dataRef.handleId 缺失")
            if total:
                try:
                    raw_bytes = self._read_words(handle_id, total)
                except Exception as exc:  # noqa: BLE001
                    if isinstance(handle_id, str) and handle_id:
                        self._release(handle_id)
                    return self._retry_result(job, f"结果读取失败: {exc}")
            if isinstance(handle_id, str) and handle_id:
                self._release(handle_id)
            words = u32_words(raw_bytes)
        job.total_words = total
        job.completed_at = self._clock()
        reference = self._references.get(job.owner) or {}
        variant = {"id": job.variant_id, "params": dict(job.params),
                   "role": job.role, "progress": dict(job.progress),
                   "jobId": job.job_id}
        # A STIPA reference job runs the io_pcm device feature; decode it with
        # the io_pcm view spec while the flow state stays on stipa_experimental.
        decode_feature = (self.catalog.feature(job.feature_id)
                          if job.feature_id and job.feature_id != job.owner
                          else self.catalog.feature(job.owner))
        try:
            chart = decode_result(decode_feature, {
                "jobId": job.job_id, "featureId": job.feature_id,
                "state": "completed", "sourceKind": job.source_kind,
                "configuration": dict(job.configuration), "schema": job.schema,
                "totalWords": total, "dataRef": dict(data_ref or {}),
            }, words, reference=reference, variant=variant)
        except Exception as exc:  # noqa: BLE001 - fall back to explicit raw payload
            chart = {"kind": str(decode_feature.get("chart") or "raw"),
                     "available": True, "chartRevision": "error",
                     "title": self._feature_name(job.owner),
                     "reason": f"解码失败: {type(exc).__name__}: {exc}",
                     "emptyReason": f"解码失败: {type(exc).__name__}: {exc}",
                     "words": [], "series": [], "categories": [], "scalarRows": [],
                     "markers": [], "referenceLines": [], "referenceBands": [],
                     "frames": [], "xAxis": {}, "yAxis": {}, "text": ""}
        decode_meta = chart.pop("decodeMeta", {}) if isinstance(chart, dict) else {}
        job.fetching_result = False
        if job.role == "reference":
            self._live_requested.discard(job.owner)
            self._live_due.pop(job.owner,None)
            self._auto_stopped.add(job.owner)
            self._save_reference(job, words, chart, decode_meta)
            self._cleanup_after_terminal(job)
            job.state = "completed"
            self._messages[job.owner] = _bilingual(
                "参考已建立并受保护；普通刷新不会释放该参考。",
                "Reference captured and protected; ordinary refresh never releases it.")
            return True
        self._store_result(job, chart, decode_meta, raw_bytes)
        self._cleanup_after_terminal(job)
        job.state = "completed"
        if job.role == "variant":
            # Start the next independent dual-variant run only after this job is
            # terminal so the exclusive-slot rule accepts it immediately.
            self._variant_completed(job, chart)
        if job.owner in self._live_requested and not job.stop_requested:
            if not self._active_feature_job(job.owner):
                self._live_due[job.owner]=self._clock()+0.05
            self._messages[job.owner]=_bilingual("持续测量中 · 显示最新设备结果","Measuring continuously · latest device result")
            protected={str(r.get("jobId")) for r in self._references.values()}
            for key,old in list(self._jobs.items()):
                if old is not job and old.owner==job.owner and old.state in TERMINAL_STATES and old.job_id not in protected and old.role!="reference":self._jobs.pop(key,None)
            return True
        chart_valid = bool(chart.get("resultValid", True)) if isinstance(chart, dict) else True
        reason_zh = str(chart.get("invalidReason") or "").strip() if isinstance(chart, dict) else ""
        reason_en = str(chart.get("invalidReasonEn") or "").strip() if isinstance(chart, dict) else ""
        if not chart_valid:
            detail = reason_zh or "原因未识别，请重新测量。"
            detail_en = reason_en or "reason not identified; please measure again."
            self._messages[job.owner] = _bilingual(
                "处理完成，但测量无效：" + detail,
                "Processing completed; measurement invalid: " + detail_en)
            self._notify_safe("warn", "测量完成但无效", detail)
        else:
            self._messages[job.owner] = _bilingual(
                "测量完成。" + ("（测试数据，非实测）" if job.source_kind == "test-fixture" else ""),
                "Measurement completed." + (" (test data, not measured)"
                                            if job.source_kind == "test-fixture" else ""))
            self._notify_safe("info", "测量完成", self._feature_name(job.owner))
        return True

    def _assemble_pages(self, job: _Job, pages: Any) -> list[int]:
        assembler = ResultPageAssembler(job.job_id, job.feature_id)
        for page in pages if isinstance(pages, (list, tuple)) else []:
            if assembler.add(page):
                break
        if not assembler.complete:
            raise DecodeError("feature-result-pagination: page chain did not terminate")
        return assembler.words

    def _retry_result(self, job: _Job, why: str) -> bool:
        if job.result_retries >= 2:
            self._fail_job(job, {"code": "feature-result-invalid",
                                 "reason": why, "detail": {}})
            return True
        job.result_retries += 1
        # A validation retry must release the in-flight result request: while
        # fetching_result stays True tick() never re-polls and the job dies with
        # a result-timeout instead of using its second attempt.
        job.fetching_result = False
        job.result_requested = False
        job.result_requested_at = None
        job.poll_at = self._clock() + POLL_INITIAL * job.result_retries
        job.state = "running"
        self._notify_safe("warn", "结果获取重试", why)
        return True

    def _store_result(self, job: _Job, chart: dict[str, Any],
                      decode_meta: dict[str, Any], raw_bytes: bytes) -> None:
        now = self._clock()
        previous=self._results.get(job.owner)
        if previous and previous.get("configuration")==job.configuration:
            # Reading an unchanged cached P1 frame is not a fresh measurement.
            return
        trend_fields={"energy_change":("power_FS2","delta_FS2"),"band_tracking":("power_FS2",),"frequency_tracking":("peak_hz",),"frequency_drift":("drift_hz_per_second",),"centroid":("centroid_hz",),"flatness":("flatness",)}
        if job.owner in trend_fields:
            fields=trend_fields[job.owner];history=self._scalar_history.setdefault(job.owner,[])
            signature=(job.source_kind,job.configuration.get("session"),json.dumps(getattr(job,"params",{}),sort_keys=True),json.dumps(job.schema.get("axes",{}),sort_keys=True))
            if history and history[-1]["identity"]!=signature:history.clear()
            values={r.get("label"):r for r in chart.get("scalarRows",[])}
            history.append({"t":now,"identity":signature,"values":{k:values[k].get("value") if values.get(k,{}).get("valid") else None for k in fields}})
            del history[:-180]
            origin=history[0]["t"];series=[];valid_y=[]
            for k in fields:
                pts=[[round(row["t"]-origin,3),row["values"][k]] for row in history if row["values"][k] is not None]
                valid_y.extend(v for _,v in pts)
                series.append({"name":values.get(k,{}).get("displayLabel",k),"points":pts,"role":"history","unit":values.get(k,{}).get("unit","")})
            shown={"energy_change":("power_FS2","previous_power_FS2","delta_FS2"),"band_tracking":("power_FS2","delta_FS2","delta_valid"),"frequency_tracking":("peak_hz","peak_bin_power","flatness"),"frequency_drift":("peak_hz","delta_hz","drift_hz_per_second"),"flatness":("flatness","peak_hz"),"centroid":("centroid_hz","peak_hz")}[job.owner]
            chart["scalarRows"]=[values[k] for k in shown if k in values]
            chart["kind"]="scalar-trend";chart["series"]=series
            chart["xAxis"]={"min":0,"max":max(1,now-origin),"unit":"s","label":"接收时间"}
            lo=min(valid_y) if valid_y else 0;hi=max(valid_y) if valid_y else 1;pad=max(abs(hi-lo)*.1,abs(hi)*.02,1.e-12)
            chart["yAxis"]={"min":lo-pad,"max":hi+pad,"unit":values.get(fields[0],{}).get("unit",""),"label":"设备结果"}
            chart["subtitle"]="设备标量随时间变化 · 保留最近180次新结果；横轴为PC接收时间"
            chart=seal_chart(chart)
        result = {
            "jobId": job.job_id,
            "featureId": job.owner,
            "totalWords": job.total_words,
            "schemaKind": str(job.schema.get("kind") or ""),
            "units": str(decode_meta.get("units") or ""),
            "chart": chart,
            "decodeMeta": decode_meta,
            "raw_bytes": raw_bytes,
            "sourceKind": job.source_kind,
            "configuration": dict(job.configuration),
            "capturedAt": now,
            "completedAt": now,
            "progress": dict(job.progress),
            "variantId": job.variant_id,
            "inputSelection":dict(self._input_channels.get(job.owner,{})),
        }
        if job.owner in {"band_das","spatial_grid","spatial_peaks"}:result["spaceSchema"]=dict(job.schema)
        if job.owner in {"room_decay","room_clarity"}:
            result["roomSchema"]=dict(job.schema)
            result["sourceFeatureId"]=job.feature_id
        previous = self._results.get(job.owner)
        if previous:
            self._raw_total -= len(previous.get("raw_bytes") or b"")
            if job.owner in self._raw_order:
                self._raw_order.remove(job.owner)
        self._results[job.owner] = result
        self._history_features.discard(job.owner)
        self._raw_total += len(raw_bytes)
        self._raw_order.append(job.owner)
        self._evict_raw()
        self._errors.pop(job.owner, None)
        self._apply_view_options(job.owner)

    def _evict_raw(self) -> None:
        while self._raw_total > RAW_BUDGET_BYTES and self._raw_order:
            owner = self._raw_order[0]
            if owner == self._open_feature or owner in self._references:
                self._raw_order.append(self._raw_order.pop(0))
                if all(item == self._open_feature or item in self._references
                       for item in self._raw_order):
                    break
                continue
            self._drop_raw(owner)
            if owner in self._raw_order:
                self._raw_order.remove(owner)

    def _drop_raw(self, owner: str) -> None:
        result = self._results.get(owner)
        if not result:
            return
        raw = result.get("raw_bytes") or b""
        if raw:
            self._raw_total -= len(raw)
            result["raw_bytes"] = b""
        if owner in self._raw_order:
            self._raw_order.remove(owner)

    def _save_reference(self, job: _Job, words: list[int],
                        chart: dict[str, Any], decode_meta: dict[str, Any]) -> None:
        keep_words = job.feature_id != "io_pcm"
        self._references[job.owner] = {
            "jobId": job.job_id,
            "featureId": job.feature_id,
            "words": list(words) if keep_words else [],
            "chart": chart,
            "params": dict(job.params),
            "sourceKind": job.source_kind,
            "configuration": dict(job.configuration),
            "schema": dict(job.schema),
            "decodeMeta": decode_meta,
            "createdAt": self._clock(),
        }
        self._messages[job.owner] = _bilingual(
            "参考已保存并受保护（A/B、相对隔声、STIPA 参考不会被普通刷新释放）。",
            "Reference saved and protected (never released by ordinary refresh).")
        self._notify_safe("info", "参考已保存", self._feature_name(job.owner))

    def _clear_reference(self, owner: str, note: str) -> None:
        if owner in self._references:
            self._references.pop(owner, None)
            self._reference_notes[owner] = str(note)
            self._messages[owner] = {
                "zh": note, "en": "Reference cleared; capture a new reference."}
            self._notify_safe("warn", "参考已失效", note)

    def _variant_completed(self, job: _Job, chart: dict[str, Any]) -> None:
        if job.owner=="frequency_time_weighting" and job.variant_id in {"A","C","Z"}:
            rows={r.get("label"):r for r in chart.get("scalarRows",[])}
            level=rows.get("计权电平",{})
            if level.get("valid") and isinstance(level.get("value"),(int,float)):
                key=job.variant_id+":"+str(job.params.get("channel",0))
                history=self._weighting_history.setdefault(key,[]);history.append((self._clock(),float(level["value"])));del history[:-120]
                start=history[0][0]
                trend={"render":"line","title":job.variant_id+"计权电平随时间变化","series":[{"name":job.variant_id+"电平","points":[[t-start,y] for t,y in history],"color":"#57C8FF"}],"xAxis":{"min":0,"max":max(1,self._clock()-start),"unit":"s","label":"接收时间"},"yAxis":{"min":-120,"max":0,"label":"数字电平","unit":"dBFS"}}
                chart=dict(chart);chart["panels"]=[trend]+list(chart.get("panels",[]))[:1]
        variants = self._variants.setdefault(job.owner, [])
        for variant in variants:
            if str(variant.get("id") or "") == job.variant_id:
                variant["state"] = "completed"
                variant["chart"] = {key: value for key, value in chart.items()
                                    if key != "decodeMeta"}
        pending = self._variant_pending.get(job.owner) or []
        if pending:
            next_run = pending.pop(0)
            feature = self.catalog.feature(job.owner)
            self._start_primary(feature, next_run, owner=job.owner, role="variant")
            for variant in variants:
                if str(variant.get("id") or "") == str(next_run.get("variantId") or ""):
                    variant["state"] = "running"

    def _complete_job(self, job: _Job) -> None:
        job.state = "completed"
        job.completed_at = self._clock()
        self._cleanup_after_terminal(job)

    # ------------------------------------------------------------------
    # errors / failures / cleanup
    # ------------------------------------------------------------------
    def _handle_error(self, entry: dict[str, Any], job: _Job | None,
                      error: Any) -> bool:
        info = _clean_error(error)
        code = info["code"]
        if code=="not_ready" and job is not None and job.params.get("autoChannel"):
            info["reason"]="输入自检暂未取得合格通道；请检查六路输入质量后重新开始"
        if code == "not_connected":
            self._on_capability_lost(False)
            if job is not None and job.active():
                self._fail_job(job, info)
            self._changed()
            return True
        if job is None:
            self._notify_safe("error", "功能请求失败", f"{code}: {info['reason']}")
            return True
        if code == "busy" and entry.get("purpose") == "start":
            job.state = "queued"
            job.poll_at = None
            job.request_id = ""
            self._jobs.pop(job.job_id, None)
            self._queue.insert(0, job)
            job.job_id = ""
            job.sent_at = None
            self._messages[job.owner] = _bilingual(
                "设备忙：等待任务槽（8 槽受限）…", "Device busy: waiting for a bounded slot…")
            return True
        if code == "job_not_found":
            self._handle_job_not_found(job, info)
            return True
        if code == "bad_state" and entry.get("purpose") == "result":
            return self._retry_result(job, info.get("reason") or "任务尚未完成")
        self._fail_job(job, info)
        return True

    def _handle_job_not_found(self, job: _Job, info: dict[str, Any]) -> None:
        if job.stop_requested:
            job.state="stopped";self._cleanup_after_terminal(job)
            self._messages[job.owner]=_bilingual("设备已无该任务，停止完成。","Device no longer has this job; stopped.")
            return
        reference = self._references.get(job.owner) or {}
        reference_id = str(reference.get("jobId") or "")
        requested_reference = str((job.params or {}).get("referenceJobId") or "")
        if reference_id and reference_id in (str(job.job_id or ""),
                                             requested_reference):
            self._clear_reference(job.owner, "job_not_found：参考任务已不存在，请重建参考")
        self._fail_job(job, {"code": "job_not_found",
                             "reason": "job_not_found：任务已不存在；不会自动重放",
                             "detail": info.get("detail") or {}})

    def _fail_job(self, job: _Job, error: dict[str, Any]) -> None:
        self._live_requested.discard(job.owner);self._live_due.pop(job.owner,None)
        self._auto_stopped.add(job.owner)
        if job.state in ("failed", "canceled", "stopped"):
            return
        if job.state == "completed" and not job.expected_result:
            # A continuous monitor must never be downgraded to a "failed" result
            # task; the abnormal end is handled by _monitor_completed().
            return
        job.state = "failed"
        job.fetching_result = False
        job.completed_at = self._clock()
        job.error = {"code": str(error.get("code") or "job-failed"),
                     "reason": str(error.get("reason") or "任务失败")[:300]}
        self._errors[job.owner] = {"code": job.error["code"],
                                   "reason": job.error["reason"],
                                   "detail": error.get("detail") or {}}
        self._messages[job.owner] = _bilingual(
            f"任务失败：{job.error['reason']}",
            f"Job failed: {job.error['code']}")
        self._cleanup_after_terminal(job)
        if job.role == "variant" and self._variant_pending.get(job.owner):
            for pending in self._variant_pending[job.owner]:
                feature = self.catalog.feature(job.owner)
                failed = self._create_job(job.owner, feature, pending,
                                          role="variant")
                failed.state = "canceled"
                failed.completed_at = self._clock()
                self._jobs[f"canceled-{failed.seq}"] = failed
            self._variant_pending[job.owner] = []
            for variant in self._variants.get(job.owner) or []:
                if variant.get("state") in ("idle", "running"):
                    variant["state"] = "failed"
        self._notify_safe("error", "功能任务失败", job.error["reason"])

    def _cleanup_after_terminal(self, job: _Job) -> None:
        if job in self._queue:
            self._queue.remove(job)
        job.poll_at = None
        job.poll_pending = False
        if job.role == "reference" and job.owner in self._references:
            # reference records own their data; nothing to release here
            pass

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _normalise_configuration(self, configuration: dict[str, Any]) -> dict[str, Any]:
        normalised = dict(configuration or {})
        for key in ("generation", "sourceFrame"):
            value = normalised.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                normalised[key] = str(value)
            elif isinstance(value, str):
                normalised[key] = value
            else:
                normalised[key] = "" if value is None else str(value)
        return normalised

    def _read_words(self, handle_id: str, total_words: int) -> bytes:
        chunks: list[bytes] = []
        offset = 0
        while offset < total_words:
            count = min(READ_CHUNK_WORDS, total_words - offset)
            raw = self._read_buffer(str(handle_id), offset, count)
            if not isinstance(raw, (bytes, bytearray)):
                raise RuntimeError("read_buffer 未返回 bytes")
            raw = bytes(raw)
            if len(raw) != count * 4:
                raise RuntimeError(f"read_buffer 返回 {len(raw)} 字节，期望 {count * 4}")
            chunks.append(raw)
            offset += count
        return b"".join(chunks)

    def _release(self, handle_id: str) -> None:
        try:
            self._release_handle(str(handle_id))
        except Exception:  # noqa: BLE001 - release is best effort
            pass

    def _source_kind(self) -> str:
        if "test-fixture" in self._observed_sources:
            return "test-fixture"
        if "pl-live" in self._observed_sources:
            return "pl-live"
        return "none"

    def _reference_compatible(self, owner: str, feature: dict[str, Any]
                              ) -> tuple[bool, str]:
        reference = self._references.get(owner)
        if not reference:
            return False, "尚未建立参考"
        launch = feature.get("launch") if isinstance(feature.get("launch"), dict) else {}
        base_params = dict(launch.get("params") or {})
        ref_params = dict(reference.get("params") or {})
        for key in ("channel", "channel_i", "channel_j", "sample_rate", "fftSize",
                    "count", "bands"):
            if key in base_params and key in ref_params and \
                    base_params[key] != ref_params[key]:
                return False, f"{key} 不一致"
        ref_feature = str(reference.get("featureId") or "")
        if ref_feature and ref_feature != str(feature.get("featureId") or "") and \
                ref_feature != "io_pcm":
            return False, "参考功能不一致"
        return True, ""

    # ------------------------------------------------------------------
    # QML read models
    # ------------------------------------------------------------------
    def entries(self, page_id: str) -> list[dict[str, Any]]:
        page_id = str(page_id or "")
        out: list[dict[str, Any]] = []
        for item in self.catalog.page_features(page_id):
            feature = item["feature"]
            fid = str(feature.get("featureId") or "")
            available, reason = self._availability(fid)
            job = self._active_feature_job(fid) or self._last_feature_job(fid)
            state = "idle"
            running = False
            if not available:
                state = "unavailable"
            elif job is not None:
                state = str(job.state)
                running = job.active()
            result = self._results.get(fid)
            if state == "idle" and result is not None:
                state = "completed"
            if fid in self._auto_stopped and result is not None and not running:state="stopped"
            if available and fid in self._live_requested and state in ("idle","completed"):
                state="running";running=True
            needs_confirmation = bool(self._required_confirmations(fid)) if available \
                else False
            out.append({
                "featureId": fid,
                "shortZh": str(feature.get("shortZh") or ""),
                "shortEn": str(feature.get("shortEn") or ""),
                "name": str(feature.get("name") or fid),
                "nameEn": str(feature.get("nameEn") or ""),
                "icon": str(feature.get("icon") or "activity"),
                "tier": str(feature.get("tier") or ""),
                "mode": str(feature.get("mode") or ""),
                "page": page_id,
                "group": item.get("group") or "",
                "state": state,
                "available": bool(available),
                "disabledReason": dict(reason) if not available else _empty_reason(),
                "hasResult": bool(result is not None),
                "running": running,
                "needsConfirmation": needs_confirmation,
            })
        return out

    def notify_signature(self) -> tuple:
        """Cheap structural fingerprint of the workspace for change coalescing.

        The live chart payload is intentionally excluded: it changes every
        device frame, while these fields only change on real UI state
        transitions (open/close, job lifecycle, messages, errors, references).
        """
        fid = self._open_feature
        job = None
        if fid:
            job = self._active_feature_job(fid) or self._last_feature_job(fid)
        error = self._errors.get(fid) or {}
        message = self._messages.get(fid) or {}
        progress = (job.progress if job is not None else None) or {}
        return (
            fid, self._page, self._background_feature, bool(self._stream_active),
            str(job.state) if job is not None else "",
            bool(getattr(job, "stop_requested", False)) if job is not None else False,
            progress.get("completedStages"), progress.get("totalStages"),
            progress.get("currentStageIndex"),
            len(self._jobs), len(self._queue),
            str(error.get("code") or ""), str(error.get("reason") or ""),
            str(message.get("zh") or ""), str(message.get("en") or ""),
            len(self._results), len(self._variants.get(fid) or []),
            tuple(sorted(self._references)),
            tuple(sorted(self._auto_stopped)),
            len(self._confirmations),
            tuple(sorted(self._messages)),
            tuple(sorted(self._errors)),
        )
    def restore_result(self, feature_id: str, entry: dict[str, Any]) -> None:
        """Re-seed a retained chart from a previous app session (history only).

        The restored entry never claims a fresh measurement: it is shown paused
        with an explicit note and only the chart payload is restored (no raw
        dataRef)."""
        feature_id = str(feature_id or "")
        chart = (entry or {}).get("chart")
        if not feature_id or not isinstance(chart, dict) or not chart:
            return
        if feature_id not in self.catalog.features:
            return
        decode_meta = {"recipe": "history", "layoutStatus": "restored",
                       "layoutConfirmed": False, "layoutSource": "previous-session",
                       "fieldMap": {}, "notes": ["上次会话历史结果（非本次测量）"],
                       "provenance": ["restored from local history file"],
                       "units": str(chart.get("units") or ""),
                       "validity": "history", "sampleRateSource": ""}
        self._results[feature_id] = {
            "jobId": "history-" + feature_id,
            "featureId": feature_id,
            "totalWords": 0,
            "schemaKind": str((chart.get("kind") or "")), 
            "units": str(chart.get("units") or ""),
            "chart": dict(chart),
            "decodeMeta": decode_meta,
            "raw_bytes": b"",
            "sourceKind": str((entry or {}).get("sourceKind") or "pl-live"),
            "configuration": {},
            "capturedAt": None,
            "completedAt": None,
            "progress": {},
            "variantId": "",
        }
        self._history_features.add(feature_id)
        self._messages[feature_id] = _bilingual(
            "上次会话历史结果（历史，不是本次测量）；连接设备后点击“开始测量”重新测量。",
            "Previous-session history (not a current measurement); connect and press Run to measure again.")
        self._auto_stopped.add(feature_id)

    def status(self) -> dict[str, Any]:
        active = self._active_jobs()
        catalog_complete = bool(self.catalog.device_catalog_complete)
        device_note = ""
        if not self._connected:
            device_note = ("设备未连接；功能入口在连接并取得控制权后可用。")
        elif not self._api_enabled:
            device_note = ("设备软件需要更新：未检测到 echo-features-1 的 featureApi，"
                           "不会用 PC 计算代替 PL 结果。")
        elif not catalog_complete:
            device_note = "功能目录尚未取得或校验失败；请刷新目录。"
        return {
            "apiVersion": self._api_version,
            "interfaceVersion": self.catalog.interface_version,
            "featureApiEnabled": bool(self._connected and self._api_enabled),
            "featureCount": len(self.catalog.features),
            "catalogComplete": catalog_complete,
            "catalogDeviceVersion": self.catalog.device_version,
            "deviceSoftwareNote": device_note,
            "connected": bool(self._connected),
            "taskSlots": {"active": len(active), "max": int(self.catalog.max_slots),
                          "queued": len([j for j in self._queue if j.state == "queued"]),
                          "exclusiveActive": any(job.exclusive for job in active)},
            "sourceKind": self._source_kind(),
            "hardwareState": "NOT_TESTED",
            "pausedReason": self._paused_reason,
        }

    def workspace(self) -> dict[str, Any]:
        if not self._open_feature:
            return {
                "open": False, "featureId": "", "available": False,
                "state": "idle", "lifecycle": "idle", "message": "",
                "error": None, "chart": {"kind": "capability", "text": "",
                                         "emptyReason": "", "series": [],
                                         "chartRevision": "closed"},
                "flow": {"kind": "", "step": 0, "stepId": "", "steps": [],
                         "note": "", "actions": [], "confirmations": []},
                "references": {"referenceJobId": "", "hasReference": False,
                               "compatible": True, "note": ""},
                "freshness": {"sampleIndex": "", "generation": "", "sourceFrame": "",
                              "capturedAt": "", "stale": False},
                "variants": [], "resultSummary": {},
                "notes": [], "provenance": [],
            }
        fid = self._open_feature
        feature = self.catalog.feature(fid)
        available, reason = self._availability(fid)
        result = self._results.get(fid)
        job = self._active_feature_job(fid) or self._last_feature_job(fid)
        state = "idle"
        if not available:
            state = ("stopped" if (result is not None and fid in self._history_features)
                     else "unavailable")
        elif job is not None:
            state = str(job.state)
        elif result is not None:
            state = "completed"
        if fid in self._auto_stopped and result is not None and not self._active_feature_job(fid):state="stopped"
        if available and fid in self._live_requested and state in ("idle","completed"):
            state="running"
        if job is not None and job.role=="reference" and job.state=="completed":
            result=None  # Current A is not a newly measured B; keep old B only in history.
        chart = self._workspace_chart(fid, feature, result, job)
        result_chart = (result or {}).get("chart")
        if not isinstance(result_chart, dict):
            result_chart = {}
        result_valid = bool(result_chart.get("resultValid", True))
        invalid_reason = str(result_chart.get("invalidReason") or "")
        invalid_reason_en = str(result_chart.get("invalidReasonEn") or "")
        if fid == "stipa_experimental":
            # The selected mode defines the stage count even before a job/result
            # exists (idle or reference capture): quick = 15, complete = 101.
            # A live device progress payload or decoded result keeps its own total.
            chart = dict(chart)
            quick = self._ensure_confirmations(fid).get("measurementMode", "complete") == "quick"
            default_total = 15 if quick else 101
            stage = dict(chart.get("stage") or {})
            total = stage.get("total")
            if not isinstance(total, int) or isinstance(total, bool) or total <= 0:
                stage["total"] = default_total
            completed = stage.get("completed")
            if not isinstance(completed, int) or isinstance(completed, bool):
                completed = 0
            stage["completed"] = min(max(completed, 0), stage["total"])
            current = stage.get("current")
            if not isinstance(current, int) or isinstance(current, bool):
                current = stage["completed"]
            stage["current"] = min(max(current, 0), stage["total"])
            if not str(stage.get("label") or "").strip():
                stage["label"] = "STIPA 阶段"
            chart["stage"] = stage

        flow = self._flow_state(fid, feature, result, job)
        references = self._reference_state(fid, feature)
        freshness = self._freshness(fid, result, job)
        variants = [dict(variant) for variant in (self._variants.get(fid) or [])]
        message = self._messages.get(fid) or self._messages.get("__api__") or {}
        if available and not message and state == "idle":
            message = _bilingual("点击运行开始测量（参数固定隐藏）。",
                                 "Press run to start (fixed hidden parameters).")
        error = self._errors.get(fid)
        if error is None and self._messages.get("__api__") and not available:
            error = {"code": "feature-api-unavailable",
                     "reason": self._messages["__api__"]["zh"],
                     "detail": {}}
        decode_meta = (result or {}).get("decodeMeta") or {}
        notes = list(decode_meta.get("notes") or [])
        if fid in self._history_features:
            notes = ["上次会话历史结果（不是本次测量）"] + notes
        if not available and reason.get("zh"):
            notes = [reason["zh"]] + notes
        if result is not None and str(result.get("sourceKind")) == "test-fixture":
            notes = ["测试数据（非实测）"] + notes
        provenance = list(decode_meta.get("provenance") or [])
        disabled_zh = "" if available else reason.get("zh", "")
        elapsed = 0.0
        started = (job.started_at if job is not None else None) or \
            ((result or {}).get("capturedAt"))
        if started is not None:
            end = (job.completed_at if job is not None and job.completed_at is not None
                   else self._clock())
            elapsed = max(0.0, (end - started) * 1000.0)
        elapsed_ms = int(elapsed)
        return {
            "open": True,
            "featureId": fid,
            "name": str(feature.get("name") or fid),
            "shortZh": str(feature.get("shortZh") or ""),
            "shortEn": str(feature.get("shortEn") or ""),
            "nameEn": str(feature.get("nameEn") or ""),
            "icon": str(feature.get("icon") or "activity"),
            "page": str(feature.get("page") or ""),
            "tier": str(feature.get("tier") or ""),
            "mode": str(feature.get("mode") or ""),
            "selectedVariant": self._selected_variants.get(fid,0),
            "noiseReferenceOffsetDb": self._ensure_confirmations(fid).get("noiseReferenceOffsetDb",123.01) if fid=="noise_rating" else 0,
            "measurementMode": self._ensure_confirmations(fid).get("measurementMode", "complete") if fid=="stipa_experimental" else "",
            "manualDirection": dict(self._manual_direction) if fid=="directed_das" else {},
            "inputSelection":dict(self._input_channels.get(fid) or (result or {}).get("inputSelection") or {}),
            "state": state,
            "lifecycle": state,
            "jobRole": job.role if job is not None else "",
            "message": str(message.get("zh") or ""),
            "messageEn": str(message.get("en") or ""),
            "error": ({"code": str(error.get("code") or ""),
                       "reason": str(error.get("reason") or ""),
                       "reasonEn": str(error.get("en") or ""),
                       "detail": error.get("detail") or {}}
                      if error else None),
            "available": bool(available),
            "disabledReason": disabled_zh,
            "disabledReasonI18n": dict(reason),
            "disabledReasonEn": reason.get("en", ""),
            "elapsedMs": elapsed_ms,
            "measurementProgress": dict(job.progress) if job is not None else dict((result or {}).get("progress") or {}),
            "sourceKind": (str((result or {}).get("sourceKind") or "")
                           or str((job.source_kind if job is not None else "") or "none")),
            "validity": str(feature.get("validity") or ""),
            "units": str((result or {}).get("units")
                         or feature.get("units") or ""),
            "notes": notes,
            "provenance": provenance,
            "chart": chart,
            "hasResult": result is not None,
            "resultValid": result_valid,
            "invalidReason": invalid_reason,
            "invalidReasonEn": invalid_reason_en,
            "resultSummary": {
                "jobId": str((result or {}).get("jobId") or ""),
                "totalWords": int((result or {}).get("totalWords") or 0),
                "schemaKind": str((result or {}).get("schemaKind") or ""),
                "units": str((result or {}).get("units") or ""),
            },
            "freshness": freshness,
            "references": references,
            "flow": flow,
            "variants": variants,
            "hardwareState": "NOT_TESTED",
        }

    def _workspace_chart(self, fid: str, feature: dict[str, Any],
                         result: dict[str, Any] | None, job: _Job | None) -> dict[str, Any]:
        if fid == "event_trigger":
            chart = self._event_chart()
            return chart
        if result is not None and fid in self._live_requested:
            return dict(result.get("chart") or {})
        if result is not None and job is not None and (job.active() or job.state=="queued"):
            chart=dict(result.get("chart") or {});chart["pendingUpdate"]=True
            return chart
        if result is not None and job is None:
            return dict(result.get("chart") or {})
        if result is not None and job is not None and job.state in ("failed","canceled"):
            chart=dict(result.get("chart") or {});chart["historicalResult"]=True
            chart["title"]="上次测量（本次未取得新结果） · "+str(chart.get("title", ""))
            chart["resultHint"]="下图保留上次结果，不属于这次失败的测量。";return seal_chart(chart)
        if result is not None and job is not None and job.state in TERMINAL_STATES:
            return dict(result.get("chart") or {})
        reference = self._references.get(fid)
        kind = flow_specs.flow_kind(feature)
        if result is None and reference and (job is None or not job.active()):
            if kind in ("reference_compare", "reference_measure"):
                chart = dict(reference.get("chart") or {})
                chart["subtitle"] = ("已保存的参考（A）；建立比较/测量后显示本次结果"
                                     if kind == "reference_compare"
                                     else "已保存的参考；确认测量链后执行测量")
                return seal_chart(chart)
            if kind == "staged_stipa":
                chart = {
                    "kind": "stipa", "available": True,
                    "title": str(feature.get("name") or fid),
                    "subtitle": "io_pcm 参考已保存；请确认测试信号后执行 101 阶段 STIPA",
                    "units": str(feature.get("units") or ""),
                    "chartRevision": "", "series": [], "categories": [],
                    "scalarRows": [], "markers": [], "referenceLines": [],
                    "referenceBands": [], "frames": [], "xAxis": {}, "yAxis": {},
                    "text": "参考已保存；等待测试信号确认。", "emptyReason": "",
                }
                return seal_chart(chart)
        # Running / queued / failed-without-result placeholder (no stale values).
        chart = {
            "kind": str(feature.get("chart") or "capability"),
            "available": True,
            "title": str(feature.get("name") or fid),
            "subtitle": str(feature.get("validity") or ""),
            "units": str(feature.get("units") or ""),
            "xAxis": {}, "yAxis": {}, "series": [], "categories": [],
            "colorScale": None, "markers": [], "referenceLines": [],
            "referenceBands": [], "frames": [], "scalarRows": [],
            "text": "", "emptyReason": "",
        }
        if job is not None and job.state in ("starting", "accepted", "running"):
            chart["text"] = "运行中：完成前不显示缓存值（失败任务不显示上一次结果）。"
            chart["emptyReason"] = "运行中"
            stage_progress = self._stage_payload(fid, dict(job.progress or {}))
            if stage_progress:
                chart["stage"] = stage_progress
            return seal_chart(chart)
        if job is not None and job.state == "failed":
            chart["text"] = "任务失败：不显示上一次缓存结果。"
            chart["emptyReason"] = "任务失败"
            return seal_chart(chart)
        chart["text"] = "尚未运行。"
        chart["emptyReason"] = "尚未运行"
        return seal_chart(chart)

    def _freshness(self, fid: str, result: dict[str, Any] | None,
                   job: _Job | None) -> dict[str, Any]:
        configuration = dict((result or {}).get("configuration") or {})
        if not configuration and job is not None:
            configuration = dict(job.configuration or {})
        captured_at = (result or {}).get("capturedAt")
        stale = False
        if captured_at is not None:
            limit=1.0 if self._stream_active and fid in self._live_requested else STALE_AFTER_SECONDS
            stale = (not self._connected) or ((self._clock() - float(captured_at)) > limit and \
                not (job is not None and job.active())
            )
        generation = str(configuration.get("generation") or "")
        source_frame = str(configuration.get("sourceFrame") or "")
        return {
            "sampleIndex": str(configuration.get("firstSampleIndex") or source_frame),
            "generation": generation,
            "sourceFrame": source_frame,
            "capturedAt": (str(int(captured_at)) if isinstance(captured_at, (int, float))
                           else ""),
            "stale": bool(stale),
        }

    # -- flow / references ------------------------------------------------
    def _flow_state(self, fid: str, feature: dict[str, Any],
                    result: dict[str, Any] | None, job: _Job | None) -> dict[str, Any]:
        definition = flow_specs.flow_definition(feature)
        kind = definition["kind"]
        values = self._ensure_confirmations(fid)
        step_index = self._step_index(fid, feature, kind, result, job)
        step_ids = definition["stepIds"]
        step_id = step_ids[step_index] if 0 <= step_index < len(step_ids) else ""
        actions = self._flow_actions(fid, feature, kind, result, job, values)
        confirmations = self._flow_confirmations(fid, feature, kind, values, job)
        note = definition["note"]
        if fid == "stipa_experimental":
            quick = self._ensure_confirmations(fid).get("measurementMode", "complete") == "quick"
            if quick:
                note = ("快速体验：15 阶段、500/1000/2000 Hz 三频带估计；先播放配套 STIPA "
                        "测试音轨并录制 8 秒参考，确认测试信号后再录测试并计算。不是认证 STIPA。")
        active_job = job if job is not None and job.active() else None
        return {
            "kind": kind,
            "step": int(step_index),
            "stepId": step_id,
            "steps": [dict(step) for step in definition["steps"]],
            "note": note,
            "actions": actions,
            "confirmations": confirmations,
            "running": bool(active_job) or fid in self._live_requested,
            "stages": (dict(self._stage_progress(fid, active_job))
                       if active_job is not None else {}),
        }

    def _stage_payload(self, fid: str, progress: dict[str, Any]) -> dict[str, Any]:
        """Shared progress payload {completed,total,current,label}.

        Quantities come from the device (completedStages/totalStages/
        currentStageIndex); the PC never derives a filled bar on its own.
        """
        total = progress.get("totalStages")
        if not isinstance(total, int) or isinstance(total, bool) or total <= 0:
            return {}
        try:
            completed = int(progress.get("completedStages") or 0)
            current = progress.get("currentStageIndex")
            current = completed if current is None else int(current)
        except (TypeError, ValueError):
            return {}
        return {"completed": completed, "total": int(total),
                "current": current,
                "label": "STIPA 阶段" if fid == "stipa_experimental" else "阶段"}

    def _stage_progress(self, fid: str, job: _Job | None) -> dict[str, Any]:
        if job is None:
            return {}
        return self._stage_payload(fid, dict(job.progress or {}))

    def _step_index(self, fid: str, feature: dict[str, Any], kind: str,
                    result: dict[str, Any] | None, job: _Job | None) -> int:
        completed = bool(result is not None and (job is None or not job.active()))
        reference = self._references.get(fid)
        values = self._ensure_confirmations(fid)
        if kind == "reference_compare":
            if completed:
                return 2
            return 1 if reference else 0
        if kind == "reference_measure":
            if completed and reference and bool(values.get("chain-confirm")):
                return 3
            if not reference:
                return 0
            return 1 if not bool(values.get("chain-confirm")) else 2
        if kind == "staged_stipa":
            if completed and reference:
                return 3
            if not reference:
                return 0
            return 1 if not bool(values.get("testSignalConfirmed")) else 2
        if kind == "room_stimulus":
            if completed:
                return 2
            return 1 if values.get("stimulus") else 0
        if kind == "dual_variant":
            variants = self._variants.get(fid) or []
            if any(variant.get("state") == "completed" for variant in variants):
                return 1
            return 0
        if kind == "monitor":
            return 1 if job is not None else 0
        return 1 if (completed or (job is not None and job.active())) else 0

    def _flow_actions(self, fid: str, feature: dict[str, Any], kind: str,
                      result: dict[str, Any] | None, job: _Job | None,
                      values: dict[str, Any]) -> list[dict[str, Any]]:
        definition = flow_specs.flow_definition(feature)
        available, reason = self._availability(fid)
        active = (job is not None and job.active()) or fid in self._live_requested
        reference = self._references.get(fid)
        compatible, _ = self._reference_compatible(fid, feature)
        required = set(self._required_confirmations(fid))
        actions: list[dict[str, Any]] = []
        for item in definition["actions"]:
            action = dict(item)
            action_id = str(item["id"])
            enabled = True
            why = _empty_reason()
            if not available:
                enabled, why = False, dict(reason)
            elif action_id == "run":
                enabled = not active
                if active:
                    why = _bilingual("任务运行中", "A job is already running")
                if kind == "reference_compare" and reference and not compatible:
                    enabled, why = False, _bilingual("参考不兼容，请重建参考",
                                                     "Reference incompatible; rebuild it")
                if kind == "reference_measure" and reference and \
                        "chain-confirm" in required:
                    enabled, why = False, dict(CONFIRMATION_REASON["chain-confirm"])
                if kind == "staged_stipa" and reference and \
                        "testSignalConfirmed" in required:
                    enabled, why = False, dict(CONFIRMATION_REASON["testSignalConfirmed"])
                if kind == "dual_variant" and required:
                    cid = sorted(required)[0]
                    enabled, why = False, dict(CONFIRMATION_REASON.get(
                        cid, _bilingual("请先完成流程确认", "Complete confirmations first")))
                if kind == "room_stimulus" and not values.get("stimulus"):
                    enabled, why = False, dict(CONFIRMATION_REASON["stimulus"])
            elif action_id == "stop":
                enabled = bool(active)
                if not active:
                    why = _bilingual("当前无运行任务", "No running job")
            elif action_id == "refresh":
                enabled = not active
                if active:
                    why = _bilingual("任务运行中", "Job running")
            elif action_id == "reference":
                enabled = not active
                if active:
                    why = _bilingual("任务运行中", "Job running")
            elif action_id == "compare":
                enabled = bool(reference) and compatible and not active
                if not reference:
                    why = _bilingual("请先建立参考", "Capture a reference first")
                elif not compatible:
                    why = _bilingual("参考不兼容", "Reference incompatible")
            elif action_id == "measure":
                enabled = bool(reference) and compatible and not active
                if not reference:
                    why = _bilingual("请先建立参考", "Capture a reference first")
                elif required:
                    cid = sorted(required)[0]
                    why = dict(CONFIRMATION_REASON.get(
                        cid, _bilingual("请先完成流程确认", "Complete confirmations first")))
                elif not compatible:
                    why = _bilingual("参考不兼容", "Reference incompatible")
            elif action_id in ("save", "export"):
                enabled = result is not None and not active
                if result is None:
                    why = _bilingual("暂无结果", "No result yet")
            action["enabled"] = bool(enabled)
            action["reason"] = dict(why)
            actions.append(action)
        return actions

    def _flow_confirmations(self, fid: str, feature: dict[str, Any], kind: str,
                            values: dict[str, Any],
                            job: _Job | None) -> list[dict[str, Any]]:
        definition = flow_specs.flow_definition(feature)
        active = job is not None and job.active()
        reference = self._references.get(fid)
        items: list[dict[str, Any]] = []
        for item in definition["confirmations"]:
            confirmation = dict(item)
            cid = str(item["id"])
            stored = values.get(cid)
            if item.get("type") == "enum":
                confirmation["value"] = stored
            else:
                confirmation["value"] = bool(stored)
            enabled = True
            why = _empty_reason()
            if cid == "chain-confirm" and not reference:
                enabled, why = False, _bilingual("请先建立参考", "Capture a reference first")
            elif cid == "testSignalConfirmed" and not reference:
                enabled, why = False, _bilingual("请先完成 io_pcm 参考",
                                                 "Capture the io_pcm reference first")
            elif cid == "stimulus" and active:
                enabled, why = False, _bilingual("任务运行中", "Job running")
            elif cid == "referenceConfirmed" and active:
                enabled, why = False, _bilingual("任务运行中", "Job running")
            confirmation["enabled"] = bool(enabled)
            confirmation["reason"] = dict(why)
            items.append(confirmation)
        return items

    def _reference_state(self, fid: str, feature: dict[str, Any]) -> dict[str, Any]:
        reference = self._references.get(fid)
        if reference:
            compatible, note = self._reference_compatible(fid, feature)
            return {
                "referenceJobId": str(reference.get("jobId") or ""),
                "hasReference": True,
                "compatible": bool(compatible),
                "note": ("参考受保护；普通刷新不会释放" + (f"（{note}）" if note else "")),
            }
        kind = flow_specs.flow_kind(feature)
        stale_note = self._reference_notes.get(fid, "")
        if kind in ("reference_compare", "reference_measure", "staged_stipa"):
            return {"referenceJobId": "", "hasReference": False,
                    "compatible": True,
                    "note": stale_note or "尚未建立参考；先建立并保存参考。"}
        return {"referenceJobId": "", "hasReference": False,
                "compatible": True, "note": ""}

    # ------------------------------------------------------------------
    # raw export
    # ------------------------------------------------------------------
    def export_raw(self, feature_id: str) -> dict[str, Any] | None:
        """Full raw words for explicit user export (never part of workspace())."""
        fid = str(feature_id or "")
        result = self._results.get(fid)
        if result is None:
            result = self._references.get(fid)
            if not result:
                return None
        raw = result.get("raw_bytes") or b""
        words = u32_words(raw) if raw else list(result.get("words") or [])
        total = int(result.get("totalWords") or len(words))
        if not words and total:
            # Raw buffer was evicted from the bounded cache; refuse to fabricate.
            return None
        source_kind = str(result.get("sourceKind") or "none")
        return {
            "featureId": fid,
            "jobId": str(result.get("jobId") or ""),
            "configuration": dict(result.get("configuration") or {}),
            "schema": dict(result.get("schema") or {}),
            "sourceKind": source_kind,
            "totalWords": total,
            "words": words,
            "fixture": source_kind == "test-fixture",
            "hardwareState": "NOT_TESTED",
            "layoutSource": str((result.get("decodeMeta") or {}).get(
                "layoutSource") or ""),
        }

    # ------------------------------------------------------------------
    # test/debug snapshot
    # ------------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        """Compact internal state (tests/evidence only; never sent to QML)."""
        return {
            "openFeature": self._open_feature,
            "page": self._page,
            "connected": self._connected,
            "apiEnabled": self._api_enabled,
            "catalogComplete": self.catalog.device_catalog_complete,
            "jobs": {job.job_id or f"pending-{job.seq}": {
                "featureId": job.feature_id, "owner": job.owner,
                "state": job.state, "role": job.role,
                "variantId": job.variant_id, "exclusive": job.exclusive,
                "sourceKind": job.source_kind, "totalWords": job.total_words,
            } for job in self._jobs.values()},
            "queue": [job.job_id or f"pending-{job.seq}" for job in self._queue],
            "references": {owner: str(reference.get("jobId") or "")
                           for owner, reference in self._references.items()},
            "results": {owner: {
                "jobId": result.get("jobId"),
                "totalWords": result.get("totalWords"),
                "sourceKind": result.get("sourceKind"),
                "retainedRawBytes": len(result.get("raw_bytes") or b""),
            } for owner, result in self._results.items()},
        }
