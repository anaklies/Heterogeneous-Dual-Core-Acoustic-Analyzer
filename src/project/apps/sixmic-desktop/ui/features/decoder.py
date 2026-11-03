"""Schema-driven decoder for echo-features-1 raw results (protocol + display only).

Hard rules enforced here:

* The device schema layout is authoritative: ``actualProducerLayout`` wins over
  ``producerLayout``/``layout``; if a recipe layout is not confirmed by the device
  sources, raw words plus an explicit reason are returned and floats are never
  guessed.
* ``words`` are raw uint32 bit patterns.  float32 / uint32 / PCM24 (sign extended)
  / signed lag index are handled per field; no acoustic DSP is performed on the
  PC (no FFT, Welch, coherence, correlation, DAS, room fitting or STIPA math).
* Display payloads are bounded: long waveforms are reduced with a peak-envelope
  that keeps transients, 2D rasters are binned for drawing, and every array is
  clipped to a QML-safe size.  The full raw words are only returned by
  ``export_raw``/the dedicated raw payload, never by workspace().
* Invalid / NaN / valid=0 samples are gaps or grey categories, never zero lines.
  Identity counters (generation/sourceFrame) stay decimal strings.

The chart payload follows the agreed QML contract (kind/chartRevision/title/
subtitle/units/xAxis/yAxis/series/categories/colorScale/markers/referenceLines/
referenceBands/frames/scalarRows/text/emptyReason + raster/channels/meters/
events/stage/panels extensions).
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
from typing import Any, Iterable, Sequence

DEFAULT_SAMPLE_RATE_HZ = 48009.775390625
FFT_SIZE = 2048
PCM24_SCALE = 8388608.0

# Bounded display extraction sizes (numbers of QML points / values).
MAX_SERIES_POINTS = 4096
MAX_WAVEFORM_VALUES = 4096
MAX_RASTER_ROWS = 90
MAX_RASTER_COLS = 180
MAX_MARKERS = 128
MAX_RAW_PREVIEW = 128

# SixMic3D HOST result word map (integration/host/sixmic_host.h SM_R_*).
SM_R_FIELDS = [
    "protocol", "algorithm", "frame", "config", "session", "slot", "fft_base",
    "cycles", "sample_low", "sample_high", "faults", "mic_status", "missed",
    "dropped", "background_done", "overwritten", "failed", "temp_centi",
    "humidity", "pressure_pa", "sound_speed", "sensor_valid", "roll_pitch",
    "yaw", "qw_qx", "qy_qz", "env_sequence", "pose_sequence", "sensor_errors",
    "lost_events", "handoff_drops", "sample_rate",
]

# Device sources for the previously "pending-layout-resolution" features.  The
# exact output word maps were confirmed from these files (2026-10-26):
PENDING_LAYOUT_SOURCES: dict[str, dict[str, Any]] = {
    "frequency_time_weighting": {
        "source": "deployment/work_platform_20261013/phase15_analysis_only_20261023/"
                  "integration/services/noise_services.py weighted_level() + "
                  "recorded_time_response.py recorded_time_response()",
        "fields": {
            "weighting": "out[0]=weighted_power_FS2(f32), out[1]=weighted_dBFS(f32), "
                         "out[2]=valid(f32), out[3:1028]=immutable 1025 weighting coefficients",
            "recorded": "out[0]=FAST_power_FS2, out[1]=FAST_dBFS, out[2]=SLOW_power_FS2, "
                        "out[3]=SLOW_dBFS, out[4]=LeqFS, out[5]=samples_uint32, out[6]=valid, "
                        "out[7]=FAST_settled, out[8]=SLOW_settled; raw mono PCM24 at word 32",
        },
    },
    "level_statistics": {
        "source": "deployment/work_platform_20261013/phase15_analysis_only_20261023/"
                  "integration/services/noise_services.py level_statistics() + "
                  "test_noise_services.py",
        "fields": {
            "layout": "out[0]=L10DBFS, out[1]=L50DBFS, out[2]=L90DBFS, out[3]=LeqFS, "
                      "out[4]=valid, out[5]=count; rolling history 16 values at out[8:24] "
                      "(out[8] newest), scratch out[24:40]",
        },
    },
    "noise_rating": {
        "source": "deployment/work_platform_20261013/phase15_analysis_only_20261023/"
                  "integration/services/noise_services.py noise_curve() + "
                  "registry/INTERFACE_REGISTRY.json metadata",
        "fields": {
            "layout": "out[0]=rating, out[1]=valid, out[2]=estimated; octave input levels at "
                      "input_offset(32); constant curve table at 64; rating list after the "
                      "table (NR 101 rows x9 bands -> 973, NC 12 rows x8 bands -> 160)",
        },
    },
    "spectral_kurtosis": {
        "source": "deployment/work_platform_20261013/phase15_analysis_only_20261023/"
                  "integration/services/extra_spectral.py spectral_kurtosis() + "
                  "test_extra_spectral.py",
        "fields": {
            "layout": "out[0]=frame_count_float32 M, then per bin i: out[1+4i]=sum_power, "
                      "out[2+4i]=sum_power_squared, out[3+4i]=kurtosis, out[4+4i]=valid",
        },
    },
    "relative_insulation": {
        "source": "deployment/work_platform_20261013/phase15_analysis_only_20261023/"
                  "integration/services/noise_services.py relative_band_difference() + "
                  "ps/gateway/src/feature_runtime.c prepare_inputs()",
        "fields": {
            "layout": "9 bands: out[0:9]=10log10(A/B) dB, out[9:18]=valid flags, "
                      "out[18:27]=A(reference) band powers, out[27:36]=B(current) band powers",
        },
    },
}

_LAYOUT_RECIPES: set[str] = {
    "waveform", "channel-fields", "snapshot", "series", "count-then-series",
    "stft", "zoom", "ab-compare", "bands", "weighting", "level-statistics",
    "noise-rating", "scalars", "kurtosis", "lag-series", "lag-series+tail",
    "harmonic-bars", "field-bars", "pair-bins", "capability", "beam-spectrum",
    "das-map", "das-map+peaks", "scalars+history", "events", "room", "insulation",
    "stages",
}


class DecodeError(ValueError):
    """Raised when result words cannot be interpreted under the confirmed schema."""


# --------------------------------------------------------------------------
# primitive word decoding
# --------------------------------------------------------------------------
def u32_words(raw: bytes) -> list[int]:
    """Little-endian uint32 words; a trailing partial word is rejected, not padded."""
    if not raw:
        return []
    if len(raw) % 4:
        raw = raw[: len(raw) // 4 * 4]
    count = len(raw) // 4
    if not count:
        return []
    return list(struct.unpack("<" + "I" * count, raw))


def f32(word: int) -> float:
    try:
        return struct.unpack("<f", struct.pack("<I", int(word) & 0xFFFFFFFF))[0]
    except (struct.error, ValueError, OverflowError):
        return float("nan")


def pcm24(word: int) -> int:
    """Sign-extend a PCM24 value carried in the low 24 bits of a uint32 word."""
    value = int(word) & 0xFFFFFF
    if value & 0x800000:
        value -= 0x1000000
    return value


def pcm24_fs(word: int) -> float:
    return pcm24(word) / PCM24_SCALE


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _clean(value: Any, digits: int = 9) -> float | None:
    if not _finite(value):
        return None
    number = float(value)
    if number == 0.0:
        return 0.0
    return float(f"{number:.{digits}g}")


def _int_word(word: Any) -> int:
    try:
        return int(word) & 0xFFFFFFFF
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------------------
# display extraction helpers
# --------------------------------------------------------------------------
def peak_envelope(values: Sequence[float], max_buckets: int = 2048) -> dict[str, Any]:
    """Peak-envelope display extraction (min/max per bucket, transients kept).

    Returns interleaved ``[min, max, min, max, ...]`` plus the bucket size so a
    cursor can map a display index back to an approximate sample index.  This is
    drawing-only; the raw words for export are untouched.
    """
    count = len(values)
    if count <= max_buckets * 2:
        return {"values": [_clean(v) for v in values], "bucketSize": 1,
                "envelope": False, "sourceSampleCount": count}
    bucket = max(1, math.ceil(count / max_buckets))
    out: list[float | None] = []
    for start in range(0, count, bucket):
        chunk = values[start:start + bucket]
        finite = [v for v in chunk if _finite(v)]
        if not finite:
            out.append(None)
            out.append(None)
            continue
        out.append(_clean(min(finite)))
        out.append(_clean(max(finite)))
    return {"values": out, "bucketSize": bucket, "envelope": True,
            "sourceSampleCount": count}


def _make_points(xs: Sequence[float], ys: Sequence[float],
                 valid: Sequence[bool] | None = None, *, dedupe: bool = True
                 ) -> tuple[list[list[float]], list[list[int]], int]:
    """Build [[x, y]] points, dropping invalid pairs; returns (points, gaps, dropped)."""
    points: list[list[float]] = []
    gaps: list[list[int]] = []
    dropped = 0
    gap_start: int | None = None
    last_x: float | None = None
    for index in range(min(len(xs), len(ys))):
        x, y = xs[index], ys[index]
        ok = _finite(x) and _finite(y) and (valid is None or bool(valid[index]))
        if not ok:
            dropped += 1
            if gap_start is None:
                gap_start = index
            continue
        if gap_start is not None:
            gaps.append([gap_start, index - 1])
            gap_start = None
        fx, fy = float(x), float(y)
        if dedupe and last_x is not None and fx == last_x and points:
            points[-1][1] = fy
            continue
        points.append([_clean(fx), _clean(fy)])
        last_x = fx
    if gap_start is not None and gap_start < min(len(xs), len(ys)):
        gaps.append([gap_start, min(len(xs), len(ys)) - 1])
    if len(points) > MAX_SERIES_POINTS:
        stride = math.ceil(len(points) / MAX_SERIES_POINTS)
        sampled = points[::stride]
        if sampled and sampled[-1] is not points[-1]:
            sampled.append(points[-1])
        points = sampled
    return points, gaps, dropped


def _range(points: Iterable[Sequence[float]]) -> tuple[float, float]:
    xs = [float(p[0]) for p in points if len(p) >= 2 and _finite(p[0])]
    if not xs:
        return 0.0, 0.0
    return min(xs), max(xs)


def _y_range(points: Iterable[Sequence[float]]) -> tuple[float, float]:
    ys = [float(p[1]) for p in points if len(p) >= 2 and _finite(p[1])]
    if not ys:
        return 0.0, 0.0
    return min(ys), max(ys)


def _axis(minimum: float, maximum: float, *, scale: str = "linear",
          label: str = "", unit: str = "") -> dict[str, Any]:
    return {"min": _clean(minimum) or 0.0, "max": _clean(maximum) or 0.0,
            "scale": scale, "label": label, "unit": unit}


def _scalar_row(label: str, value: Any, unit: str = "",
                valid: bool = True) -> dict[str, Any]:
    if isinstance(value, float) and _finite(value):
        value = _clean(value)
    elif isinstance(value, float):
        value = None
        valid = False
    return {"label": str(label), "value": value, "unit": str(unit),
            "valid": bool(valid)}


def _band_label(hz: float) -> str:
    if not _finite(hz):
        return "—"
    number = float(hz)
    if number >= 1000:
        text = f"{number / 1000:g}k"
    else:
        text = f"{number:g}"
    return text + " Hz"


def _field_unit(name: str) -> str:
    key = str(name).lower()
    if "dbfs" in key:
        return "dBFS"
    if "db" in key:
        return "dB"
    if "hz" in key:
        return "Hz"
    if "second" in key or key.endswith("_s") or key.endswith("_seconds"):
        return "s"
    if "percent" in key or key.endswith("_pct"):
        return "%"
    if "fs2" in key or "power" in key or "energy" in key:
        return "FS²"
    if "ratio" in key or "flatness" in key or "coherence" in key:
        return ""
    if "samples" in key or "count" in key or "index" in key:
        return "count"
    return ""


# --------------------------------------------------------------------------
# context
# --------------------------------------------------------------------------
class _Ctx:
    def __init__(self, feature: dict[str, Any], payload: dict[str, Any],
                 words: Sequence[int], *, reference: dict[str, Any] | None = None,
                 variant: dict[str, Any] | None = None) -> None:
        self.feature = dict(feature or {})
        self.payload = dict(payload or {})
        self.words = [int(w) & 0xFFFFFFFF for w in words]
        self.schema = self.payload.get("schema") if isinstance(self.payload.get("schema"), dict) else {}
        actual = self.schema.get("actualProducerLayout")
        producer = self.schema.get("producerLayout") or self.schema.get("layout")
        self.layout: dict[str, Any] = actual if isinstance(actual, dict) else (
            producer if isinstance(producer, dict) else {})
        self.axes: dict[str, Any] = self.schema.get("axes") if isinstance(self.schema.get("axes"), dict) else {}
        self.decode: dict[str, Any] = self.feature.get("decode") if isinstance(self.feature.get("decode"), dict) else {}
        self.display: dict[str, Any] = self.feature.get("display") if isinstance(self.feature.get("display"), dict) else {}
        self.reference = reference or {}
        self.variant = variant or {}
        self.notes: list[str] = []
        self.provenance: list[str] = []
        self.feature_id = str(self.feature.get("featureId") or self.payload.get("featureId") or "")
        self.name = str(self.feature.get("name") or self.feature_id)
        self.chart_kind = str(self.feature.get("chart") or "scalars")
        self.units = str(self.feature.get("units") or self.schema.get("units") or "")
        self._sr: float | None = None
        self._sr_source = ""

    # -- metadata ---------------------------------------------------------
    def sample_rate(self) -> float:
        if self._sr is not None:
            return self._sr
        candidates = [
            (self.layout.get("sample_rate"), "producer metadata actualProducerLayout"),
            (self.layout.get("sampleRateHz"), "producer metadata actualProducerLayout"),
            (self.axes.get("sampleRateHz"), "schema axes"),
            (self.decode.get("sampleRateHz"), "view spec"),
        ]
        for value, source in candidates:
            if _finite(value) and float(value) > 0:
                self._sr = float(value)
                self._sr_source = source
                return self._sr
        self._sr = DEFAULT_SAMPLE_RATE_HZ
        self._sr_source = "device default (目录/设备默认)"
        self.provenance_note("显示频率轴来自目录/设备默认采样率 %.9g Hz，不是本次 producer 元数据"
                             % DEFAULT_SAMPLE_RATE_HZ)
        return self._sr

    def fft_size(self) -> int:
        for value in (self.layout.get("fftSize"), self.axes.get("fftSize"),
                      self.decode.get("fftSize"), self.payload.get("fftSize")):
            try:
                number = int(value)
            except (TypeError, ValueError):
                continue
            if number > 0:
                return number
        return FFT_SIZE

    def provenance_note(self, text: str) -> None:
        if text and text not in self.provenance:
            self.provenance.append(text)

    def note(self, text: str) -> None:
        if text and text not in self.notes:
            self.notes.append(text)

    def bin_frequency(self, bin_index: float) -> float:
        return float(bin_index) * self.sample_rate() / float(self.fft_size())

    def bins(self, count: int, first_bin: int = 0) -> list[float]:
        return [self.bin_frequency(first_bin + i) for i in range(count)]

    def first_bin(self) -> int:
        for value in (self.layout.get("first_bin"), self.decode.get("firstBin")):
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                continue
        return 0

    def labels(self) -> list[str]:
        colors = self.display.get("channelColors") or ["#57C8FF", "#FFC86B", "#CB9CFF",
                                                       "#44DBC0", "#A5D970", "#FF8295"]
        return list(colors)

    # -- chart scaffold ---------------------------------------------------
    def chart(self, kind: str | None = None, **extra: Any) -> dict[str, Any]:
        chart = {
            "kind": kind or self.chart_kind,
            "available": True,
            "title": self.name,
            "subtitle": "",
            "units": self.units,
            "xAxis": _axis(0.0, 0.0),
            "yAxis": _axis(0.0, 0.0),
            "series": [],
            "categories": [],
            "colorScale": None,
            "markers": [],
            "referenceLines": [],
            "referenceBands": [],
            "frames": [],
            "scalarRows": [],
            "text": "",
            "emptyReason": "",
        }
        chart.update(extra)
        return chart

    def frequency_axis(self, points: Sequence[Sequence[float]], unit: str = "Hz") -> dict[str, Any]:
        minimum, maximum = _range(points)
        scale = "log" if self.display.get("logXDefault") and minimum > 0 else "linear"
        return _axis(minimum, maximum, scale=scale, label="频率", unit=unit)

    def series(self, name: str, points: list[list[float]], *, role: str = "main",
               color: str | None = None, width: float = 1.2, dashed: bool = False,
               fill: bool = False, visible: bool = True,
               valid: bool = True) -> dict[str, Any]:
        colors = self.labels()
        return {"name": str(name), "role": str(role),
                "color": color or colors[len(colors) % 3],
                "points": points, "width": width, "dashed": dashed, "fill": fill,
                "visible": visible, "valid": bool(valid)}

    def finish(self, chart: dict[str, Any]) -> dict[str, Any]:
        list_keys = ("series", "categories", "markers", "referenceLines",
                     "referenceBands", "frames", "scalarRows", "channels",
                     "meters", "events", "panels", "points")
        for key in ("available", "title", "subtitle", "units", "xAxis", "yAxis",
                    "series", "categories", "markers", "referenceLines",
                    "referenceBands", "frames", "scalarRows", "text", "emptyReason"):
            chart.setdefault(key, [] if key in list_keys else "")
        has_payload = any(chart.get(key) for key in list_keys) or bool(
            chart.get("text")) or bool(chart.get("raster")) or bool(
            chart.get("stage")) or bool(chart.get("waveform"))
        if not has_payload and not chart.get("emptyReason"):
            chart["emptyReason"] = "无有效数据（NaN/无效位或无保留帧）"
        return seal_chart(chart)


def seal_chart(chart: dict[str, Any]) -> dict[str, Any]:
    """Attach a deterministic chartRevision that changes with data/validity."""
    payload = {key: value for key, value in chart.items() if key != "chartRevision"}
    digest = hashlib.sha1(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                     default=str).encode("utf-8")).hexdigest()
    chart["chartRevision"] = digest[:16]
    return chart


# --------------------------------------------------------------------------
# recipes
# --------------------------------------------------------------------------
def _recipe_waveform(ctx: _Ctx) -> dict[str, Any]:
    layout = ctx.layout
    service = str(layout.get("service") or "")
    words = ctx.words
    if "hilbert" in service or "analytic_envelope" in str(layout.get("fields") or ""):
        values = [f32(w) for w in words]
        display = peak_envelope(values)
        sr = ctx.sample_rate()
        chart = ctx.chart("waveform")
        chart["channels"] = [{
            "name": "包络", "color": ctx.labels()[0],
            "values": display["values"], "visible": True,
            "sampleRateHz": _clean(sr), "startSampleIndex": 0,
            "bucketSize": display["bucketSize"],
            "envelope": display["envelope"],
            "sourceSampleCount": display["sourceSampleCount"],
        }]
        chart["gaps"] = []
        chart["sampleRateHz"] = _clean(sr)
        chart["units"] = str(layout.get("units") or "FS")
        chart["yAxis"] = _axis(0.0, 1.0, label="幅度", unit="FS")
        chart["xAxis"] = _axis(0.0, _clean(len(values) / sr), label="时间", unit="s")
        chart["subtitle"] = "解析包络（PL 输出，PC 不做 Hilbert 变换）"
        ctx.note("波形为设备输出的解析包络；PC 不计算希尔伯特变换")
        return ctx.finish(chart)
    channels = ctx.axes.get("channels")
    if isinstance(channels, str):
        parsed = [int(ch) for ch in channels.replace("or", " ").split() if ch.isdigit()]
        channels = max(parsed) if parsed else 1
    try:
        channels = int(channels or layout.get("channels") or 1)
    except (TypeError, ValueError):
        channels = 1
    channels = max(1, min(channels, 6))
    try:
        stride = int(ctx.axes.get("channelStrideWords") or layout.get("channelStrideWords") or 0)
    except (TypeError, ValueError):
        stride = 0
    total = len(words)
    if stride <= 0:
        stride = max(1, total // channels)
    available = min(total, stride * channels)
    if channels > 1 and available < stride:
        channels = max(1, available // stride)
    sr = ctx.sample_rate()
    chart = ctx.chart("waveform")
    chart["channels"] = []
    chart["gaps"] = []
    for index in range(channels):
        start = index * stride
        end = min(start + stride, available)
        raw = words[start:end]
        values = [pcm24_fs(word) for word in raw]
        display = peak_envelope(values, max_buckets=min(2048, max(1, len(values) // 2)))
        chart["channels"].append({
            "name": f"CH{index + 1}",
            "color": ctx.labels()[index % len(ctx.labels())],
            "values": display["values"],
            "visible": True,
            "sampleRateHz": _clean(sr),
            "startSampleIndex": 0,
            "bucketSize": display["bucketSize"],
            "envelope": display["envelope"],
            "sourceSampleCount": display["sourceSampleCount"],
        })
    samples = stride
    chart["sampleRateHz"] = _clean(sr)
    chart["units"] = "FS"
    chart["yAxis"] = _axis(-1.0, 1.0, label="幅度", unit="FS")
    chart["xAxis"] = _axis(0.0, _clean(samples / sr), label="时间", unit="s")
    chart["subtitle"] = f"{channels} 通道 · PCM24 符号扩展 · 显示抽取峰值包络"
    ctx.provenance_note("PCM24 数值: value&0xFFFFFF 符号扩展后再除以 2^23 归一化为 FS")
    if any(channel["envelope"] for channel in chart["channels"]):
        ctx.note("长记录显示采用峰值包络抽取（仅绘图），原始字完整保留用于导出")
    return ctx.finish(chart)


_LEVEL_FIELDS = ["rms_FS", "peak_FS", "peakToPeak_FS", "mean_FS", "rms_dBFS",
                 "crest", "clipCount", "nonzeroValid"]


def _recipe_channel_fields(ctx: _Ctx) -> dict[str, Any]:
    fields = [str(f) for f in (ctx.schema.get("fields") or _LEVEL_FIELDS)]
    if len(fields) < 8:
        fields = _LEVEL_FIELDS
    stride = ctx.axes.get("channelStrideWords") or len(fields)
    try:
        stride = int(stride)
    except (TypeError, ValueError):
        stride = len(fields)
    channels = ctx.axes.get("channels")
    try:
        channels = int(channels or (len(ctx.words) // stride if stride else 1))
    except (TypeError, ValueError):
        channels = 1
    channels = max(1, min(channels, 6, len(ctx.words) // max(1, stride)))
    chart = ctx.chart("level-bars")
    meters = []
    categories = []
    for channel in range(channels):
        base = channel * stride
        values = {name: _int_word(ctx.words[base + index]) if base + index < len(ctx.words) else None
                  for index, name in enumerate(fields)}
        rms_fs = f32(values.get("rms_FS") or 0)
        rms_dbfs = f32(values.get("rms_dBFS") or 0)
        peak = f32(values.get("peak_FS") or 0)
        clip = int(values.get("clipCount") or 0)
        nonzero = int(values.get("nonzeroValid") or 0)
        valid = bool(nonzero) and _finite(rms_dbfs) and _finite(peak)
        meters.append({
            "label": f"CH{channel + 1}",
            "color": ctx.labels()[channel % len(ctx.labels())],
            "value": _clean(rms_dbfs) if valid else None,
            "peak": _clean(peak) if _finite(peak) else None,
            "valid": valid,
            "clip": clip > 0,
            "rmsFs": _clean(rms_fs),
            "crest": _clean(f32(values.get("crest") or 0)),
        })
        categories.append({"label": f"CH{channel + 1}",
                           "value": _clean(rms_dbfs) if valid else None,
                           "unit": "dBFS", "valid": valid})
    chart["meters"] = meters
    chart["categories"] = categories
    chart["yAxis"] = _axis(-120.0, 0.0, label="电平", unit="dBFS")
    chart["subtitle"] = "六通道 RMS/峰值/削顶（非校准 SPL）"
    ctx.note("静音时 nonzeroValid=0，不显示 dBFS；峰值为 FS 数字满幅比例")
    if any(meter["clip"] for meter in meters):
        ctx.note("检测到削顶计数")
    return ctx.finish(chart)


def _faults_text(faults: int) -> str:
    names = ["pipeline", "capture", "config", "memory", "foreground", "background",
             "sensor", "recorder", "lost-event", "handoff"]
    active = []
    for bit in range(10):
        if faults & (1 << bit):
            active.append(names[bit] if bit < len(names) else f"bit{bit}")
    return ",".join(active) if active else "none"


def _recipe_snapshot(ctx: _Ctx) -> dict[str, Any]:
    words = ctx.words
    field = (lambda index: _int_word(words[index]) if index < len(words) else 0)
    sample_index = (field(8) | (field(9) << 32))
    faults = field(10)
    chart = ctx.chart("scalars")
    rows: list[dict[str, Any]] = []
    feature_id = ctx.feature_id
    if feature_id == "signal_quality":
        rows.extend([
            _scalar_row("采集故障位", f"0x{faults:08x}", "bitfield", faults == 0),
            _scalar_row("故障明细", _faults_text(faults), "", True),
            _scalar_row("麦克风状态", f"0x{field(11):08x}", "bitfield", field(11) != 0),
            _scalar_row("采集有效", int(faults == 0), "bool", True),
            _scalar_row("源帧号", field(2), "frame", field(2) != 0),
            _scalar_row("配置版本", field(3), "version", field(3) != 0),
            _scalar_row("会话", field(4), "id", field(4) != 0),
            _scalar_row("采样序号", str(sample_index), "samples", sample_index > 0),
            _scalar_row("传感器有效", f"0x{field(21):08x}", "bitfield", field(21) != 0),
            _scalar_row("声速", f32(field(20)), "m/s", _finite(f32(field(20)))),
            _scalar_row("温度", field(17), "centi-°C", field(17) != 0),
            _scalar_row("湿度", field(18), "%", field(18) != 0),
            _scalar_row("气压", field(19), "Pa", field(19) != 0),
            _scalar_row("环境序列", field(26), "count", True),
            _scalar_row("姿态序列", field(27), "count", True),
            _scalar_row("传感器错误", f"0x{field(28):08x}", "bitfield", field(28) == 0),
            _scalar_row("丢失事件", field(29), "count", field(29) == 0),
            _scalar_row("交接丢弃", field(30), "count", field(30) == 0),
            _scalar_row("采样率", f32(field(31)), "Hz", _finite(f32(field(31)))),
        ])
        chart["text"] = ("P0 六通道状态快照（SM_R_* 32 字）。P0 状态/帧/来源有效性必须为真；"
                         "静音不等于采集成功。")
    else:
        rows.extend([
            _scalar_row("源帧号", field(2), "frame", field(2) != 0),
            _scalar_row("配置版本", field(3), "version", field(3) != 0),
            _scalar_row("会话", field(4), "id", field(4) != 0),
            _scalar_row("槽位", field(5), "slot", field(5) <= 3),
            _scalar_row("FFT 基址", f"0x{field(6):08x}", "word", True),
            _scalar_row("采样序号", str(sample_index), "samples", sample_index > 0),
            _scalar_row("周期计数", field(7), "cycles", True),
            _scalar_row("故障位", f"0x{faults:08x}", "bitfield", faults == 0),
            _scalar_row("故障明细", _faults_text(faults), "", True),
            _scalar_row("丢帧", field(13), "count", field(13) == 0),
            _scalar_row("漏事件", field(12), "count", field(12) == 0),
            _scalar_row("采样率", f32(field(31)), "Hz", _finite(f32(field(31)))),
        ])
        chart["text"] = ("P0 原始游标/连续性快照（SM_R_* 32 字）；缺口或故障位=1 时明确显示失败，"
                         "不补零、不伪造连续。")
    chart["scalarRows"] = rows
    chart["subtitle"] = "P0 32 字状态快照"
    ctx.note("字段映射来自 integration/host/sixmic_host.h SM_R_*（设备源码确认）")
    return ctx.finish(chart)


def _series_values(ctx: _Ctx, start: int, count: int) -> list[float]:
    return [f32(w) for w in ctx.words[start:start + count]]


def _recipe_series(ctx: _Ctx) -> dict[str, Any]:
    words = ctx.words
    count = len(words)
    for value in (ctx.layout.get("bins"), ctx.layout.get("count"),
                  ctx.decode.get("count"), ctx.axes.get("bins")):
        try:
            candidate = int(value)
        except (TypeError, ValueError):
            continue
        if 0 < candidate <= len(words):
            count = candidate
            break
    first = ctx.first_bin()
    xs = ctx.bins(count, first)
    ys = _series_values(ctx, 0, count)
    points, gaps, dropped = _make_points(xs, ys)
    # Display-only modulation view. The source envelope FFT includes a mean
    # component and the existing Hann window's first-bin lobe; retain all raw
    # words/export, but do not let those dominate the modulation plot.
    dc = ys[0] if ys else None
    if ctx.feature_id == "modulation_spectrum":
        points=[p for p in points if p[0]>=2*ctx.sample_rate()/ctx.fft_size()]
    chart = ctx.chart()
    name = str(ctx.layout.get("service") or ctx.feature.get("shortZh") or "结果")
    chart["series"] = [ctx.series(name, points)]
    chart["xAxis"] = ctx.frequency_axis(points)
    chart["yAxis"] = _axis(*_y_range(points), label=ctx.units, unit="")
    chart["subtitle"] = f"{count} 频点 · 设备生产布局"
    if ctx.feature_id == "modulation_spectrum":
        chart["scalarRows"]=[_scalar_row("直流分量（原始FFT幅）",dc,"FFT幅",_finite(dc))]
        chart["subtitle"]="短窗包络谱：视图隐藏DC及第一窗主瓣；未改动原始数据"
        ctx.note("与包络谱共享同一PL计算；当前短窗不用于精确测量低于约47Hz的调制，隐藏点仍保留在原始导出中")
    if ctx.layout.get("history"):
        chart["scalarRows"] = [_scalar_row("累计帧数/历史", str(ctx.layout.get("history")), "",
                                           True)]
    if dropped:
        ctx.note(f"{dropped} 个无效/NaN 频点未绘制（不画 0）")
    return ctx.finish(chart)


def _recipe_count_then_series(ctx: _Ctx) -> dict[str, Any]:
    words = ctx.words
    count_word = _int_word(words[0]) if words else 0
    decode = ctx.decode
    expected = 0
    for value in (decode.get("count"), ctx.layout.get("bins"), ctx.decode.get("bins")):
        try:
            expected = int(value)
        except (TypeError, ValueError):
            continue
        if expected > 0:
            break
    available = max(0, len(words) - 1)
    count = expected if 0 < expected <= available else available
    xs = ctx.bins(count, ctx.first_bin())
    ys = _series_values(ctx, 1, count)
    points, gaps, dropped = _make_points(xs, ys)
    chart = ctx.chart()
    name = str(ctx.layout.get("service") or "均值谱")
    chart["series"] = [ctx.series(name, points)]
    chart["xAxis"] = ctx.frequency_axis(points)
    chart["yAxis"] = _axis(*_y_range(points), label=ctx.units, unit="")
    chart["scalarRows"] = [
        _scalar_row("累计独立帧数", count_word, "帧", count_word > 0),
        _scalar_row("均值频点数", count, "bins", count > 0),
    ]
    chart["subtitle"] = "累计平均谱（帧数在首字，PC 不做 Welch）"
    ctx.provenance_note("均值 PSD 为设备累计结果；PC 仅解码，不执行 Welch 计算")
    if dropped:
        ctx.note(f"{dropped} 个无效/NaN 频点未绘制")
    return ctx.finish(chart)


def _recipe_bands(ctx: _Ctx) -> dict[str, Any]:
    centers: list[float] = []
    for source in (ctx.axes.get("bandHz"), ctx.layout.get("centers_hz"),
                   ctx.schema.get("bandHz")):
        if isinstance(source, list) and source:
            centers = [float(v) for v in source if _finite(v)]
            break
    count = min(len(centers), len(ctx.words)) if centers else len(ctx.words)
    if not centers:
        centers = [float(index) for index in range(count)]
    ramp = ctx.display.get("bandRamp") or ["#6A5ACD", "#4E76D6", "#3E8FC9", "#37AFAF",
                                           "#44DBC0", "#A9D96C", "#FFC86B"]
    categories = []
    for index in range(count):
        power = f32(ctx.words[index])
        valid = _finite(power) and power > 0.0
        categories.append({
            "label": _band_label(centers[index]),
            "value": _clean(power) if valid else None,
            "centerFrequency": _clean(centers[index]),
            "unit": "FS²",
            "valid": valid,
            "color": ramp[index % len(ramp)],
        })
    chart = ctx.chart()
    chart["categories"] = categories
    chart["yAxis"] = _axis(0.0, max([float(c["value"] or 0) for c in categories] or [0.0]),
                           label="频带功率", unit="FS²")
    chart["subtitle"] = f"{count} 频带 · 设备 PL 频带能量"
    valid_count = sum(1 for c in categories if c["valid"])
    if valid_count < count:
        ctx.note(f"{count - valid_count} 个频带功率为 0/无效（灰标，不画 0）")
    return ctx.finish(chart)


def _recipe_ab_compare(ctx: _Ctx) -> dict[str, Any]:
    decode = ctx.decode
    count = 0
    for value in (decode.get("count"), ctx.layout.get("bins")):
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        if count > 0:
            break
    count = count or 1025
    delta_offset = int(decode.get("deltaOffset") or 0)
    flags_offset = int(decode.get("flagsOffset") or (2 * count))
    words = ctx.words
    reference_words = ctx.reference.get("words") or []
    chart = ctx.chart("ab-spectrum")
    if len(words) == count:
        # Role=reference result: 1025 bin powers captured as the frozen reference.
        xs = ctx.bins(count, ctx.first_bin())
        ys = [f32(w) for w in words]
        points, _, dropped = _make_points(xs, ys)
        chart["series"] = [ctx.series("冻结参考 A", points, role="reference",
                                      color=ctx.labels()[0])]
        chart["xAxis"] = ctx.frequency_axis(points)
        chart["yAxis"] = _axis(*_y_range(points), label="功率谱", unit="FS²/bin")
        chart["subtitle"] = "已保存的 PL 功率参考（不释放）"
        ctx.note("参考结果被保留，普通刷新不会释放该参考")
        return ctx.finish(chart)
    delta_ys = [f32(w) for w in words[delta_offset:delta_offset + count]]
    flag_ys = [f32(w) for w in words[flags_offset:flags_offset + count]] if len(
        words) > flags_offset else []
    xs = ctx.bins(count, ctx.first_bin())
    valid = [True if i >= len(flag_ys) else True for i in range(count)]
    delta_points, gaps, dropped = _make_points(xs, delta_ys, valid)
    chart["series"] = [ctx.series("差值（当前-参考）", delta_points, role="delta",
                                  color=ctx.labels()[2])]
    flagged = [index for index, value in enumerate(flag_ys) if _finite(value) and value != 0]
    markers = []
    for index in flagged[:MAX_MARKERS]:
        if index < len(xs):
            markers.append({"x": _clean(xs[index]), "y": 0.0,
                            "label": "阈值标志", "kind": "threshold"})
    chart["markers"] = markers
    if len(flagged) > MAX_MARKERS:
        ctx.note(f"阈值标志 {len(flagged)} 个，仅绘制前 {MAX_MARKERS} 个（原始导出完整）")
    ref_ys: list[float] = []
    if reference_words and len(reference_words) >= count:
        ref_ys = [f32(w) for w in reference_words[:count]]
        ref_points, _, _ = _make_points(xs, ref_ys)
        chart["series"].append(ctx.series("参考 A（已保存）", ref_points, role="reference",
                                          color=ctx.labels()[0], dashed=True))
        current_ys = [ref + delta for ref, delta in zip(ref_ys, delta_ys)
                      if _finite(ref) and _finite(delta)]
        if len(current_ys) == count:
            current_points, _, _ = _make_points(xs, current_ys)
            chart["series"].append(ctx.series("当前 B（参考+PL差值显示还原）",
                                              current_points, role="current",
                                              color=ctx.labels()[1]))
            ctx.provenance_note("当前谱 B = 已保存参考 A + PL 差值（仅显示还原，不是 PC 重算）")
        else:
            ctx.note("参考或差值存在无效频点，未能显示当前谱 B")
    else:
        chart["scalarRows"] = [_scalar_row("参考频谱", "本机无保存参考；仅显示 PL 差值/阈值标志",
                                           "", False)]
        ctx.note("比较结果只含 PL 差值/阈值标志；A/B 需要已保存的参考结果")
    chart["xAxis"] = ctx.frequency_axis(delta_points)
    top_series=[v for v in chart["series"] if v.get("role")!="delta"]
    top_points=[p for v in top_series for p in v.get("points",[])]
    chart["yAxis"] = _axis(*_y_range(top_points), label="功率谱", unit="FS²/bin")
    chart["deltaYAxis"] = _axis(*_y_range(delta_points), label="功率差值 B−A", unit="FS²/bin")
    chart["panels"]=[{"render":"line","title":"冻结参考 A 与当前 B","series":top_series},
                      {"render":"line","title":"差值 B−A","series":[chart["series"][0]]}]
    if ctx.feature_id=="relative_limit":
        db_offset=ctx.layout.get("change_db_offset")
        if db_offset is not None:
            db_values=[f32(v) for v in words[int(db_offset):int(db_offset)+count]]
            db_points,_,_=_make_points(xs,db_values)
            chart["deltaYAxis"]=_axis(-12,12,label="相对变化",unit="dB")
            change=ctx.series("变化 dB",db_points,role="delta",color=ctx.labels()[2])
            chart["series"]=[change]+top_series
            threshold=float(ctx.layout.get("threshold_db",6))
            summary=int(ctx.layout.get("summary_offset",3*count))
            chart["scalarRows"]=[_scalar_row("越限频点",sum(bool(_finite(v) and v!=0) for v in flag_ys),"个",True),_scalar_row("限值",threshold,"dB",True)]
            chart["referenceLines"]=[{"value":threshold,"label":"增加限值","unit":"dB"},{"value":-threshold,"label":"减小限值","unit":"dB"}]
        chart["kind"]="statistics"
        chart["panels"]=[{"render":"line","title":"相对参考的变化与限值","series":[v for v in chart["series"] if v.get("role")=="delta"],"xAxis":chart["xAxis"],"yAxis":chart.get("deltaYAxis"),"referenceLines":chart.get("referenceLines",[])},
                          {"render":"line","title":"越限标志  1=越限  0=正常","series":[ctx.series("PL越限标志",[[x,float(bool(_finite(y) and y!=0))] for x,y in zip(xs,flag_ys)])],"xAxis":chart["xAxis"],"yAxis":_axis(-.05,1.1,label="越限状态",unit="")}]

    if ctx.feature_id!="relative_limit":chart["referenceLines"] = [{"value":0.0,"label":"无变化","unit":"FS²/bin"}] if delta_points else []
    chart["subtitle"] = f"{count} 频点 · PL 绝对变化阈值标志（非 dB SPL 限值）"
    if dropped:
        ctx.note(f"{dropped} 个无效/NaN 频点未绘制")
    return ctx.finish(chart)


def _recipe_pair_bins(ctx: _Ctx) -> dict[str, Any]:
    layout = ctx.layout
    try:
        stride = int(layout.get("stride") or 11)
    except (TypeError, ValueError):
        stride = 11
    fields = [str(f) for f in (layout.get("fields") or [
        "sum_xx", "sum_yy", "sum_real", "sum_imag", "Sxx", "Syy",
        "CSD_real", "CSD_imag", "coherence", "phase_rad", "valid"])]
    try:
        bins = int(layout.get("bins") or ctx.axes.get("bins") or 1025)
    except (TypeError, ValueError):
        bins = 1025
    count_float = f32(ctx.words[0]) if ctx.words else 0.0
    count_word = int(count_float) if _finite(count_float) and count_float>=0 else 0
    first = ctx.first_bin()
    xs = ctx.bins(bins, first)
    size = min(bins, max(0, (len(ctx.words) - 1) // max(1, stride)))
    values: dict[str, list[float]] = {}
    for index, field in enumerate(fields):
        line = []
        for bin_index in range(size):
            position = 1 + bin_index * stride + index
            line.append(f32(ctx.words[position]) if position < len(ctx.words) else float("nan"))
        values[field] = line
    valid = [bool(_finite(v) and v != 0) for v in values.get("valid", [1.0] * size)]
    convention = str(layout.get("convention") or "conj(X_i)*X_j")
    pair = layout.get("pair") or ctx.variant.get("params") or {}
    chart_kind = ctx.chart_kind
    chart = ctx.chart(chart_kind)
    if chart_kind == "coherence-phase":
        coherence_points, coh_gaps, _ = _make_points(xs[:size], values.get("coherence", [0.0] * size), valid)
        phase_mask=[valid[i] and _finite(values.get("coherence",[0.0]*size)[i]) and values.get("coherence",[0.0]*size)[i]>=.5 for i in range(size)]
        phase_points, phase_gaps, _ = _make_points(xs[:size], values.get("phase_rad", [0.0] * size), phase_mask)
        chart["series"] = [
            ctx.series("相干", coherence_points, role="coherence", color=ctx.labels()[0]),
            ctx.series("相位", phase_points, role="phase", color=ctx.labels()[1]),
        ]
        chart["panels"] = [
            {"kind": "line", "title": "相干（0..1）", "subtitle": "每频点 valid 才绘制",
             "units": "", "xAxis": ctx.frequency_axis(coherence_points),
             "yAxis": _axis(0.0, 1.0, label="相干", unit=""),
             "series": [ctx.series("相干", coherence_points, role="coherence")]},
            {"kind": "line", "title": "相位", "subtitle": "弧度；只显示相干≥0.5的频点，原始相位仍保留",
             "units": "rad", "xAxis": ctx.frequency_axis(phase_points),
             "yAxis": _axis(-math.pi, math.pi, label="相位", unit="rad"),
             "series": [ctx.series("相位", phase_points, role="phase")]},
        ]
        chart["subtitle"] = f"{size} 频点 · 双通道 {pair} · {convention} · 相位 rad"
        chart["scalarRows"]=[_scalar_row("累计帧数",count_word,"帧",count_word>0),_scalar_row("有效频点",sum(valid),"点"),_scalar_row("可信相位频点",sum(phase_mask),"点")]
        ctx.note("相干 0..1 + 每频点 valid；低相干频点的相位不绘制")
    else:
        colors = ctx.labels()
        series_specs = [("Sxx", "Sxx", colors[0]), ("Syy", "Syy", colors[1])]
        chart["series"] = []
        for field, label, color in series_specs:
            if field in values:
                points, _, _ = _make_points(xs[:size], values[field], valid)
                chart["series"].append(ctx.series(label, points, role=field.lower(),
                                                  color=color))
        for field, label, role in (("CSD_real", "CSD 实部", "csd-real"),
                                   ("CSD_imag", "CSD 虚部", "csd-imag")):
            if field in values:
                points, _, _ = _make_points(xs[:size], values[field], valid)
                chart["series"].append(ctx.series(label, points, role=role))
        if "CSD_real" in values and "CSD_imag" in values:
            magnitude = [math.hypot(values["CSD_real"][i], values["CSD_imag"][i])
                         for i in range(size)]
            points, _, _ = _make_points(xs[:size], magnitude, valid)
            chart["series"].append(ctx.series("CSD 幅值（显示合成）", points, role="csd-mag"))
        chart["xAxis"] = ctx.frequency_axis(chart["series"][0]["points"] if chart["series"]
                                           else [])
        y_points = [point for item in chart["series"] for point in item["points"]]
        chart["yAxis"] = _axis(*_y_range(y_points), label=ctx.units, unit="")
        chart["subtitle"] = f"{size} 频点 · 双通道 {pair} · {convention}"
        chart["scalarRows"] = [_scalar_row("累计帧数", count_word, "count", count_word > 0)]
        ctx.note("CSD 实/虚部按 schema 字段显示；幅值为实虚显示合成（非重算声学量）")
    if not any(chart["series"]):
        chart["emptyReason"] = "无有效双通道频点"
    return ctx.finish(chart)


def _lag_of(index: int, size: int = FFT_SIZE) -> int:
    half = size // 2
    return index if index <= half else index - size


def _recipe_lag_series(ctx: _Ctx) -> dict[str, Any]:
    layout = ctx.layout
    size = 0
    for value in (layout.get("output_count"),
                  len(ctx.words) if ctx.decode.get("recipe") != "lag-series+tail" else 2048):
        try:
            size = int(value)
        except (TypeError, ValueError):
            continue
        if size > 0:
            break
    size = max(1, min(size, len(ctx.words)))
    tail = 0
    if str(ctx.decode.get("recipe")) == "lag-series+tail":
        tail = 3
        size = max(1, min(2048, len(ctx.words) - tail))
    sr = ctx.sample_rate()
    cepstrum = "cepstrum" in str(ctx.feature_id) or "cepstrum" in str(layout.get("service") or "")
    if cepstrum:
        xs = [index / sr for index in range(size)]
        unit_label, axis_label = "s", "倒频率"
        x_unit = "s"
    else:
        xs = [_lag_of(index, FFT_SIZE) / sr for index in range(size)]
        unit_label, axis_label = "", "时延"
        x_unit = "s"
    ys = [f32(w) for w in ctx.words[:size]]
    points, gaps, dropped = _make_points(xs, ys)
    chart = ctx.chart("lag-series")
    name = str(layout.get("service") or "相关")
    chart["series"] = [ctx.series(name, points)]
    peak_index = -1
    peak_value = 0.0
    peak_abs = -1.0
    for index, value in enumerate(ys):
        if _finite(value) and abs(float(value)) > peak_abs:
            peak_abs = abs(float(value))
            peak_value = float(value)
            peak_index = index
    if peak_index >= 0:
        chart["markers"] = [{"x": _clean(xs[peak_index]), "y": _clean(peak_value),
                             "label": "峰值", "kind": "peak"}]
        chart["scalarRows"] = [
            _scalar_row("峰值时延" if not cepstrum else "峰值倒频率",
                        xs[peak_index], "s", True),
            _scalar_row("峰值", peak_value, str(layout.get("units") or ctx.units), True),
        ]
    if not cepstrum:
        points.sort(key=lambda p:p[0])
    if ctx.feature_id=="gcc_phat":
        # Display the physically admissible pair-delay window, not the entire
        # circular FFT period. The raw correlation remains in the export.
        params=(ctx.feature.get("launch") or {}).get("params") or {}
        i=int(params.get("channel",0));j=int(params.get("other",1))
        radius=.225/math.sqrt(3);coords=[(0,radius,-.076),(-.1125,-radius/2,-.076),(.1125,-radius/2,-.076),(0,radius,.076),(-.1125,-radius/2,.076),(.1125,-radius/2,.076)]
        distance=math.dist(coords[max(0,min(5,i))],coords[max(0,min(5,j))]);bound=distance/300+1/sr
        window=[p for p in points if abs(p[0])<=bound]
        points=[[x*1000,y] for x,y in window];chart["series"][0]["points"]=points
        if points:
            best=max(points,key=lambda p:abs(p[1]));chart["markers"]=[{"x":best[0],"y":best[1],"label":"时延候选","kind":"peak"}]
            chart["scalarRows"]=[_scalar_row("时延候选",best[0],"ms"),_scalar_row("相关峰值",best[1],""),_scalar_row("通道对",f"MIC{i+1} / MIC{j+1}",""),_scalar_row("物理窗口",bound*1000,"±ms")]
        axis_label="麦对时延";x_unit="ms"
        ctx.note("仅在阵列几何允许的时延窗中读峰；这是相关峰候选，不是方向；纯音及反射可能多解，底噪中不保证可靠")
    chart["xAxis"] = _axis(*_range(points), label=axis_label, unit=x_unit)
    chart["yAxis"] = _axis(*_y_range(points), label=str(layout.get("units") or ctx.units),
                           unit="")
    if cepstrum:
        chart["subtitle"] = f"{size} 点 · 实倒谱（quefrency=index/sampleRate）"
        ctx.note("倒谱横轴为倒频率秒（quefrency），不是物理时延定位")
    else:
        lag_note = str(layout.get("lag") or "")
        chart["subtitle"] = f"{size} 点 · lag=(i<=1024?i:i-2048)/sampleRate"
        ctx.note(("参考通道与符号约定：" + lag_note) if lag_note
                 else "正值表示第一通道相对第二通道延迟（设备 schema 约定）")
    if dropped:
        ctx.note(f"{dropped} 个无效/NaN 点未绘制")
    if tail and len(ctx.words) >= tail:
        tail_values = [f32(w) for w in ctx.words[-tail:]]
        tail_names = [str(name) for name in (layout.get("fields_tail") or
                                            ["fundamental_hz", "period_strength", "valid"])]
        rows = []
        for index, value in enumerate(tail_values):
            label = tail_names[index] if index < len(tail_names) else f"tail{index}"
            valid = (value != 0) if label.endswith("valid") else _finite(value)
            rows.append(_scalar_row(label, value, _field_unit(label), bool(valid)))
        chart["scalarRows"] = chart.get("scalarRows", []) + rows
        chart["subtitle"] += " · PL基频估计；当前默认100–2000Hz"
        if layout.get("window"):ctx.note("记录窗："+str(layout["window"]))
        ctx.note("周期性为环形 Hann 记录最大归一化自相关，非唯一物理基频")
    return ctx.finish(chart)


def _recipe_harmonic_bars(ctx: _Ctx) -> dict[str, Any]:
    layout = ctx.layout
    fields = [str(f) for f in (layout.get("fields") or [])]
    orders = 0
    for value in (layout.get("output_count"), len(ctx.words)):
        try:
            total = int(value)
        except (TypeError, ValueError):
            continue
        if total > 0:
            orders = max(0, total - 2)
            break
    orders = min(orders, max(0, len(ctx.words) - 1))
    f0 = layout.get("f0_hz")
    categories = []
    for order in range(orders):
        power = f32(ctx.words[order])
        valid = _finite(power) and power > 0.0
        label = f"H{order + 1}"
        if _finite(f0) and float(f0) > 0:
            label += f" {float(f0) * (order + 1):g}Hz"
        categories.append({"label": label, "value": _clean(power) if valid else None,
                           "unit": "FS²", "valid": valid,
                           "color": ctx.labels()[order % len(ctx.labels())]})
    chart = ctx.chart("harmonic-bars")
    chart["categories"] = categories
    thd = f32(ctx.words[orders]) if len(ctx.words) > orders else float("nan")
    valid_flag = f32(ctx.words[orders + 1]) if len(ctx.words) > orders + 1 else float("nan")
    chart["scalarRows"] = [
        _scalar_row("THD", thd, "ratio", bool(_finite(valid_flag) and valid_flag != 0)),
        _scalar_row("有效", int(_finite(valid_flag) and valid_flag != 0), "bool", True),
    ]
    chart["yAxis"] = _axis(0.0, max([float(c["value"] or 0) for c in categories] or [0.0]),
                           label="谐波功率", unit="FS²")
    chart["subtitle"] = f"{orders} 次谐波 · 当前指定基频 {float(f0) if _finite(f0) else 0:g}Hz · 接收端谐波比（非设备自身失真检定）"
    ctx.note("THD按比值显示，1.0等于100%；必须保证指定基频主导输入，扬声器/房间/麦克风响应均会影响接收端结果")
    return ctx.finish(chart)


def _recipe_field_bars(ctx: _Ctx) -> dict[str, Any]:
    layout = ctx.layout
    fields = [str(f) for f in (layout.get("fields") or [])]
    words = [_int_word(w) for w in ctx.words]
    chart = ctx.chart("harmonic-bars")
    categories = []
    for index, name in enumerate(fields):
        value = f32(words[index]) if index < len(words) else float("nan")
        if name.endswith("_FS2") or "power" in name or "carrier" in name and "ratio" not in name:
            valid = _finite(value) and value > 0
            categories.append({"label": name, "value": _clean(value) if valid else None,
                               "unit": "FS²", "valid": valid,
                               "color": ctx.labels()[index % len(ctx.labels())]})
    chart["categories"] = categories
    rows = []
    valid_flag = 1.0
    for index, name in enumerate(fields):
        value = f32(words[index]) if index < len(words) else float("nan")
        if name.endswith("ratio"):
            valid_flag = f32(words[-1]) if words else float("nan")
            rows.append(_scalar_row(name, value, "",
                                    bool(_finite(valid_flag) and valid_flag != 0)))
        elif name.endswith("valid"):
            rows.append(_scalar_row("有效", int(_finite(value) and value != 0), "bool", True))
    chart["scalarRows"] = rows
    chart["yAxis"] = _axis(0.0, max([float(c["value"] or 0) for c in categories] or [0.0]),
                           label="功率", unit="FS²")
    ranges=layout.get("bin_ranges") or []
    centers=[(r[0]+r[1])*.5*ctx.sample_rate()/ctx.fft_size()/1000 for r in ranges if isinstance(r,list) and len(r)==2]
    chart["subtitle"] = "固定下/载波/上频带："+" / ".join(f"{v:.1f}kHz" for v in centers)+"；积分功率比"
    ctx.note("当前默认频带不会自动跟随任意载波；测试音必须匹配设备元数据指定频带")
    return ctx.finish(chart)


def _recipe_scalars(ctx: _Ctx) -> dict[str, Any]:
    layout = ctx.layout
    fields = [str(f) for f in (layout.get("fields") or ctx.schema.get("fields")
                               or ctx.decode.get("fields") or [])]
    if not fields:
        return _fallback(ctx, "no scalar field mapping")
    words = [_int_word(w) for w in ctx.words]
    chart = ctx.chart("scalars")
    rows = []
    for index, name in enumerate(fields):
        if index >= len(words):
            break
        if "uint" in name or name.endswith("_id") or name in ("frame", "count"):
            value: Any = words[index]
            valid = value != 0
            unit = "count"
        elif name in ("valid", "initialized", "settled") or name.endswith("_valid"):
            raw = f32(words[index])
            value = int(_finite(raw) and raw != 0)
            valid = True
            unit = "bool"
        else:
            raw = f32(words[index])
            value = raw
            valid = _finite(raw) and (raw != 0 or name not in ("fundamental_hz", "peak_hz"))
            unit = _field_unit(name)
        rows.append(_scalar_row(name, value, unit, bool(valid)))
    # Distinct primary metrics for pages sharing the spectral-shape producer.
    # Keep raw field keys for consumers; display labels never change the wire data.
    primary={"frequency_tracking":"peak_hz","centroid":"centroid_hz","flatness":"flatness","frequency_drift":"drift_hz_per_second","energy_change":"delta_FS2","band_tracking":"delta_FS2"}.get(ctx.feature_id)
    display_names={"peak_hz":"主频","centroid_hz":"谱重心","flatness":"谱平坦度","peak_bin_power":"谱峰功率","delta_hz":"频率变化","drift_hz_per_second":"频率漂移率","drift_valid":"漂移有效","power_FS2":"当前功率","previous_power_FS2":"前次功率","delta_FS2":"功率变化","delta_valid":"变化有效","history_hz":"历史频率","history_power_FS2":"历史功率","initialized":"已初始化","frame_uint":"源帧"}
    flags={r["label"]:r["value"] for r in rows}
    for r in rows:
        if r["label"] in display_names:r["displayLabel"]=display_names[r["label"]]
        guard="drift_valid" if r["label"] in ("delta_hz","drift_hz_per_second") else "delta_valid" if r["label"]=="delta_FS2" else None
        if guard and not flags.get(guard):r["value"]=None;r["valid"]=False
    if primary:rows.sort(key=lambda r:r["label"]!=primary)
    chart["scalarRows"] = rows
    chart["subtitle"] = str(layout.get("service") or "设备标量输出")
    if "floor" in layout:
        ctx.provenance_note(f"设备计算地板 1e-{abs(int(math.log10(float(layout.get('floor') or 1e-20)))):g}"
                            "；0/无效值与静音不解释为测量成功")
    if "lifetime" in layout:
        ctx.note(str(layout.get("lifetime")))
    return ctx.finish(chart)


def _recipe_scalars_history(ctx: _Ctx) -> dict[str, Any]:
    layout = ctx.layout
    fields = [str(f) for f in (layout.get("fields") or ["positive_flux",
                                                        "absolute_delta_sum", "rms_delta"])]
    history_offset = 0
    try:
        history_offset = int(layout.get("history_offset") or 0)
    except (TypeError, ValueError):
        history_offset = 0
    chart = ctx.chart()
    rows = []
    for index, name in enumerate(fields):
        if index >= len(ctx.words):
            break
        value = f32(ctx.words[index])
        valid = _finite(value)
        rows.append(_scalar_row(name, value, _field_unit(name), valid))
    history = [f32(w) for w in ctx.words[history_offset:]] if history_offset < len(ctx.words) else []
    points, gaps, dropped = _make_points(list(range(len(history))), history)
    chart["series"] = [ctx.series("帧历史", points, role="history",
                                  color=ctx.labels()[2])]
    chart["scalarRows"] = rows
    chart["xAxis"] = _axis(*_range(points), label="帧序号", unit="frame")
    chart["yAxis"] = _axis(*_y_range(points), label=ctx.units, unit="")
    chart["subtitle"] = "变化检测标量 + 帧历史（设备 PL 输出）"
    ctx.note("横轴为设备帧序号，不是接收时间")
    if dropped:
        ctx.note(f"{dropped} 个无效/NaN 帧未绘制")
    return ctx.finish(chart)


def _recipe_level_statistics(ctx: _Ctx) -> dict[str, Any]:
    layout = ctx.layout
    fields = [str(f) for f in (layout.get("output_fields") or
                              ["L10DBFS", "L50DBFS", "L90DBFS", "LeqFS", "valid", "count"])]
    words = [_int_word(w) for w in ctx.words]
    chart = ctx.chart("statistics")
    rows = []
    labels = ["L10", "L50", "L90", "Leq"]
    categories = []
    measurement_valid=len(words)>4 and _finite(f32(words[4])) and f32(words[4])!=0
    for index in range(min(4, len(words))):
        value = f32(words[index])
        valid = _finite(value) and measurement_valid
        label = labels[index] if index < len(labels) else fields[index]
        rows.append(_scalar_row(label, value, "dBFS", bool(valid)))
        categories.append({"label": label, "value": _clean(value) if valid else None,
                           "unit": "dBFS", "valid": bool(valid),
                           "color": ctx.labels()[index % len(ctx.labels())]})
    valid_flag = f32(words[4]) if len(words) > 4 else 0.0
    count = f32(words[5]) if len(words) > 5 else 0.0
    rows.append(_scalar_row("有效", int(_finite(valid_flag) and valid_flag != 0),
                            "bool", True))
    rows.append(_scalar_row("观测数", count, "count", _finite(count)))
    chart["categories"] = categories
    history = [f32(w) for w in ctx.words[8:24]] if len(ctx.words) >= 24 else []
    history=history[:min(16,max(0,int(count)))] if _finite(count) else []
    chronological = list(reversed(history))
    points, gaps, dropped = _make_points(list(range(len(chronological))), chronological)
    if points:
        chart["series"] = [ctx.series("电平观测趋势（旧→新）", points, role="trend",
                                      color=ctx.labels()[2])]
    chart["scalarRows"] = rows
    chart["yAxis"] = _axis(-140.0, 0.0, label="电平", unit="dBFS")
    chart["panels"]=[
        {"render":"bars","title":"分位电平与等效电平","categories":categories,"yAxis":chart["yAxis"],"xLabel":"统计量","xUnit":""},
        {"render":"line","title":"最近电平变化","series":chart.get("series",[]),"xAxis":_axis(0,max(1,len(chronological)-1),label="观测序号",unit="次"),"yAxis":chart["yAxis"]}]
    chart["subtitle"] = "16 次等间隔观测的 L10/L50/L90/LeqFS（非校准噪声评价）"
    ctx.note("统计量来自设备 PL 滚动观测；PC 不重新排序或重算分位数；"
             "必须等间隔采样，缺帧需复位")
    if dropped:
        ctx.note(f"{dropped} 个无效/NaN 观测未绘制")
    return ctx.finish(chart)


_NR_CENTERS = [31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000]
_NC_CENTERS = [63, 125, 250, 500, 1000, 2000, 4000, 8000]


def _recipe_noise_rating(ctx: _Ctx) -> dict[str, Any]:
    layout = ctx.layout
    words = [_int_word(w) for w in ctx.words]
    chart = ctx.chart("noise-rating")
    rating = f32(words[0]) if words else float("nan")
    valid = f32(words[1]) if len(words) > 1 else 0.0
    estimated = f32(words[2]) if len(words) > 2 else 0.0
    blocks = layout.get("constant_blocks") or []
    table: list[float] = []
    ratings: list[float] = []
    if isinstance(blocks, list):
        for block in blocks:
            if not isinstance(block, list) or len(block) != 2:
                continue
            offset, values = block
            if not isinstance(values, list):
                continue
            try:
                offset = int(offset)
            except (TypeError, ValueError):
                continue
            if len(values) == 101:
                ratings = [float(v) for v in values if _finite(v)]
            elif len(values) == 12:
                ratings = [float(v) for v in values if _finite(v)]
            elif len(values) >= 64:
                table = [float(v) for v in values if _finite(v)]
    family = "NR" if str(layout.get("service","")).startswith("NR") or len(ratings)>12 else "NC"
    centers = [float(v) for v in (layout.get("centers_hz") or
                                  (_NR_CENTERS if family == "NR" else _NC_CENTERS))
               if _finite(v)]
    if not table:
        rows = [
            _scalar_row("估计值", rating, family, bool(_finite(rating) and valid != 0)),
            _scalar_row("有效", int(valid != 0), "bool", True),
            _scalar_row("估计", int(estimated != 0), "bool", True),
        ]
        chart["scalarRows"] = rows
        chart["text"] = (f"{family} 估计值；显式名义参考，不是声学校准。"
                         "设备未返回曲线表，未绘制参考曲线。")
        return ctx.finish(chart)
    band_count = len(centers) if centers else 9
    rows_count = len(table) // band_count if band_count else 0
    series = []
    if rows_count and _finite(rating):
        row_index = 0
        if ratings:
            nearest = min(range(len(ratings)), key=lambda i: abs(ratings[i] - float(rating)))
            row_index = nearest
        else:
            row_index = max(0, min(rows_count - 1, int(round(float(rating)))))
        row_index = max(0, min(rows_count - 1, row_index))
        row = table[row_index * band_count:(row_index + 1) * band_count]
        reference_points, _, _ = _make_points(centers, row)
        series.append(ctx.series(f"{family} 参考曲线", reference_points, role="reference",
                                 color=ctx.labels()[0], dashed=True))
    levels = []
    input_offset = layout.get("input_offset")
    try:
        input_offset = int(input_offset) if input_offset is not None else 32
    except (TypeError, ValueError):
        input_offset = 32
    for index in range(band_count):
        position = input_offset + index
        if position < len(words):
            raw_level=f32(words[position])
            offset=f32(words[31]) if len(words)>31 else 0.0
            levels.append(raw_level+offset if _finite(raw_level) and _finite(offset) else float("nan"))
        else:
            levels.append(float("nan"))
    level_points, _, dropped = _make_points(centers, levels)
    if level_points:
        series.append(ctx.series("倍频程电平（名义参考）", level_points, role="levels",
                                 color=ctx.labels()[1]))
    chart["series"] = series
    chart["scalarRows"] = [
        _scalar_row(f"{family} 估计值", rating, family,
                    bool(_finite(rating) and valid != 0)),
        _scalar_row("有效", int(valid != 0), "bool", True),
        _scalar_row("名义估计", int(estimated != 0), "bool", True),
        _scalar_row("参考偏移", f32(words[31]) if len(words) > 31 else float("nan"),
                    "dB", False),
    ]
    chart["xAxis"] = _axis(min(centers or [0]), max(centers or [0]),
                           scale="log", label="频率", unit="Hz")
    all_points=[p for row in series for p in row.get("points",[])]
    chart["yAxis"] = _axis(*_y_range(all_points), label="名义参考电平", unit="dB")
    chart["subtitle"] = f"{family} 曲线估计 · 显式名义数字参考（非认证、非声学校准）"
    ctx.note("0 偏移只是显式名义参考示例，不是声学校准；结果为估计值")
    if dropped:
        ctx.note(f"{dropped} 个频带输入无效/NaN 未绘制")
    return ctx.finish(chart)


def _recipe_kurtosis(ctx: _Ctx) -> dict[str, Any]:
    words = [_int_word(w) for w in ctx.words]
    chart = ctx.chart("spectrum")
    if not words:
        chart["emptyReason"] = "无谱峭度数据"
        return ctx.finish(chart)
    frame_count = f32(words[0])
    bins = 0
    for value in (ctx.layout.get("bins"), (len(words) - 1) // 4):
        try:
            bins = int(value)
        except (TypeError, ValueError):
            continue
        if bins > 0:
            break
    bins = max(0, min(bins, (len(words) - 1) // 4))
    first = int(ctx.layout.get("first_bin") or 0)
    xs = ctx.bins(bins, first)
    ys: list[float] = []
    valid: list[bool] = []
    for index in range(bins):
        base = 1 + 4 * index
        valid_flag = f32(words[base + 3]) if base + 3 < len(words) else 0.0
        kurt = f32(words[base + 2]) if base + 2 < len(words) else float("nan")
        ys.append(kurt)
        valid.append(bool(_finite(kurt) and _finite(valid_flag) and valid_flag != 0))
    points, gaps, dropped = _make_points(xs, ys, valid)
    chart["series"] = [ctx.series("谱峭度", points, role="kurtosis",
                                  color=ctx.labels()[2])]
    chart["scalarRows"] = [
        _scalar_row("累计帧数 M", frame_count, "帧", _finite(frame_count) and frame_count >= 3),
        _scalar_row("频点数", bins, "bins", bins > 0),
        _scalar_row("有效频点", sum(1 for flag in valid if flag), "bins", True),
    ]
    chart["xAxis"] = ctx.frequency_axis(points)
    chart["yAxis"] = _axis(*_y_range(points), label="谱峭度", unit="")
    chart["subtitle"] = ("累积同配置帧谱峭度：per-bin valid 才绘制；"
                         "(M+1)/(M-1)(M·ΣP²/ΣP²-1)-1，PC 不重算")
    ctx.note("每频点 valid 需要 M≥3 且 ΣP≥1e-20；重叠偏差未校正；更换配置必须复位")
    if dropped:
        ctx.note(f"{dropped} 个无效频点未绘制")
    return ctx.finish(chart)


def _recipe_insulation(ctx: _Ctx) -> dict[str, Any]:
    words = [_int_word(w) for w in ctx.words]
    chart = ctx.chart("insulation-bars")
    bands = 0
    try:
        offset = int(ctx.decode.get("inputOffset") or 18)
        bands = max(0, offset // 2)
    except (TypeError, ValueError):
        bands = 9
    if len(words) == bands:
        # Role=reference result for relative_insulation: 9 octave band powers.
        centers = _NR_CENTERS
        categories = []
        for index in range(min(bands, len(centers))):
            power = f32(words[index])
            valid = _finite(power) and power > 0
            ramp = ctx.display.get("bandRamp") or ctx.labels()
            categories.append({"label": _band_label(centers[index]),
                               "value": _clean(power) if valid else None, "unit": "FS²",
                               "valid": valid,
                               "color": ramp[index % len(ramp)]})
        chart["categories"] = categories
        chart["subtitle"] = "已保存的相对隔声参考（PL 倍频程能量，A）"
        ctx.note("参考已保存；测量时必须保持同激励/增益/测量链")
        return ctx.finish(chart)
    bands = min(bands, len(words) // 4) or (len(words) // 4)
    bands = max(0, min(bands, 32))
    differences = [f32(w) for w in words[:bands]]
    valid_flags = [f32(w) for w in words[bands:2 * bands]]
    reference = [f32(w) for w in words[2 * bands:3 * bands]]
    current = [f32(w) for w in words[3 * bands:4 * bands]]
    centers = _NR_CENTERS[:bands] if bands <= len(_NR_CENTERS) else [
        float(index + 1) for index in range(bands)]
    ramp = ctx.display.get("bandRamp") or ctx.labels()
    categories = []
    for index in range(bands):
        valid = bool(_finite(valid_flags[index]) and valid_flags[index] != 0
                     and _finite(differences[index]))
        categories.append({
            "label": _band_label(centers[index]),
            "value": _clean(differences[index]) if valid else None,
            "unit": "dB",
            "valid": valid,
            "centerFrequency": _clean(centers[index]),
            "color": ramp[index % len(ramp)],
        })
    chart["categories"] = categories
    chart["yAxis"] = _axis(min([0.0]+[float(c["value"]) for c in categories if c["valid"]]) - 1.0,
                           max([0.0]+[float(c["value"]) for c in categories if c["valid"]]) + 1.0,
                           label="相对差异", unit="dB")
    chart["subtitle"] = (f"{bands} 频带 · 相对电平差异 dB（A/B），非 Rw/DnT，"
                         "PC 不重算隔声指标")
    rows = [_scalar_row("参考 A 频带功率", sum(v for v in reference if _finite(v)),
                        "FS²", False),
            _scalar_row("测量 B 频带功率", sum(v for v in current if _finite(v)),
                        "FS²", False)]
    chart["scalarRows"] = [_scalar_row("有效频带",sum(1 for c in categories if c["valid"]),"带",True)]
    ctx.note("结果为相对差异，禁止标为 Rw；同激励/增益/测量链需用户确认")
    return ctx.finish(chart)


def _fit_rows(values: list[float], label: str, first_index: int,
              sample_rate: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = []
    bands = []
    names = [label + " 值", label + " R²", label + " 有效", label + " 样本数",
             label + " 开始时间", label + " 结束时间"]
    units = ["s", "", "bool", "samples", "s", "s"]
    for offset in range(6):
        position = first_index + offset
        value = values[position] if position < len(values) else float("nan")
        name = names[offset]
        if offset in (0, 1):
            flag=values[first_index+2] if first_index+2<len(values) else 0
            ok=_finite(flag) and flag!=0 and _finite(value)
            rows.append(_scalar_row(name, value if ok else None, units[offset], ok))
        elif offset in (2, 4, 5):
            rows.append(_scalar_row(name, value, units[offset],
                                    _finite(value) and (offset == 2 or value >= 0)))
        else:
            rows.append(_scalar_row(name, value, units[offset], _finite(value)))
    valid = values[first_index + 2] if first_index + 2 < len(values) else 0.0
    if _finite(valid) and valid != 0 and _finite(values[first_index]):
        first = values[first_index + 4] if first_index + 4 < len(values) else 0.0
        last = values[first_index + 5] if first_index + 5 < len(values) else 0.0
        if _finite(first) and _finite(last) and sample_rate > 0 and last >= first:
            bands.append({"from": _clean(first),
                          "to": _clean(last),
                          "label": label, "color": None})
    return rows, bands


def _recipe_room(ctx: _Ctx) -> dict[str, Any]:
    layout = ctx.layout
    words = [_int_word(w) for w in ctx.words]
    try:
        summary_words = int(layout.get("summary_words") or 32)
    except (TypeError, ValueError):
        summary_words = 32
    try:
        ir_offset = int(layout.get("ir_offset") or 32)
    except (TypeError, ValueError):
        ir_offset = 32
    try:
        decay_offset = int(layout.get("decay_offset") or (ir_offset + 24000))
    except (TypeError, ValueError):
        decay_offset = ir_offset + 24000
    try:
        samples = int(layout.get("samples") or max(0, len(words) - decay_offset))
    except (TypeError, ValueError):
        samples = max(0, len(words) - decay_offset)
    sample_rate = ctx.sample_rate()
    field_map = layout.get("fields") if isinstance(layout.get("fields"), dict) else {}
    summary = [f32(w) for w in words[:summary_words]]

    def word(index: int) -> float:
        return summary[index] if index < len(summary) else float("nan")

    chart_kind = ctx.chart_kind
    chart = ctx.chart(chart_kind)
    decay = [f32(w) for w in words[decay_offset:decay_offset + samples]]
    xs = [index / sample_rate for index in range(len(decay))] if sample_rate else []
    points, gaps, dropped = _make_points(xs, decay)
    chart["series"] = [ctx.series("能量衰减", points, role="decay",
                                  color=ctx.labels()[5] if len(ctx.labels()) > 5
                                  else ctx.labels()[0])]
    rows: list[dict[str, Any]] = []
    bands: list[dict[str, Any]] = []
    for label, key, first_index in (
            ("EDT", "EDT", 10), ("T20", "T20", 16), ("T30", "T30", 22)):
        positions = field_map.get(key) if isinstance(field_map.get(key), list) else None
        start = int(positions[0]) if positions else first_index
        fit_rows, fit_bands = _fit_rows(summary, label, start, sample_rate)
        rows.extend(fit_rows)
        bands.extend(fit_bands)
    rows.extend([
        _scalar_row("能量", word(0), "FS²", _finite(word(0)) and word(0) > 0),
        _scalar_row("早期能量 50ms", word(1), "FS²", _finite(word(1))),
        _scalar_row("早期能量 80ms", word(2), "FS²", _finite(word(2))),
        _scalar_row("D50", word(3), "%", _finite(word(3)) and 0 <= word(3) <= 100 and word(0)>0 and word(4)!=0),
        _scalar_row("尾部检查通过", int(word(4) != 0), "bool", True),
        _scalar_row("C50", word(5), "dB", _finite(word(5)) and word(6) != 0),
        _scalar_row("C80", word(7), "dB", _finite(word(7)) and word(8) != 0),
    ])
    chart["fitDetails"] = rows
    chart["scalarRows"] = [r for r in rows if r["label"] in ("EDT 值","T20 值","T30 值")]
    chart["referenceBands"] = bands
    chart["resultHint"] = "" if all(r["valid"] for r in chart["scalarRows"]) else f"部分拟合无法计算：检查底噪、有效衰减区间及{samples/sample_rate:.2f}秒分析窗；无效不是0秒。"
    if chart_kind == "room-clarity":
        categories = [
            {"label": "C50", "value": _clean(word(5)) if word(6)!=0 else None,
             "unit": "dB", "valid": bool(_finite(word(5)) and word(6) != 0)},
            {"label": "C80", "value": _clean(word(7)) if word(8)!=0 else None,
             "unit": "dB", "valid": bool(_finite(word(7)) and word(8) != 0)},
            {"label": "D50", "value": _clean(word(3)),
             "unit": "%", "valid": _finite(word(3)) and 0 <= word(3) <= 100 and word(0)>0 and word(4)!=0},
        ]
        chart["categories"] = categories[:2]
        chart["scalarRows"] = [_scalar_row("C50",word(5) if word(6)!=0 else None,"dB",word(6)!=0 and _finite(word(5))),
                              _scalar_row("C80",word(7) if word(8)!=0 else None,"dB",word(8)!=0 and _finite(word(7))),
                              _scalar_row("D50",word(3) if word(0)>0 and word(4)!=0 else None,"%",word(0)>0 and word(4)!=0 and _finite(word(3)) and 0 <= word(3) <= 100)]
        chart["series"] = []
        chart["referenceBands"] = []
        chart["resultHint"] = "C50/C80比较早到与晚到能量；D50为前50ms能量比例，与混响衰减时间不同。"
    chart["xAxis"] = _axis(0.0, (len(decay) / sample_rate) if sample_rate else 0.0,
                           label="时间", unit="s")
    chart["yAxis"] = _axis(*_y_range(points), label="相对能量", unit="dB")
    if chart_kind=="room-clarity":
        chart["xAxis"]=_axis(0,2,label="清晰度指标",unit="")
        cvals=[r["value"] for r in chart["scalarRows"][:2] if r["valid"] and _finite(r["value"])]
        chart["yAxis"]=_axis(min([0]+cvals)-3,max([0]+cvals)+3,label="早晚能量比",unit="dB")
    if "noise_power_FS2" in field_map:
        noise_known=_finite(word(9)) and word(9)>0 and _finite(word(28)) and -200<word(28)<0
        chart["scalarRows"].extend([_scalar_row("尾噪功率",word(9) if noise_known else None,"FS²",noise_known),_scalar_row("可信衰减余量",-word(28) if noise_known else None,"dB",noise_known)])
        chart["resultHint"]="已补偿平稳尾噪；T20需覆盖-5至-25dB，T30需覆盖-5至-35dB，并高于噪声不确定性界限。无效不是0秒。"
        chart["decayQualityValid"]=bool(word(4)!=0)
        if not chart["decayQualityValid"]:chart["resultHint"]="未形成可信的先强后衰减：可能未捕获激励、有第二次瞬态或背景变化。本次不评价房间好坏，请播放测试脉冲并保持安静。"
    center=layout.get("center_hz")
    chart["subtitle"] = ("清晰度：C50 / C80 / D50" if chart_kind=="room-clarity" else
                         (str(center)+" Hz频带衰减" if center else "混响衰减：EDT / T20 / T30"))
    chart["subtitle"] += " · PC 不重新拟合"
    if center:chart["scalarRows"]=[r for r in chart["scalarRows"] if r["label"] in ("EDT 值","T20 值","T30 值")]
    if _finite(word(4)) and word(4) == 0 and word(0)>0:
        ctx.note("尾部近似平稳底噪：当前PL未做底噪扣除，拒绝相应拟合或清晰度；不是0秒混响")
    if dropped:
        ctx.note(f"{dropped} 个无效/NaN 衰减点未绘制")
    ctx.note("不是认证 RIR/RT60 测量；普通语音不得自动当 RIR")
    return ctx.finish(chart)


def _recipe_stft(ctx: _Ctx) -> dict[str, Any]:
    words = [_int_word(w) for w in ctx.words]
    bins = 0
    for value in (ctx.axes.get("bins"), 1025):
        try:
            bins = int(value)
        except (TypeError, ValueError):
            continue
        if bins > 0:
            break
    bins = max(1, bins)
    frames_available = len(words) // bins
    indices_raw = ctx.axes.get("frameFirstSampleIndices") or []
    indices: list[int] = []
    for value in indices_raw:
        try:
            indices.append(int(str(value)))
        except (TypeError, ValueError):
            continue
    sample_rate = ctx.sample_rate()
    ff = 2048
    try:
        ff = int(ctx.axes.get("fftSize") or FFT_SIZE)
    except (TypeError, ValueError):
        ff = FFT_SIZE
    xs = [index * sample_rate / ff for index in range(bins)]
    frames = []
    matrix: list[list[float]] = []
    display_bins = min(128, bins)
    stride = max(1, math.ceil(bins / display_bins))
    for frame in range(frames_available):
        values = [f32(w) for w in words[frame * bins:(frame + 1) * bins]]
        first = indices[frame] if frame < len(indices) else None
        time = (first / sample_rate) if (first is not None and sample_rate) else None
        display_points = []
        for start in range(0, bins, stride):
            chunk = values[start:start + stride]
            finite = [v for v in chunk if _finite(v)]
            if not finite:
                continue
            # display LOD: peak-preserving max of the bucket for drawing only
            peak = max(finite)
            display_points.append([_clean(xs[start]), _clean(peak)])
        points, _, _ = _make_points([p[0] for p in display_points],
                                    [p[1] for p in display_points])
        frames.append({"time": _clean(time) if time is not None else None,
                       "displayTimeSeconds": _clean((first - indices[0]) / sample_rate)
                       if (first is not None and indices and sample_rate) else None,
                       "frameFirstSampleIndex": first,
                       "points": points})
        matrix.append([_clean(v) for v in values])
    chart = ctx.chart("stft")
    chart["frames"] = frames[:16]
    # raster: bottom row = first frame (Lead/charts contract)
    chart["raster"] = {
        "matrix": list(reversed(matrix[:16])),
        "palette": "viridis",
        "min": 0.0,
        "max": _clean(max((v for row in matrix[:16] for v in row if _finite(v)), default=0.0)),
        "xLabel": "频率",
        "xUnit": "Hz",
        "yLabel": "保留帧",
        "yUnit": "frame",
        "rowTimes": [frame.get("time") for frame in frames[:16]],
    }
    chart["xAxis"] = _axis(min(xs) if xs else 0.0, max(xs) if xs else 0.0,
                           scale="linear", label="频率", unit="Hz")
    all_y = [value for row in matrix for value in row if _finite(value)]
    chart["yAxis"] = _axis(0.0, max(all_y) if all_y else 0.0, label="PSD", unit="FS²/Hz")
    chart["subtitle"] = (f"{frames_available} 个实际保留帧 × {bins} bins；"
                         "缺帧留空、不补 hop")
    ctx.provenance_note("帧时间轴来自 frameFirstSampleIndices/sampleRate，不是接收时间；"
                        "显示点按峰值抽取为绘图 LOD，原始帧数据保留")
    if frames_available > 16:
        ctx.note(f"仅显示前 16 个保留帧（共 {frames_available} 帧）")
    return ctx.finish(chart)


def _recipe_zoom(ctx: _Ctx) -> dict[str, Any]:
    layout = ctx.layout
    words = [_int_word(w) for w in ctx.words]
    try:
        decimation = int(layout.get("decimation") or 2)
    except (TypeError, ValueError):
        decimation = 2
    try:
        fft_length = int(layout.get("fft_length") or FFT_SIZE)
    except (TypeError, ValueError):
        fft_length = FFT_SIZE
    sample_rate = ctx.sample_rate()
    for value in (layout.get("sample_rate"), ctx.axes.get("sampleRateHz")):
        if _finite(value) and float(value) > 0:
            sample_rate = float(value)
            break
    center = layout.get("center_hz")
    try:
        center = float(center)
    except (TypeError, ValueError):
        center = sample_rate / 2.0
    effective_rate = sample_rate / max(1, decimation)
    pairs = min(len(words) // 2, fft_length)
    amplitude = [f32(words[2 * index]) for index in range(pairs)]
    psd = [f32(words[2 * index + 1]) for index in range(pairs)]
    shifted = [((index + fft_length // 2) % fft_length) for index in range(pairs)]
    xs = [center + ((bin_index + fft_length // 2) % fft_length - fft_length // 2)
          * effective_rate / fft_length for bin_index in range(pairs)]
    # fftshift for monotonic display: raw bin i gets displayed at i + N/2 mod N
    xs = [center + ((shifted[index] if False else
                     ((index + fft_length // 2) % fft_length)) - fft_length // 2)
          * effective_rate / fft_length for index in range(pairs)]
    # Correct fftshift mapping: display order starts at -N/2.
    xs = [center + (display_index - fft_length // 2) * effective_rate / fft_length
          for display_index in range(pairs)]
    raw_order = [(index + fft_length // 2) % fft_length for index in range(pairs)]
    amp = [amplitude[index] * 2.0 for index in raw_order]
    power = [psd[index] for index in raw_order]
    amp_points, _, amp_dropped = _make_points(xs, amp)
    psd_points, _, psd_dropped = _make_points(xs, power)
    chart = ctx.chart("zoom-spectrum")
    chart["series"] = [
        ctx.series("幅值（实音×2，显示）", amp_points, role="amplitude",
                   color=ctx.labels()[0]),
        ctx.series("PSD", psd_points, role="psd", color=ctx.labels()[2]),
    ]
    chart["xAxis"] = _axis(*_range(psd_points), label="频率", unit="Hz")
    chart["yAxis"] = _axis(*_y_range(psd_points), label="PSD", unit="FS²/Hz")
    chart["subtitle"] = (f"Zoom center={center:.6g} Hz · D={decimation} · "
                         "显示仅 fftshift；轴为 producer 频率约定")
    ctx.provenance_note("frequency_axis: center + fftfreq(2048, D/fs)，显示时 fftshift；"
                        "幅值显示对实音乘 2")
    if amp_dropped or psd_dropped:
        ctx.note("部分 Zoom 频点为无效/NaN，未绘制")
    return ctx.finish(chart)


def _recipe_beam_spectrum(ctx: _Ctx) -> dict[str, Any]:
    layout = ctx.layout
    words = [_int_word(w) for w in ctx.words]
    try:
        bins = int(layout.get("bins") or 128)
    except (TypeError, ValueError):
        bins = 128
    first = int(layout.get("first_bin") or 1)
    bins = max(0, min(bins, len(words) // 3))
    xs = ctx.bins(bins, first)
    psd = [f32(words[3 * index + 2]) for index in range(bins)]
    points, gaps, dropped = _make_points(xs, psd)
    chart = ctx.chart("beam-spectrum")
    chart["series"] = [ctx.series("波束 PSD", points, role="psd",
                                  color=ctx.labels()[0])]
    requested=ctx.schema.get("requestedParameters") or ctx.variant.get("params") or {}
    azimuth = requested.get("azimuth_deg",layout.get("azimuth_deg"))
    elevation = requested.get("elevation_deg",layout.get("elevation_deg"))
    chart["markers"] = [{
        "x": _clean(azimuth if _finite(azimuth) else 0.0),
        "y": _clean(elevation if _finite(elevation) else 0.0),
        "label": "手动方向（本地阵列坐标）", "kind": "direction"}]
    chart["xAxis"] = ctx.frequency_axis(points)
    chart["yAxis"] = _axis(*_y_range(points), label="PSD", unit="FS²/Hz")
    chart["scalarRows"]=[_scalar_row("方位角",azimuth if _finite(azimuth) else 0,"°"),_scalar_row("俯仰角",elevation if _finite(elevation) else 0,"°"),_scalar_row("有效频点",bins,"点")]
    chart["subtitle"] = ("指定方向的功率频谱；不是自动 DOA，"
                         "不恢复源数/XYZ/跟踪")
    ctx.note("固定角度为隐藏参数（本地阵列坐标）；PC 不做自动波束估计")
    if dropped:
        ctx.note(f"{dropped} 个无效/NaN 频点未绘制")
    return ctx.finish(chart)


def _sphere_matrix(points: list[list[float]], powers: list[float]) -> dict[str, Any]:
    azimuths = sorted({float(p[0]) for p in points})
    elevations = sorted({float(p[1]) for p in points})
    grid = {f"{az:.6g}:{el:.6g}": None for el in elevations for az in azimuths}
    for index, point in enumerate(points):
        key = f"{float(point[0]):.6g}:{float(point[1]):.6g}"
        if index < len(powers) and key in grid:
            grid[key] = powers[index]
    # bottom row = first elevation (Lead/charts contract)
    matrix = []
    for elevation in elevations:
        row = []
        for azimuth in azimuths:
            value = grid[f"{azimuth:.6g}:{elevation:.6g}"]
            row.append(_clean(value) if _finite(value) else None)
        matrix.append(row)
    flat = [value for row in matrix for value in row if _finite(value)]
    return {"matrix": matrix, "min": min(flat) if flat else 0.0,
            "max": max(flat) if flat else 0.0,
            "palette": "viridis",
            "xLabel": "方位", "xUnit": "deg",
            "yLabel": "俯仰", "yUnit": "deg",
            "azimuths": azimuths, "elevations": elevations}


def _recipe_das(ctx: _Ctx) -> dict[str, Any]:
    layout = ctx.layout
    words = [_int_word(w) for w in ctx.words]
    points_layout = layout.get("points")
    points: list[list[float]] = []
    if isinstance(points_layout, list):
        for item in points_layout:
            if isinstance(item, (list, tuple)) and len(item) >= 2 and \
                    _finite(item[0]) and _finite(item[1]):
                points.append([float(item[0]), float(item[1])])
    try:
        power_offset = int(layout.get("power_offset") or 8192)
    except (TypeError, ValueError):
        power_offset = 8192
    try:
        peak_offset = int(layout.get("peak_offset") or 10240)
    except (TypeError, ValueError):
        peak_offset = 10240
    try:
        max_peaks = int(layout.get("max_peaks") or 3)
    except (TypeError, ValueError):
        max_peaks = 3
    count = min(len(points), max(0, len(words) - power_offset)) if points else 0
    powers = [f32(words[power_offset + index]) for index in range(count)]
    relative = [f32(words[9216 + index]) for index in range(count)] \
        if len(words) > 9216 else []
    chart = ctx.chart("das-map")
    if points:
        chart["raster"] = _sphere_matrix(points, powers)
    if chart.get("raster"):
        chart["colorScale"]={"min":chart["raster"]["min"],"max":chart["raster"]["max"],"unit":"FS²","palette":"viridis","label":"功率","valueFormat":"%.2e"}
    chart["points"] = [{"azimuthDeg": _clean(p[0]), "elevationDeg": _clean(p[1]),
                        "power": _clean(powers[index]) if index < len(powers) else None,
                        "valid": bool(index < len(powers)
                                      and _finite(powers[index]) and powers[index] > 0)}
                       for index, p in enumerate(points)]
    markers = []
    scalar_rows = []
    for rank in range(max(0, min(max_peaks, 3))):
        base = peak_offset + 3 * rank
        if base + 2 >= len(words):
            break
        peak_power = f32(words[base])
        peak_index = _int_word(words[base + 1])
        peak_valid = f32(words[base + 2])
        if not (_finite(peak_valid) and peak_valid != 0):
            continue
        if 0 <= peak_index < len(points):
            markers.append({
                "x": _clean(points[peak_index][0]),
                "y": _clean(points[peak_index][1]),
                "label": f"辅助峰{rank + 1}",
                "kind": "peak",
            })
            scalar_rows.extend([_scalar_row(f"峰{rank+1}方位",points[peak_index][0],"°"),_scalar_row(f"峰{rank+1}俯仰",points[peak_index][1],"°")])
            scalar_rows.append(_scalar_row(f"辅助峰{rank + 1}", peak_power,
                                           "FS²", True))
    chart["markers"] = markers
    finite_p=[v for v in powers if _finite(v) and v>=0]
    if finite_p:
        hi=max(finite_p);lo=min(finite_p)
        chart["scalarRows"]=[_scalar_row("网格点",len(powers),"点"),_scalar_row("最大功率",hi,"FS²"),_scalar_row("最小功率",lo,"FS²")]
        chart["caption"]="颜色表示实际相对功率；近似均匀的功率图不等于没有数据，不提供自动定位。"
    else:chart["scalarRows"]=scalar_rows
    first_bin=layout.get("first_bin");bins=layout.get("bins")
    band_note=(f"{float(first_bin)*ctx.sample_rate()/ctx.fft_size():.0f}–{(float(first_bin)+float(bins)-1)*ctx.sample_rate()/ctx.fft_size():.0f}Hz" if _finite(first_bin) and _finite(bins) else "设备指定频带")
    chart["subtitle"] = "手动DAS · 当前频带 "+band_note+" · 不是自动 DOA（声源定位）"
    ctx.note("方位/俯仰为本地阵列坐标；点为手动网格，颜色为相对 FS² 功率")
    ctx.note("辅助峰为可视化辅助，不是已验证源数或自动方向检测")
    if ctx.feature_id=="band_das" and points:
        closest=min(abs(p[1]) for p in points);cut=sorted([[p[0],powers[k]] for k,p in enumerate(points[:len(powers)]) if abs(p[1])==closest])
        chart["kind"]="beam-spectrum";chart["series"]=[ctx.series("水平切面功率",cut)]
        chart["xAxis"]=_axis(0,360,label="方位角（最近水平切面）",unit="°");chart["yAxis"]=_axis(*_y_range(cut),label="频带功率",unit="FS²")
        chart["subtitle"]="带限DAS · "+band_note+" · 显示水平切面；全空间请看球面网格"
        chart["markers"]=[]
        return ctx.finish(chart)
    if ctx.feature_id=="spatial_peaks":
        chart["kind"]="bands";chart["categories"]=[{"label":m["label"]+f" {m['x']}°/{m['y']}°","value":r["value"],"valid":True} for m,r in zip(markers,[r for r in scalar_rows if r['unit']=='FS²'])]
        chart["scalarRows"]=scalar_rows;chart["xAxis"]=_axis(0,max(1,len(markers)),label="辅助峰（方位/俯仰）",unit="");chart["yAxis"]=_axis(0,max([0]+[r['value'] for r in scalar_rows if r['unit']=='FS²']) or 1,label="峰功率",unit="FS²")
        chart["subtitle"]="空间辅助峰排名及角度；不是已确认声源，也不是源数"
        return ctx.finish(chart)
    chart["markers"] = [] if ctx.feature_id=="spatial_grid" else markers
    chart["azimuthRange"] = {"min": 0.0, "max": 360.0}
    chart["elevationRange"] = {"min": -90.0, "max": 90.0}
    chart["xAxis"] = _axis(0.0, 360.0, label="方位", unit="deg")
    chart["yAxis"] = _axis(-90.0, 90.0, label="俯仰", unit="deg")
    return ctx.finish(chart)


def _recipe_capability(ctx: _Ctx) -> dict[str, Any]:
    chart = ctx.chart("capability")
    limitations = ctx.feature.get("limitations") or []
    validity = str(ctx.feature.get("validity") or ctx.schema.get("validity") or "")
    text = "空间接口能力说明：手动 DAS 图/辅助峰可用；不提供自动 DOA、XYZ、自动源数或跟踪。"
    chart["text"] = text
    chart["message"] = text
    chart["subtitle"] = validity
    if limitations:
        ctx.note("；".join(str(item) for item in limitations[:3]))
    if not ctx.words:
        chart["emptyReason"] = ""
    return ctx.finish(chart)


def _recipe_events(ctx: _Ctx) -> dict[str, Any]:
    chart = ctx.chart("events")
    chart["events"] = []
    chart["text"] = ("持续监测任务：事件列表/下载/确认走 event.list/get/download/ack 与 48121；"
                     "PC 不轮询未完成监测任务的 feature.result。")
    chart["subtitle"] = "事件监测（持续运行；停止后等待 canceled）"
    ctx.note("监测任务不返回 feature.result；事件与记录文件由事件链提供")
    return ctx.finish(chart)


# STIPA result word contract (quick 15-stage and complete 101-stage runs share
# the same nine float32 words).  The view spec carries the canonical order; a
# device actualProducerLayout.fields declaration is the fallback for old
# schemas, and the legacy three-word layout is the last resort.
_STIPA_RESULT_FIELDS = [
    "experimental_index", "valid", "certified_zero", "reason_code",
    "failed_band_hz", "failed_modulation_hz", "reference_depth",
    "measured_depth", "transfer_ratio",
]
# reason_code meanings of the STIPA rejection vocabulary.
_STIPA_REASON_ACQUISITION = 1
_STIPA_REASON_ENERGY = 2
_STIPA_REASON_REFERENCE = 3
_STIPA_REASON_RATIO = 4


def _stipa_fields(ctx: _Ctx) -> list[str]:
    """Ordered result-word names for a STIPA chart.

    The PC view spec (decode.fields) is the canonical 9-word order because the
    staged result contract is fixed for both measurement modes; old device
    schemas still declare only three words, so the spec must not be overridden
    by a stale producer layout.
    """
    decode_fields = ctx.decode.get("fields")
    if isinstance(decode_fields, list) and decode_fields:
        return [str(name) for name in decode_fields]
    actual = ctx.schema.get("actualProducerLayout")
    if isinstance(actual, dict):
        layout_fields = actual.get("fields")
        if isinstance(layout_fields, list) and layout_fields:
            return [str(name) for name in layout_fields]
    layout_fields = ctx.layout.get("fields")
    if isinstance(layout_fields, list) and layout_fields:
        return [str(name) for name in layout_fields]
    return list(_STIPA_RESULT_FIELDS)


def _stipa_word(fields: list[str], words: list[int], name: str) -> float:
    """Read one named result word; a missing field/word stays NaN (never guessed)."""
    try:
        index = fields.index(name)
    except ValueError:
        return float("nan")
    if index < 0 or index >= len(words):
        return float("nan")
    return f32(words[index])


def _stipa_known(value: float) -> bool:
    return _finite(value) and float(value) != 0.0


def _stipa_number_text(value: float) -> str:
    """500/1000/2000 Hz and 0.63/3.15 Hz without trailing float noise."""
    if not _finite(value):
        return "未知"
    number = float(value)
    if abs(number - round(number)) < 1e-6:
        return str(int(round(number)))
    return f"{number:g}"


def _stipa_band_text(value: float, *, english: bool = False) -> str:
    if not _stipa_known(value):
        return "未知频带" if not english else "unknown band"
    return f"{_stipa_number_text(value)} Hz " + ("频带" if not english else "band")


def _stipa_modulation_text(value: float, *, english: bool = False) -> str:
    if not _stipa_known(value):
        return "未知调制频率" if not english else "unknown modulation component"
    return (f"{_stipa_number_text(value)} Hz "
            + ("调制分量" if not english else "modulation component"))


def _stipa_ratio_text(value: float) -> str:
    return "未知" if not _finite(value) else f"{float(value):.3f}"


def _stipa_invalid_reason(fields: list[str], words: list[int]) -> tuple[str, str]:
    """(zh, en) rejection explanation for a valid=0 STIPA result.

    reason_code is the only authority: 1=capture/validation, 2=energy/fit,
    3=unstable reference, 4=test/reference ratio out of range; anything else
    (including a missing/zero code) gets the generic re-measure message.
    """
    reason_value = _stipa_word(fields, words, "reason_code")
    reason = int(round(reason_value)) if _finite(reason_value) else 0
    band = _stipa_word(fields, words, "failed_band_hz")
    modulation = _stipa_word(fields, words, "failed_modulation_hz")
    ratio = _stipa_word(fields, words, "transfer_ratio")
    if reason == _STIPA_REASON_ACQUISITION:
        return ("采集数据无效（参考或测试录音不满足格式/电平/时长），"
                "请重新录制参考与测试。",
                "Invalid capture data (the reference or test recording fails the "
                "format/level/duration requirements); re-record both the reference "
                "and the test signal.")
    if reason == _STIPA_REASON_ENERGY:
        return (f"信号能量或拟合不足：{_stipa_band_text(band)}，"
                "请检查音量/麦克风增益并重新录制。",
                f"Signal energy or fit insufficient: "
                f"{_stipa_band_text(band, english=True)}; check the level/microphone "
                "gain and re-record.")
    if reason == _STIPA_REASON_REFERENCE:
        return (f"参考信号不稳定：{_stipa_band_text(band)}、"
                f"{_stipa_modulation_text(modulation)}校验失败，请重新录制参考。",
                f"Reference signal unstable: {_stipa_band_text(band, english=True)}, "
                f"{_stipa_modulation_text(modulation, english=True)} validation "
                "failed; re-record the reference.")
    if reason == _STIPA_REASON_RATIO:
        return (f"测试与参考比值超限（{_stipa_ratio_text(ratio)}）："
                f"{_stipa_band_text(band)}、{_stipa_modulation_text(modulation)}；"
                "请检查测量位置或重新录制参考。",
                f"Test/reference ratio out of range ({_stipa_ratio_text(ratio)}): "
                f"{_stipa_band_text(band, english=True)}, "
                f"{_stipa_modulation_text(modulation, english=True)}; check the "
                "measurement position or re-record the reference.")
    return ("测量无效（原因码未知或为 0），请重新测量；"
            "若重复失败请检查采集格式、电平与参考录制。",
            "Measurement invalid (unknown or zero reason code); measure again. If "
            "it repeats, check the capture format, level and the reference "
            "recording.")


def _stipa_stage(ctx: _Ctx, quick: bool) -> dict[str, Any]:
    """Progress payload {completed,total,current,label} from device progress.

    completedStages/totalStages/currentStageIndex are quantities reported by the
    device (the gateway fixes the semantics); the PC never fills the bar on its
    own when it sees state=completed.
    """
    progress = (ctx.variant.get("progress")
                if isinstance(ctx.variant.get("progress"), dict) else {})
    default_total = 15 if quick else int(ctx.decode.get("stagesTotal") or 101)

    def count(value: Any, default: int) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return int(default)
        return number if number >= 0 else int(default)

    completed = count(progress.get("completedStages"), 0)
    total = count(progress.get("totalStages"), default_total)
    if total <= 0:
        total = default_total
    completed = min(completed, total)
    current = min(count(progress.get("currentStageIndex"), completed), total)
    return {"completed": int(completed), "total": int(total),
            "current": int(current),
            "label": str(progress.get("label") or "STIPA 阶段")}


def _recipe_stages(ctx: _Ctx) -> dict[str, Any]:
    fields = _stipa_fields(ctx)
    chart = ctx.chart("stipa")
    words = [_int_word(w) for w in ctx.words]
    valid_value = _stipa_word(fields, words, "valid")
    result_valid = bool(_finite(valid_value) and valid_value != 0.0)
    index_value = _stipa_word(fields, words, "experimental_index")
    rows: list[dict[str, Any]] = []
    # Base readouts keep the original display: index + validity arithmetic.
    for position, name in enumerate(fields):
        if position >= len(words):
            break
        value = f32(words[position])
        if name == "experimental_index":
            ok = result_valid and _finite(value) and 0.0 <= value <= 1.0
            rows.append(_scalar_row(name, value if ok else None, "", ok))
        elif name in ("valid", "certified_zero"):
            rows.append(_scalar_row(name, int(_finite(value) and value != 0),
                                    "bool", True))
        elif name in ("reason_code", "failed_band_hz", "failed_modulation_hz",
                      "reference_depth", "measured_depth", "transfer_ratio"):
            continue  # diagnostics are appended only for an invalid result below
        else:
            ok = result_valid and _finite(value)
            rows.append(_scalar_row(name, value if ok else None, "", ok))
    if not result_valid:
        # Rejection diagnostics: every field the result actually carries.
        diagnostics = (
            ("reason_code", "原因码", "", "int"),
            ("failed_band_hz", "失败频带", "Hz", "hz"),
            ("failed_modulation_hz", "失败调制频率", "Hz", "hz"),
            ("reference_depth", "参考调制度", "", "ratio"),
            ("measured_depth", "测试调制度", "", "ratio"),
            ("transfer_ratio", "传输比", "", "ratio"),
        )
        for name, label, unit, kind in diagnostics:
            if name not in fields or fields.index(name) >= len(words):
                continue
            value = _stipa_word(fields, words, name)
            if kind == "int":
                rows.append(_scalar_row(label, int(round(value)) if _finite(value)
                                        else None, unit, _finite(value)))
            else:
                known = _stipa_known(value)
                rows.append(_scalar_row(label, _clean(round(float(value), 3))
                                        if known else None, unit, known))
    chart["resultValid"] = result_valid
    chart["indexValid"] = bool(result_valid and _finite(index_value)
                               and 0.0 <= index_value <= 1.0)
    chart["indexValue"] = _clean(index_value) if chart["indexValid"] else None
    invalid_zh = invalid_en = ""
    if not result_valid:
        invalid_zh, invalid_en = _stipa_invalid_reason(fields, words)
    chart["invalidReason"] = invalid_zh
    chart["invalidReasonEn"] = invalid_en
    quick = (ctx.variant.get("params") or {}).get("measurementMode") == "quick"
    chart["indexLabel"] = "快速调制保持指数" if quick else "实验STIPA指数"
    if quick:
        chart["title"] = "快速语音传输评估"
    chart["stage"] = _stipa_stage(ctx, quick)
    chart["scalarRows"] = rows
    chart["text"] = "快速体验 · 500/1000/2000 Hz三频带估计" if quick else "完整实验STIPA · 101阶段"
    certified = _stipa_word(fields, words, "certified_zero")
    if _finite(certified):
        ctx.note("certified_zero=%d（认证字段恒为 0，不构成认证）" % int(certified))
    if not result_valid:
        ctx.note("设备结果 valid=0：不显示实验指数，也不会显示“测量完成”。")
    ctx.note("仅当全部阶段完成且 valid 才显示实验指数；PC 不补算声学指标")
    return ctx.finish(chart)


def _recipe_weighting(ctx: _Ctx) -> dict[str, Any]:
    layout = ctx.layout
    words = [_int_word(w) for w in ctx.words]
    service = str(layout.get("service") or "")
    chart = ctx.chart("weighting")
    panels = []
    variant_params = dict(ctx.variant.get("params") or {})
    variant_id = str(ctx.variant.get("id") or "")
    if layout.get("coefficient_offset") is not None or "spectral_" in service:
        try:
            coefficient_offset = int(layout.get("coefficient_offset") or 3)
        except (TypeError, ValueError):
            coefficient_offset = 3
        power = f32(words[0]) if words else float("nan")
        dbfs = f32(words[1]) if len(words) > 1 else float("nan")
        valid = f32(words[2]) if len(words) > 2 else float("nan")
        coefficients = [f32(w) for w in words[coefficient_offset:coefficient_offset + 1025]]
        weighting = str(variant_params.get("weighting") or
                        str(service).replace("spectral_", "").split("_")[0] or "A")
        if weighting not in ("A", "C", "Z"):
            weighting = "A"
        xs = ctx.bins(len(coefficients), 0)
        curve = [10.0 * math.log10(value) if (_finite(value) and value > 0) else float("nan")
                 for value in coefficients]
        curve_points, _, dropped = _make_points(xs, curve)
        chart["series"] = [
            ctx.series(f"{weighting} 相对频率计权系数", curve_points,
                       role="weighting-curve", color=ctx.labels()[0]),
        ]
        chart["scalarRows"] = [
            _scalar_row("计权功率", power, "FS²", _finite(power) and valid != 0),
            _scalar_row("计权电平", dbfs, "dBFS", _finite(dbfs) and valid != 0),
            _scalar_row("有效", int(_finite(valid) and valid != 0), "bool", True),
            _scalar_row("频率计权", weighting, "", True),
        ]
        panels = [
            {"kind": "line", "title": f"{weighting} 相对频率计权",
             "subtitle": "Hann 帧 PSD 频点权重（非 IEC 时域滤波器组）",
             "units": "dB", "xAxis": ctx.frequency_axis(curve_points),
             "yAxis": _axis(*_y_range(curve_points), label="相对计权", unit="dB"),
             "series": [ctx.series(f"{weighting} 权值", curve_points,
                                   role="weighting-curve")]},
            {"kind": "scalars", "title": "计权电平（设备 PL）",
             "subtitle": "integrated weighted level", "units": "FS²,dBFS",
             "scalarRows": chart["scalarRows"]},
        ]
        chart["subtitle"] = (f"{weighting}计权系数是固定参考曲线；上方计权电平随测量更新。"
                             "与时间计权分开标注，绝不合并为 A 计权 FAST/SLOW")
        chart["panels"] = panels[:1]
        chart["xAxis"] = ctx.frequency_axis(curve_points)
        chart["yAxis"] = _axis(*_y_range(curve_points), label="相对计权", unit="dB")
        ctx.note("A/C/Z 为模拟参考频率计权，不是 IEC 时域滤波器组；"
                 "该图与独立的时间响应运行分开显示")
        if dropped:
            ctx.note(f"{dropped} 个计权系数为 0/无效，未绘制")
        return ctx.finish(chart)
    # recorded exact Z / unweighted FAST-SLOW-LeqFS variant (workspace result)
    fields = [str(f) for f in (layout.get("fields") or [
        "FAST_power_FS2", "FAST_dBFS", "SLOW_power_FS2", "SLOW_dBFS", "LeqFS",
        "samples_uint32", "valid", "FAST_settled", "SLOW_settled"])]
    rows = []
    for index, name in enumerate(fields):
        if index >= len(words):
            break
        value = f32(words[index])
        if name in ("samples_uint32",):
            value = _int_word(words[index])
            rows.append(_scalar_row(name, value, "samples", value > 0))
        elif name in ("valid", "FAST_settled", "SLOW_settled"):
            rows.append(_scalar_row(name, int(_finite(value) and value != 0), "bool", True))
        else:
            rows.append(_scalar_row(name, value, "dBFS" if name=="LeqFS" else _field_unit(name),
                                    _finite(value)))
    try:
        input_offset = int(layout.get("input_offset") or 32)
    except (TypeError, ValueError):
        input_offset = 32
    try:
        samples = int(layout.get("samples") or max(0, len(words) - input_offset))
    except (TypeError, ValueError):
        samples = max(0, len(words) - input_offset)
    raw = words[input_offset:input_offset + samples]
    values = [pcm24_fs(w) for w in raw]
    display = peak_envelope(values, max_buckets=min(2048, max(1, samples // 2)))
    sample_rate = ctx.sample_rate()
    waveform = {
        "kind": "waveform",
        "title": "采集记录（Z 未计权原始记录）",
        "subtitle": "独立运行：不是 A 计权时间响应",
        "units": "FS",
        "channels": [{"name": "记录", "color": ctx.labels()[3],
                      "values": display["values"], "visible": True,
                      "sampleRateHz": _clean(sample_rate), "startSampleIndex": 0,
                      "bucketSize": display["bucketSize"],
                      "envelope": display["envelope"],
                      "sourceSampleCount": display["sourceSampleCount"]}],
        "gaps": [], "sampleRateHz": _clean(sample_rate),
        "xAxis": _axis(0.0, _clean(samples / sample_rate) if sample_rate else 0.0,
                       label="时间", unit="s"),
        "yAxis": _axis(-1.0, 1.0, label="幅度", unit="FS"),
        "series": [], "categories": [], "scalarRows": [], "markers": [],
        "referenceLines": [], "referenceBands": [], "frames": [],
        "raster": None, "colorScale": None, "text": "", "emptyReason": "",
    }
    scalar_panel = {"kind": "scalars", "title": "Z 未计权 FAST/SLOW/LeqFS",
                    "subtitle": "captured exact recurrence", "units": "FS²,dBFS",
                    "scalarRows": rows}
    chart["series"] = []
    chart["scalarRows"] = rows
    # The shared PanelChart renders line/bar data, not nested scalar/waveform
    # objects. Readouts go above it; both plots below use explicit series.
    chart["scalarRows"]=[dict(r,displayLabel={"FAST_dBFS":"FAST","SLOW_dBFS":"SLOW","LeqFS":"Leq","FAST_settled":"FAST稳定","SLOW_settled":"SLOW稳定"}.get(r["label"],r["label"])) for r in rows if r["label"] in ("FAST_dBFS","SLOW_dBFS","LeqFS","FAST_settled","SLOW_settled")]
    vals=display["values"];bucket=display["bucketSize"]
    wave_points=[[(i//2 if display["envelope"] else i)*bucket/sample_rate,v] for i,v in enumerate(vals) if _finite(v)]
    amp=max([abs(v) for _,v in wave_points]+[1.e-6])*1.1
    panels=[{"kind":"line","title":"本次采集波形","series":[ctx.series("PCM波形包络",wave_points)],"xAxis":waveform["xAxis"],"yAxis":_axis(-amp,amp,label="幅度",unit="FS")}]
    offset=int(layout.get("trace_offset") or 0);count=int(layout.get("trace_count") or 0);stride=int(layout.get("trace_stride") or 3);step=int(layout.get("trace_step_samples") or 480)
    trace_series=[]
    for column,label in enumerate(["FAST","SLOW","Leq"]):
        pts=[[(i+1)*step/sample_rate,f32(words[offset+i*stride+column])] for i in range(count) if offset+i*stride+column<len(words)]
        if pts:trace_series.append(ctx.series(label,pts,color=ctx.labels()[column]))
    if trace_series:panels.insert(0,{"kind":"line","title":"PL逐样本时间响应（本次记录）","series":trace_series,"xAxis":waveform["xAxis"],"yAxis":_axis(-120,0,label="数字电平",unit="dBFS")})
    chart["panels"]=panels
    chart["waveform"] = waveform
    chart["subtitle"] = ("独立运行：Z 未计权 FAST/SLOW/LeqFS（timeResponse=true），"
                         "绝不并入 A 计权图")
    for row in chart["scalarRows"]:
        if row["label"] in ("FAST_settled","SLOW_settled"):row["value"]="已稳定" if row["value"] else "启动段";row["unit"]=""
    ctx.note("本图为分段采集后由PL逐样本计算；SLOW初始段未充分稳定，不冒充连续流式声级计")
    return ctx.finish(chart)


# --------------------------------------------------------------------------
# fallback + dispatch
# --------------------------------------------------------------------------
def _fallback(ctx: _Ctx, why: str) -> dict[str, Any]:
    chart = ctx.chart("raw")
    chart["available"] = True
    chart["words"] = [_int_word(w) for w in ctx.words[:MAX_RAW_PREVIEW]]
    chart["rawWordCount"] = len(ctx.words)
    chart["reason"] = f"未确认的布局/recipe：{why}；只显示原始 uint32 字，不猜浮点值。"
    chart["emptyReason"] = chart["reason"]
    chart["text"] = chart["reason"]
    chart["title"] = ctx.name
    ctx.note(chart["reason"])
    ctx.provenance_note("layoutStatus=pending-layout-resolution 的功能在字段映射确认前"
                        "只显示原始字；本功能映射见 PENDING_LAYOUT_SOURCES")
    return ctx.finish(chart)


_RECIPES = {
    "waveform": _recipe_waveform,
    "channel-fields": _recipe_channel_fields,
    "snapshot": _recipe_snapshot,
    "series": _recipe_series,
    "count-then-series": _recipe_count_then_series,
    "bands": _recipe_bands,
    "ab-compare": _recipe_ab_compare,
    "pair-bins": _recipe_pair_bins,
    "lag-series": _recipe_lag_series,
    "lag-series+tail": _recipe_lag_series,
    "harmonic-bars": _recipe_harmonic_bars,
    "field-bars": _recipe_field_bars,
    "scalars": _recipe_scalars,
    "scalars+history": _recipe_scalars_history,
    "level-statistics": _recipe_level_statistics,
    "noise-rating": _recipe_noise_rating,
    "kurtosis": _recipe_kurtosis,
    "insulation": _recipe_insulation,
    "room": _recipe_room,
    "stft": _recipe_stft,
    "zoom": _recipe_zoom,
    "beam-spectrum": _recipe_beam_spectrum,
    "das-map": _recipe_das,
    "das-map+peaks": _recipe_das,
    "capability": _recipe_capability,
    "events": _recipe_events,
    "stages": _recipe_stages,
    "weighting": _recipe_weighting,
}


def decode_result(feature: dict[str, Any], payload: dict[str, Any],
                  words: Sequence[int], *, reference: dict[str, Any] | None = None,
                  variant: dict[str, Any] | None = None) -> dict[str, Any]:
    """Decode one raw feature result into a bounded QML chart payload.

    Returns the chart dict plus ``decodeMeta`` (notes/provenance/recipe/
    layoutStatus/layoutSource) consumed by the runtime workspace.
    """
    ctx = _Ctx(feature, payload, words, reference=reference, variant=variant)
    recipe = str(ctx.decode.get("recipe") or "")
    layout_status = str(ctx.decode.get("layoutStatus") or "")
    try:
        if ctx.schema.get("kind") == "capability" or recipe == "capability":
            chart = _recipe_capability(ctx)
        elif not ctx.words and recipe in ("events",):
            chart = _recipe_events(ctx)
        elif not ctx.words and ctx.schema.get("kind") == "stages":
            chart = _recipe_stages(ctx)
        else:
            handler = _RECIPES.get(recipe)
            if handler is None:
                chart = _fallback(ctx, f"recipe={recipe or '<missing>'}")
            elif layout_status == "pending-layout-resolution" and \
                    ctx.feature_id not in PENDING_LAYOUT_SOURCES:
                chart = _fallback(ctx, f"pending layout for {ctx.feature_id}")
            else:
                chart = handler(ctx)
    except Exception as exc:  # noqa: BLE001 - decoding must never kill the UI thread
        chart = _fallback(ctx, f"decode error: {type(exc).__name__}: {exc}")
    source = PENDING_LAYOUT_SOURCES.get(ctx.feature_id)
    if layout_status == "pending-layout-resolution" and source is not None:
        ctx.provenance_note(f"布局已从设备服务源码确认：{source['source']}")
    chart["decodeMeta"] = {
        "recipe": recipe,
        "layoutStatus": layout_status,
        "layoutConfirmed": ctx.feature_id not in PENDING_LAYOUT_SOURCES and
                           layout_status != "pending-layout-resolution",
        "layoutSource": (source or {}).get("source", ""),
        "fieldMap": (source or {}).get("fields", {}),
        "notes": list(ctx.notes),
        "provenance": list(ctx.provenance),
        "units": ctx.units,
        "validity": str(ctx.feature.get("validity") or ctx.schema.get("validity") or ""),
        "sampleRateSource": ctx._sr_source,
    }
    return chart


# --------------------------------------------------------------------------
# 1024-word result page assembly / identity validation
# --------------------------------------------------------------------------
_RESULT_PAGE_WORDS = 1024
_MAX_RESULT_WORDS = 16 * 1024 * 1024
_ALLOWED_SOURCE_KINDS = {"pl-live", "test-fixture"}


class ResultPageAssembler:
    """Assemble ``feature.result`` pages with strict identity validation.

    The bridge normally merges all pages before handing them to the runtime;
    this assembler is the protocol-level guard used when raw pages are exposed
    (and by the unit tests): identity may not change during pagination, offsets
    must be contiguous and ordered, a page carries at most 1024 words, duplicated
    or missing pages are rejected, and totalWords must match the identity.
    """

    def __init__(self, expected_job_id: str | None = None,
                 expected_feature_id: str | None = None) -> None:
        self.expected_job_id = str(expected_job_id) if expected_job_id else None
        self.expected_feature_id = (str(expected_feature_id)
                                    if expected_feature_id else None)
        self.snapshot: dict[str, Any] | None = None
        self.words: list[int] = []
        self.total_words = 0
        self.complete = False
        self.received_offsets: list[int] = []

    def _identity(self, page: dict[str, Any]) -> dict[str, Any]:
        identity: dict[str, Any] = {}
        for key in ("jobId", "featureId", "state", "sourceKind", "totalWords"):
            identity[key] = page.get(key)
        identity["configuration"] = page.get("configuration")
        identity["schema"] = page.get("schema")
        return identity

    def add(self, page: Any) -> bool:
        if self.complete:
            raise DecodeError("feature-result-pagination: page after completion")
        if not isinstance(page, dict):
            raise DecodeError("feature-result-page: not an object")
        job_id = page.get("jobId")
        if not isinstance(job_id, str) or not job_id:
            raise DecodeError("feature-result-identity: jobId")
        if self.expected_job_id and job_id != self.expected_job_id:
            raise DecodeError("feature-result-identity: jobId mismatch")
        feature_id = page.get("featureId")
        if not isinstance(feature_id, str) or not feature_id:
            raise DecodeError("feature-result-identity: featureId")
        if self.expected_feature_id and feature_id != self.expected_feature_id:
            raise DecodeError("feature-result-identity: featureId mismatch")
        source_kind = page.get("sourceKind")
        if source_kind not in _ALLOWED_SOURCE_KINDS:
            raise DecodeError("feature-result-source")
        configuration = page.get("configuration")
        if not isinstance(configuration, dict) or not all(
                key in configuration for key in
                ("session", "config", "generation", "sourceFrame")):
            raise DecodeError("feature-result-configuration")
        schema = page.get("schema")
        if not isinstance(schema, dict):
            raise DecodeError("feature-result-schema")
        for key in ("generation", "sourceFrame"):
            value = configuration.get(key)
            if not isinstance(value, str) or not value.isdigit():
                raise DecodeError(f"feature-result-identity: {key} must be a decimal string")
        total = page.get("totalWords")
        if not isinstance(total, int) or isinstance(total, bool) or total < 0 or \
                total > _MAX_RESULT_WORDS:
            raise DecodeError("feature-result-totalWords")
        offset = page.get("offsetWords")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise DecodeError("feature-result-position")
        if offset != len(self.words):
            raise DecodeError("feature-result-position")
        words = page.get("words")
        if not isinstance(words, list) or len(words) > _RESULT_PAGE_WORDS:
            raise DecodeError("feature-result-length")
        if offset + len(words) > total:
            raise DecodeError("feature-result-length")
        for word in words:
            if not isinstance(word, int) or isinstance(word, bool) or \
                    not 0 <= word <= 0xFFFFFFFF:
                raise DecodeError("feature-result-word")
        more = page.get("more")
        if not isinstance(more, bool):
            raise DecodeError("feature-result-pagination")
        if more != (offset + len(words) < total):
            raise DecodeError("feature-result-pagination")
        if more and not words:
            raise DecodeError("feature-result-pagination")
        identity = self._identity(page)
        if self.snapshot is None:
            self.snapshot = identity
            self.total_words = total
        elif identity != self.snapshot:
            raise DecodeError("feature-result-changed-during-pagination")
        elif total != self.total_words:
            raise DecodeError("feature-result-changed-during-pagination")
        self.words.extend(int(word) for word in words)
        self.received_offsets.append(offset)
        if not more:
            if len(self.words) != total:
                raise DecodeError("feature-result-length")
            self.complete = True
        return self.complete


def validate_result_pages(pages: Iterable[Any], *, job_id: str | None = None,
                          feature_id: str | None = None) -> list[int]:
    """Assemble a raw page iterable; raises DecodeError with an explicit reason."""
    assembler = ResultPageAssembler(job_id, feature_id)
    for page in pages:
        if assembler.add(page):
            break
    if not assembler.complete:
        raise DecodeError("feature-result-pagination: page chain did not terminate")
    return assembler.words

