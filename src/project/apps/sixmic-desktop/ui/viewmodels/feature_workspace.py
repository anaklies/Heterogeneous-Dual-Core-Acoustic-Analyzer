"""QML-facing feature workspace facade (Lead-owned).

Sits between AppViewModel and ui.features.FeatureRuntime.  Responsibilities:

- load the generated 45-feature view spec (page/group classification is the
  prompt's 8 logical categories);
- expose page-scoped icon entries and the single active feature workspace;
- translate runtime payloads to the locked UI vocabulary (zh/en) and attach
  QQuickImageProvider image URLs for 2D rasters;
- adapt FeatureRuntime's call/read callbacks to the frozen BackendBridge;
- NEVER expose measurement parameters: every start uses spec.launch
  (policy=fixed-hidden).  Only documented workflow confirmations are exposed.

The runtime module is imported lazily: a missing/incomplete runtime degrades to
an explicit "feature runtime unavailable" state instead of breaking app load.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any, Callable

from .plot_images import heatmap_image, stft_heatmap_image

STATE_LABELS = {
    "idle": ("待启动", "Idle"),
    "queued": ("等待任务槽", "Queued"),
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

SOURCE_LABELS = {
    "pl-live": ("设备实测", "Device live"),
    "test-fixture": ("测试数据（非实测）", "Test data (not measured)"),
    "file-replay": ("设备录制回放", "Device recording playback"),
    "offline-reference": ("离线参考（非实时）", "Offline reference"),
    "none": ("无数据", "No data"),
}

DEVICE_SOFTWARE_NOTE = (
    "设备软件需要更新：未检测到 echo-features-1 的 featureApi。不会用PC计算代替PL结果。",
    "Device software update required: echo-features-1 featureApi is not available. "
    "PC-side computation is never substituted for PL results.",
)

# STFT live display tuning.  FeatureChart forces the inferno palette for the
# STFT heat map (FeatureChart.forcedPalette(..., "inferno")), so the Python
# display image has to use the same palette or the surface and the colour bar
# disagree.  The image is intentionally small: it is stretched over the plot
# area by Qt Quick, so the per-update Python cost stays in the low milliseconds.
_STFT_DISPLAY_PALETTE = "inferno"
_STFT_IMAGE_HEIGHT = 256
# Display-only raster: 64-128 x 256 is blitted as one image; the decoder's
# numeric contract (1025 bins) is untouched.
_STFT_RASTER_COLUMNS = 128


def _finite_number(value: Any) -> bool:
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) \
            and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _localize(pair: Any, language: str, fallback: str = "") -> str:
    if isinstance(pair, dict):
        zh, en = pair.get("zh", ""), pair.get("en", "")
        return str(zh if language == "zh" else en or fallback)
    if isinstance(pair, (list, tuple)) and len(pair) == 2:
        return str(pair[0] if language == "zh" else pair[1])
    return str(pair if pair is not None else fallback)


class FeatureWorkspaceFacade:
    def __init__(self, spec_path: Path, bridge: Any, images: Any, *,
                 language: Callable[[], str] = lambda: "zh",
                 notify: Callable[[str, str, str], None] | None = None) -> None:
        self._spec_path = Path(spec_path)
        self._bridge = bridge
        self._images = images
        self._language = language
        self._notify = notify or (lambda level, title, detail: None)
        self._pending: dict[str, str] = {}
        self._runtime: Any = None
        self._runtime_error = ""
        self._feature_api: dict[str, Any] = {
            "connected": False, "enabled": False, "version": "", "featureCount": 0,
            "maxResultWordsPerPage": 1024, "catalogPageSize": 8, "reason": "",
        }
        self._chart_cache: dict[str, dict[str, Any]] = {}
        # Cached QML read model (see workspace()); invalidated on every change.
        self._ws_cache: dict[str, Any] | None = None
        self._ws_cache_language = ""
        self._on_change: Callable[[], None] | None = None
        self._spec = self._load_spec()
        self._instantiate_runtime()

    # -- setup -------------------------------------------------------------
    def _load_spec(self) -> dict[str, Any]:
        try:
            spec = json.loads(self._spec_path.read_text(encoding="utf-8"))
            if not isinstance(spec, dict) or len(spec.get("features") or {}) != 45:
                raise ValueError("feature spec must contain 45 features")
            return spec
        except (OSError, ValueError) as exc:
            self._runtime_error = "feature-spec: " + str(exc)[:200]
            return {"version": 0, "features": {}, "pages": {}}

    def _instantiate_runtime(self) -> None:
        try:
            from ui.features import FeatureRuntime  # type: ignore
        except Exception as exc:  # noqa: BLE001 - runtime is delivered by the team
            self._runtime_error = "feature-runtime: " + str(exc)[:200]
            self._runtime = None
            return
        try:
            runtime = FeatureRuntime(
                self._spec,
                call=self._call,
                read_buffer=self._read,
                release_handle=self._release,
                notify=self._runtime_notify,
                instrument_mode=True,
            )
            if hasattr(runtime, "on_change"):
                runtime.on_change(self._emit_changed)
            self._runtime = runtime
        except Exception as exc:  # noqa: BLE001
            self._runtime_error = "feature-runtime-init: " + str(exc)[:200]
            self._runtime = None

    # -- runtime callbacks -------------------------------------------------
    def _emit_changed(self) -> None:
        # One runtime change must rebuild the QML snapshot once, not
        # once per QML binding that reads App.featureWorkspace.
        self._ws_cache = None
        if self._on_change is not None:
            try:
                self._on_change()
            except Exception:  # noqa: BLE001 - UI notification must not break runtime
                pass

    def _runtime_notify(self, level: str, title: str, detail: str = "") -> None:
        try:
            self._notify(str(level), str(title), str(detail))
        except Exception:  # noqa: BLE001
            pass

    def _call(self, op: str, args: dict[str, Any] | None = None) -> str:
        """Issue one bridge call; returns the request id used for correlation."""
        args = dict(args or {})
        bridge = self._bridge
        try:
            if op == "list":
                request_id = bridge.listFeatures()
            elif op == "start":
                request_id = bridge.startFeature(
                    str(args.get("featureId") or ""),
                    json.dumps(args.get("params") or {}, ensure_ascii=False))
            elif op == "stop":
                request_id = bridge.stopFeature(str(args.get("jobId") or ""))
            elif op == "get":
                request_id = bridge.getFeature(str(args.get("jobId") or ""))
            elif op == "result":
                request_id = bridge.getFeatureResult(str(args.get("jobId") or ""))
            elif op == "release":
                request_id = bridge.releaseFeatureResult(str(args.get("handleId") or ""))
            else:
                raise RuntimeError("unsupported feature op: " + op)
        except Exception:  # noqa: BLE001 - surfaces as runtime notification
            self._notify("error", "功能接口不可用", "功能接口调用失败: " + op)
            raise
        self._pending[str(request_id)] = op
        return str(request_id)

    def _read(self, handle_id: str, offset_elements: int = 0,
              count_elements: int = 4096) -> bytes:
        try:
            raw = self._bridge.readBuffer(str(handle_id), int(offset_elements),
                                          int(count_elements))
            return bytes(raw) if raw is not None else b""
        except Exception:  # noqa: BLE001
            return b""

    def _release(self, handle_id: str) -> None:
        try:
            self._call("release", {"handleId": str(handle_id)})
        except Exception:  # noqa: BLE001
            pass

    # -- bridge responses --------------------------------------------------
    def on_response(self, request_id: str, result: Any, error: Any = None) -> bool:
        """Route one feature bridge completion. Returns True if consumed."""
        op = self._pending.pop(str(request_id), None)
        if op is None or self._runtime is None:
            return False
        try:
            self._runtime.on_response(str(request_id), op, result, error)
        except Exception as exc:  # noqa: BLE001 - never kill the UI thread
            self._runtime_error = "feature-runtime-response: " + str(exc)[:200]
        self._emit_changed()
        return True

    # -- connection / capability ------------------------------------------
    def set_connection(self, connected: bool, feature_api: dict[str, Any] | None = None) -> None:
        info = dict(feature_api or {})
        if not connected:
            info = {"connected": False, "enabled": False, "reason": "not-connected"}
        info["connected"] = bool(connected)
        enabled = bool(info.get("enabled")) and bool(info.get("connected"))
        self._feature_api = {
            "connected": bool(connected),
            "enabled": enabled,
            "version": str(info.get("version") or ""),
            "featureCount": int(info.get("featureCount") or 0),
            "maxResultWordsPerPage": int(info.get("maxResultWordsPerPage") or 1024),
            "catalogPageSize": int(info.get("catalogPageSize") or 8),
            "reason": str(info.get("reason") or ""),
        }
        if self._runtime is not None:
            try:
                # set_feature_api carries the connected flag in info; calling
                # set_connection() first would briefly report "connected but
                # featureApi disabled" and flash a false "功能接口不可用" warning.
                self._runtime.set_feature_api(enabled, dict(self._feature_api))
                if connected and enabled:
                    self.refresh_catalog()
            except Exception as exc:  # noqa: BLE001
                self._runtime_error = "feature-runtime-capability: " + str(exc)[:200]
        self._emit_changed()

    def refresh_catalog(self) -> None:
        if self._runtime is None:
            return
        try:
            self._runtime.refresh_catalog()
        except Exception as exc:  # noqa: BLE001
            self._runtime_error = "feature-catalog: " + str(exc)[:200]
        self._emit_changed()

    # -- QML read models ---------------------------------------------------
    def _localize_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        language = str(self._language() or "zh")
        feature_id = str(entry.get("featureId") or "")
        spec = (self._spec.get("features") or {}).get(feature_id) or {}
        item = dict(entry)
        # Tooltip metadata stays data-driven; it is status/units/limits only,
        # never editable measurement parameters.
        item.setdefault("units", str(spec.get("units") or ""))
        item.setdefault("shortName", str(spec.get("shortZh") or feature_id))
        prerequisites = spec.get("prerequisites") or []
        item.setdefault("prerequisitesText", chr(10).join(
            str(item.get("text") or "") for item in prerequisites
            if isinstance(item, dict) and item.get("text")))
        item.setdefault("featureDescription", str(
            spec.get("nameEn") or spec.get("name") or feature_id))
        item.setdefault("tier", str(spec.get("tier") or ""))
        item.setdefault("mode", str(spec.get("mode") or ""))
        item.setdefault("icon", str(spec.get("icon") or "activity"))
        item.setdefault("page", str(spec.get("page") or ""))
        item.setdefault("group", str(spec.get("group") or ""))
        item["shortName"] = _localize(
            {"zh": entry.get("shortZh", ""), "en": entry.get("shortEn", "")},
            language, str(entry.get("name") or entry.get("featureId") or ""))
        item["name"] = _localize(
            {"zh": entry.get("name", ""), "en": entry.get("nameEn", "")},
            language, str(entry.get("featureId") or ""))
        item["stateLabel"] = _localize(
            STATE_LABELS.get(str(entry.get("state") or "idle"), STATE_LABELS["idle"]),
            language)
        reason = entry.get("disabledReason") or {}
        if isinstance(reason, dict):
            item["disabledReason"] = _localize(
                {"zh": reason.get("zh", ""), "en": reason.get("en", "")}, language)
        else:
            item["disabledReason"] = str(reason or "")
        return item

    def page_groups(self, page_id: str) -> list[dict[str, Any]]:
        language = str(self._language() or "zh")
        page_meta = (self._spec.get("pages") or {}).get(page_id) or {}
        entries = {str(item.get("featureId")): item for item in self.entries(page_id)}
        groups: list[dict[str, Any]] = []
        for group in page_meta.get("groups") or []:
            features = [entries[fid] for fid in group.get("features") or [] if fid in entries]
            if not features:
                continue
            groups.append({
                "id": str(group.get("id") or ""),
                "label": _localize({"zh": group.get("labelZh", ""),
                                    "en": group.get("labelEn", "")}, language),
                "features": features,
            })
        return groups

    def entries(self, page_id: str) -> list[dict[str, Any]]:
        if self._runtime is None:
            return self._fallback_entries(page_id)
        try:
            raw = self._runtime.entries(page_id) or []
        except Exception as exc:  # noqa: BLE001
            self._runtime_error = "feature-entries: " + str(exc)[:200]
            raw = []
        return [self._localize_entry(dict(entry)) for entry in raw]

    def _fallback_entries(self, page_id: str) -> list[dict[str, Any]]:
        language = str(self._language() or "zh")
        page_meta = (self._spec.get("pages") or {}).get(page_id) or {}
        out: list[dict[str, Any]] = []
        features = self._spec.get("features") or {}
        for group in page_meta.get("groups") or []:
            for fid in group.get("features") or []:
                spec = features.get(fid) or {}
                if not spec:
                    continue
                out.append(self._localize_entry({
                    "featureId": fid, "shortZh": spec.get("shortZh", fid),
                    "shortEn": spec.get("shortEn", fid), "name": spec.get("name", fid),
                    "nameEn": spec.get("nameEn", fid), "icon": spec.get("icon", "activity"),
                    "tier": spec.get("tier", ""), "mode": spec.get("mode", ""),
                    "page": page_id, "group": group.get("id", ""),
                    "state": "unavailable", "available": False, "hasResult": False,
                    "running": False, "needsConfirmation": bool(
                        (spec.get("launch") or {}).get("confirmation")),
                    "disabledReason": {"zh": self._unavailable_reason("zh"),
                                       "en": self._unavailable_reason("en")},
                }))
        return out

    def _unavailable_reason(self, language: str) -> str:
        if not self._runtime_error:
            return "功能工作区尚未就绪"
        if "runtime" in self._runtime_error:
            return "功能运行时不可用（工程诊断）"
        return "设备软件需要更新或功能接口未启用"

    def workspace(self) -> dict[str, Any]:
        """Return the QML read model for the active feature.

        QML evaluates several bindings that read App.featureWorkspace for
        one notification; building the snapshot again inside each read was
        the dominant live-stream GUI cost (~45 rebuilds per frame).  The
        snapshot is therefore cached until the next runtime/facade change.
        """
        language = str(self._language() or "zh")
        cached = self._ws_cache
        if cached is not None and self._ws_cache_language == language:
            return cached
        snapshot = self._compute_workspace()
        self._ws_cache = snapshot
        self._ws_cache_language = language
        return snapshot

    def workspace_signature(self) -> Any:
        """Cheap structural fingerprint of the read model (no chart payload).

        Used by AppViewModel to decide whether a change needs an immediate
        QML notification (open/close/state/message) or can be coalesced with
        the live chart refresh budget.
        """
        if self._runtime is None:
            return ("unavailable", self._runtime_error)
        try:
            return self._runtime.notify_signature()
        except Exception:  # noqa: BLE001 - coalescing must never raise
            return None

    def _compute_workspace(self) -> dict[str, Any]:
        language = str(self._language() or "zh")
        if self._runtime is None:
            return {"open": False, "available": False,
                    "message": self._unavailable_reason(language),
                    "chart": {"kind": "capability", "emptyReason": self._unavailable_reason(language)},
                    "flow": {"actions": [], "confirmations": []}}
        try:
            workspace = dict(self._runtime.workspace() or {})
        except Exception as exc:  # noqa: BLE001
            self._runtime_error = "feature-workspace: " + str(exc)[:200]
            return {"open": False, "available": False,
                    "message": "功能工作区状态不可用",
                    "chart": {"kind": "capability", "emptyReason": "workspace-error"},
                    "flow": {"actions": [], "confirmations": []}}
        feature_id = str(workspace.get("featureId") or "")
        # Fixed/hidden parameters: never let an internal field reach the user UI.
        for internal in ("params", "paramForm", "paramSpec", "paramsJson"):
            workspace.pop(internal, None)
        workspace["validity"] = self._plain_validity(workspace.get("validity"), language)
        workspace["stateLabel"] = _localize(
            STATE_LABELS.get(str(workspace.get("state") or "idle"), STATE_LABELS["idle"]),
            language)
        workspace["sourceLabel"] = _localize(
            SOURCE_LABELS.get(str(workspace.get("sourceKind") or "none"), SOURCE_LABELS["none"]),
            language)
        flow = dict(workspace.get("flow") or {})
        flow["actions"] = [self._localize_action(action, language)
                           for action in (flow.get("actions") or [])]
        flow["confirmations"] = [self._localize_action(item, language)
                                 for item in (flow.get("confirmations") or [])]
        workspace["flow"] = flow
        variants = []
        for variant in workspace.get("variants") or []:
            item = dict(variant)
            item["label"] = _localize(
                {"zh": item.get("labelZh", ""), "en": item.get("labelEn", "")},
                language, str(item.get("label") or item.get("id") or ""))
            item["chart"] = self._attach_image(
                feature_id + ":" + str(item.get("id") or ""), feature_id,
                self._localize_chart(item.get("chart") or {}, language))
            variants.append(item)
        workspace["variants"] = variants
        workspace["chart"] = self._attach_image(
            feature_id, feature_id, self._localize_chart(workspace.get("chart") or {},
                                                         language))
        if not workspace.get("shortName"):
            workspace["shortName"] = _localize(
                {"zh": workspace.get("shortZh", ""), "en": workspace.get("shortEn", "")},
                language, str(workspace.get("name") or feature_id))
        return workspace

    def _localize_chart(self, chart: dict[str, Any], language: str) -> dict[str, Any]:
        """Localize producer titles when the decoder supplies bilingual text."""
        chart = dict(chart or {})
        if isinstance(chart.get("frames"), list):
            frames=[]
            for source in chart["frames"]:
                if not isinstance(source, dict):
                    frames.append(source)
                    continue
                frame=dict(source)
                for key in ("frameFirstSampleIndex", "sampleIndex", "generation", "sourceFrame"):
                    if isinstance(frame.get(key), int):
                        frame[key]=str(frame[key])
                frames.append(frame)
            chart["frames"]=frames
        for key in ("title", "subtitle", "emptyReason", "text"):
            zh = chart.get(key + "Zh")
            en = chart.get(key + "En")
            if zh is not None or en is not None:
                chart[key] = _localize({"zh": zh or "", "en": en or ""}, language,
                                       str(chart.get(key) or ""))
        if language == "zh":
            # Schema validity strings are English protocol text.  Show a plain
            # Chinese note on the chart strip instead of raw engineering wording.
            subtitle = str(chart.get("subtitle") or "")
            if subtitle and all(ord(ch) < 128 for ch in subtitle):
                chart["subtitle"] = "需要本次PL处理完成且数据来源有效"
        # Translate display terms only; preserve schema identities/numbers.
        if language == "zh":
            terms = {
                "rms_FS":"均方根", "peak_FS":"峰值", "peakToPeak_FS":"峰峰值", "mean_FS":"直流均值",
                "rms_dBFS":"均方根电平", "crest":"波峰因数", "crest_ratio":"波峰因数", "clipCount":"削顶计数",
                "clip_count":"削顶计数", "nonzeroValid":"非零能量有效", "nonzero_energy_valid":"非零能量有效",
                "capture_valid":"输入有效", "fresh":"数据新鲜", "source_frame_id":"来源帧", "continuity_status":"连续性",
                "centroid_hz":"谱质心", "flatness":"谱平坦度", "peak_hz":"主峰频率", "peak_bin_power":"主峰功率",
                "delta_hz":"频率变化", "drift_hz_per_second":"频率漂移", "drift_valid":"漂移有效", "initialized":"历史已建立",
                "fundamental_hz":"基频", "period_strength":"周期强度", "THD_ratio":"有限带宽 THD",
                "coherence":"相干性", "phase_rad":"相位差", "frequency":"频率", "time":"时间", "lag":"时延",
                "positive_flux":"正向谱变化", "absolute_delta_sum":"谱变化总量", "rms_delta":"谱变化均方根",
                "L10DBFS":"L10", "L50DBFS":"L50", "L90DBFS":"L90", "count":"有效计数", "valid":"结果有效",
                "C50_db":"C50", "C80_db":"C80", "D50_percent":"D50", "tail_nonstationary":"末段非平稳",
                "relative_difference_dB":"相对电平差", "experimental_index":"实验指数", "rating":"估计等级", "estimated":"估计结果",
                "weighted_power_FS2":"计权功率", "weighted_dBFS":"相对计权电平", "power_FS2":"当前功率",
                "previous_power_FS2":"参考功率", "delta_FS2":"功率变化", "delta_valid":"变化有效"}
            units = {"dimensionless":"", "relative":"相对值", "FS squared/Hz":"FS²/Hz", "FS squared":"FS²"}
            def polish(obj):
                """Copy only label-bearing dicts; share the numeric data arrays.

                A live 1025-point trace must not be deep-copied on every frame just
                to translate a few display terms; points/raster/frames arrays stay
                shared because their values are never rewritten here.
                """
                if not isinstance(obj,dict):
                    return obj
                out={}
                for key,value in obj.items():
                    if key in ("label","name","title") and isinstance(value,str):
                        out[key]=terms.get(value,value)
                    elif key=="unit" and isinstance(value,str):
                        out[key]=units.get(value,value)
                    elif isinstance(value,dict):
                        out[key]=polish(value)
                    elif isinstance(value,list) and value and isinstance(value[0],dict):
                        out[key]=[polish(item) for item in value]
                    else:
                        out[key]=value
                return out
            # The chart is already a presentation copy; do not touch raw schema.
            chart=polish(chart)
        return chart

    @staticmethod
    def _plain_validity(text: Any, language: str) -> str:
        value = str(text or "")
        if language == "zh" and value and all(ord(ch) < 128 for ch in value):
            return "需要本次PL处理完成且数据来源有效"
        return value

    def _localize_action(self, action: dict[str, Any], language: str) -> dict[str, Any]:
        item = dict(action or {})
        item["label"] = _localize(
            {"zh": item.get("labelZh", ""), "en": item.get("labelEn", "")},
            language, str(item.get("label") or item.get("id") or ""))
        if isinstance(item.get("reason"), dict):
            item["reason"] = _localize(item["reason"], language)
        options = item.get("options")
        if isinstance(options, list):
            localized_options = []
            for option in options:
                if not isinstance(option, dict):
                    localized_options.append(option)
                    continue
                localized = dict(option)
                localized["label"] = _localize(
                    {"zh": option.get("labelZh", ""), "en": option.get("labelEn", "")},
                    language, str(option.get("label") or option.get("value") or ""))
                localized_options.append(localized)
            item["options"] = localized_options
        return item

    def _attach_image(self, cache_key: str, feature_id: str,
                      chart: dict[str, Any]) -> dict[str, Any]:
        chart = dict(chart or {})
        kind = str(chart.get("kind") or "")
        raster = chart.get("raster")
        # Retained-frame STFT: HeatmapChart now paints one image blit instead of
        # ~34k Canvas cells per update.  The image is built in display geometry
        # here and the payload keeps only a small peak-preserving sampling matrix
        # for the raster fallback / 3D waterfall / cursor path.
        if kind == "stft" and isinstance(raster, dict) \
                and str(raster.get("yUnit") or "") == "frame":
            return self._attach_stft_image(cache_key, chart, raster)
        # Other rasters keep the numeric matrix: their chart components draw it
        # cell-by-cell inside their own Canvas together with the axes and grid.
        if not raster and kind not in ("stft", "das-map", "heatmap"):
            return chart
        if kind == "das-map":
            # Polar/rectangular cells must use the same Canvas geometry as axes.
            chart["imageUrl"] = ""
            return chart
        if raster:
            revision = str(chart.get("chartRevision") or raster.get("revision") or
                           chart.get("revision") or "")
            cache = self._chart_cache.get(cache_key)
            if cache is None or cache.get("revision") != revision \
                    or cache.get("kind") != "raster":
                matrix = raster.get("matrix") or []
                number = 0
                if matrix:
                    try:
                        image = heatmap_image(
                            matrix,
                            palette=str(raster.get("palette") or "viridis"),
                            min_value=raster.get("min"),
                            max_value=raster.get("max"))
                        number = int(self._images.set_image(cache_key, image))
                    except Exception:  # noqa: BLE001 - display only
                        number = 0
                self._chart_cache[cache_key] = {"kind": "raster", "revision": revision,
                                                "number": number}
            number = int((self._chart_cache.get(cache_key) or {}).get("number") or 0)
            chart["imageUrl"] = ("image://plots/" + cache_key + "/" + str(number)) if number else ""
        elif kind == "stft":
            chart.setdefault("imageUrl", "")
        return chart

    def _attach_stft_image(self, cache_key: str, chart: dict[str, Any],
                           raster: dict[str, Any]) -> dict[str, Any]:
        """Attach the live STFT display image and trim the sampling raster.

        One live update used to ship a 16 x 1025 numeric raster to QML: the
        facade rasterised it with heatmap_image (raw orientation), QML then threw
        that image away, transposed the full matrix in JS on every notification
        and painted ~34k Canvas cells per repaint.  Now one small Python image
        (built directly in HeatmapChart screen geometry) feeds the chart as a
        single blit, and only a <=128-column peak-preserving matrix stays in the
        payload for the raster fallback and the 3D waterfall LOD.
        """
        matrix = raster.get("matrix") or []
        revision = str(chart.get("chartRevision") or raster.get("revision") or
                       chart.get("revision") or "")
        cache = self._chart_cache.get(cache_key)
        if cache is None or cache.get("kind") != "stft" \
                or cache.get("revision") != revision:
            sampling_raster = self._stft_sampling_raster(raster)
            number = 0
            frequency_axis, color_scale = self._stft_display_axes(chart, raster, matrix)
            if matrix and frequency_axis is not None:
                try:
                    image = stft_heatmap_image(
                        matrix,
                        frequency_axis=frequency_axis,
                        color_scale=color_scale,
                        palette=_STFT_DISPLAY_PALETTE,
                        width=min(64, max(16, len(matrix) * 4)),
                        height=_STFT_IMAGE_HEIGHT)
                    if not image.isNull():
                        number = int(self._images.set_image(cache_key, image))
                except Exception:  # noqa: BLE001 - display only, keep fallback
                    number = 0
            cache = {"kind": "stft", "revision": revision, "number": number,
                     "raster": sampling_raster}
            self._chart_cache[cache_key] = cache
        chart["frequencyAxis"] = self._stft_display_axes(chart, raster, matrix)[0]
        chart["raster"] = cache.get("raster") or raster
        number = int(cache.get("number") or 0)
        chart["imageUrl"] = ("image://plots/" + cache_key + "/" + str(number)) if number else ""
        return chart

    @staticmethod
    def _stft_display_axes(chart: dict[str, Any], raster: dict[str, Any],
                           matrix: Any) -> tuple[dict[str, Any] | None,
                                                 dict[str, Any] | None]:
        """Display axes exactly as FeaturePayload.stftDisplay derives them.

        Returns (frequency_axis, color_scale) for the image builder, or
        (None, None) when the payload cannot describe a displayable raster.
        """
        try:
            bins = max(len(row) for row in matrix)
        except (TypeError, ValueError):
            return None, None
        x_axis = chart.get("xAxis") or {}
        low = x_axis.get("min")
        high = x_axis.get("max")
        if not (_finite_number(low) and _finite_number(high)) \
                or not float(high) > float(low):
            return None, None
        low, high = float(low), float(high)
        if bins > 1:
            positive = low if low > 0 else (high - low) / (bins - 1)
        else:
            positive = low if low > 0 else high
        if not positive > 0.0:
            positive = high
        frequency_axis = {
            "min": positive,
            "max": high,
            "scale": "log" if (high / positive) > 20 else "linear",
            "dataMin": low,
            "dataMax": high,
        }
        color = chart.get("colorScale") or {}
        color_low = color.get("min")
        color_high = color.get("max")
        if not (_finite_number(color_low) and _finite_number(color_high)) \
                or not float(color_high) > float(color_low):
            color_low = raster.get("min")
            color_high = raster.get("max")
        color_scale = {"min": color_low, "max": color_high}
        return frequency_axis, color_scale

    @staticmethod
    def _stft_sampling_raster(raster: dict[str, Any]) -> dict[str, Any]:
        """Peak-preserving <=128-column copy of the STFT raster for QML.

        Rows stay in the decoder contract order (row 0 = newest frame) and all
        metadata (min/max/palette/labels/rowTimes/yUnit) is preserved, so
        FeaturePayload.stftDisplay keeps transposing the same way and the 3D
        waterfall still receives one point per retained frame.  Peak-preserving
        buckets (max of each bucket) keep transient bands visible.
        """
        matrix = raster.get("matrix") or []
        try:
            bins = max(len(row) for row in matrix)
        except (TypeError, ValueError):
            return dict(raster)
        if bins <= _STFT_RASTER_COLUMNS:
            return dict(raster)
        stride = int(math.ceil(bins / float(_STFT_RASTER_COLUMNS)))
        sampled: list[list[float | None]] = []
        for row in matrix:
            line: list[float | None] = []
            for start in range(0, bins, stride):
                chunk = row[start:start + stride]
                finite = [value for value in chunk if _finite_number(value)]
                line.append(max(finite) if finite else None)
            sampled.append(line)
        presentation = dict(raster)
        presentation["matrix"] = sampled
        presentation["columnStride"] = stride
        presentation["sourceBins"] = bins
        return presentation

    def status(self) -> dict[str, Any]:
        language = str(self._language() or "zh")
        info = dict(self._feature_api)
        runtime_status: dict[str, Any] = {}
        if self._runtime is not None:
            try:
                runtime_status = dict(self._runtime.status() or {})
            except Exception as exc:  # noqa: BLE001
                self._runtime_error = "feature-status: " + str(exc)[:200]
        info.update(runtime_status)
        info["featureApiEnabled"] = bool(self._feature_api.get("enabled"))
        info["connected"] = bool(self._feature_api.get("connected"))
        info["deviceSoftwareNote"] = ""
        if info["connected"] and not info["featureApiEnabled"]:
            info["deviceSoftwareNote"] = _localize(DEVICE_SOFTWARE_NOTE, language)
        elif not info["connected"]:
            info["deviceSoftwareNote"] = _localize(
                ("设备未连接；功能入口在连接并取得控制权后可用。",
                 "Device not connected; feature entries unlock after connecting."), language)
        elif not self._runtime:
            info["deviceSoftwareNote"] = _localize(
                ("功能运行时未就绪（PC侧）", "Feature runtime not ready (PC side)"), language)
        info["sourceLabel"] = _localize(
            SOURCE_LABELS.get(str(info.get("sourceKind") or "none"), SOURCE_LABELS["none"]),
            language)
        info["runtimeError"] = self._runtime_error
        return info

    # -- QML actions -------------------------------------------------------
    def open(self, feature_id: str) -> None:
        if self._runtime is not None:
            self._runtime.open(str(feature_id))
            self._emit_changed()

    def close(self) -> None:
        if self._runtime is not None:
            self._runtime.close()
            self._emit_changed()

    def run(self, feature_id: str) -> None:
        if self._runtime is not None:
            self._runtime.run(str(feature_id))
            self._emit_changed()

    def stop(self, feature_id: str) -> None:
        if self._runtime is not None:
            self._runtime.stop(str(feature_id))
            self._emit_changed()

    def refresh(self, feature_id: str) -> None:
        if self._runtime is not None:
            self._runtime.refresh(str(feature_id))
            self._emit_changed()

    def confirm(self, feature_id: str, key: str, value: Any) -> None:
        if self._runtime is not None:
            self._runtime.confirm(str(feature_id), str(key), value)
            self._emit_changed()

    def action(self, feature_id: str, action_id: str) -> None:
        if self._runtime is not None:
            self._runtime.action(str(feature_id), str(action_id))
            self._emit_changed()

    def set_view_option(self, feature_id: str, key: str, value: Any) -> None:
        if self._runtime is not None:
            self._runtime.set_view_option(str(feature_id), str(key), value)
            self._emit_changed()

    def page_changed(self, page_id: str) -> None:
        if self._runtime is not None:
            self._runtime.on_page_changed(str(page_id))
            self._emit_changed()

    def tick(self) -> None:
        if self._runtime is not None:
            try:
                self._runtime.tick()
            except Exception as exc:  # noqa: BLE001
                self._runtime_error = "feature-tick: " + str(exc)[:200]

    def export_raw(self, feature_id: str) -> dict[str, Any] | None:
        if self._runtime is None:
            return None
        try:
            return self._runtime.export_raw(str(feature_id))
        except Exception:  # noqa: BLE001
            return None

    def artifact_path(self, feature_id: str, suffix: str, root: Path) -> str:
        safe = "".join(ch for ch in str(feature_id) if ch.isalnum() or ch in "-_")
        folder = Path(root) / "exports" / "charts"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S") + "-" + __import__("uuid").uuid4().hex[:10]
        return str(folder / f"{safe or 'feature'}-{stamp}.{suffix.lstrip('.')}")

    def shutdown(self) -> None:
        if self._runtime is not None:
            try:
                self._runtime.shutdown()
            except Exception:  # noqa: BLE001
                pass

    def attach_change_callback(self, callback: Callable[[], None]) -> None:
        self._on_change = callback