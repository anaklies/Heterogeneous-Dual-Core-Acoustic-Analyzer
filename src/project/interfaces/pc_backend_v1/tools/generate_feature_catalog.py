#!/usr/bin/env python3
"""Generate the product feature catalog from the real FUNCTION_EXECUTION_MAP.csv.

Rules (documented, not invented per row):
- Every CSV row becomes exactly one feature with the same stable featureId.
- status is derived from the recorded evidence only; nothing is promoted to
  "available" without board acceptance evidence.
- Removed automatic DOA rows become "unsupported" (user decision 2026-10-24).
- PL microprogram-native services are "experimental" (native values validated,
  whole-service RTL/board not accepted).
- Features whose evidence gate is physical capture/board connectivity are
  "not_ready" until a real board link is accepted.

Run: python interfaces/pc_backend_v1/tools/generate_feature_catalog.py
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CSV = ROOT / "deployment/work_platform_20261013/phase15_analysis_only_20261023/integration/FUNCTION_EXECUTION_MAP.csv"
OUT_JSON = Path(__file__).resolve().parents[1] / "features/FEATURE_CATALOG.json"
OUT_MD = Path(__file__).resolve().parents[1] / "features/FEATURE_CATALOG.md"
FROZEN_AT = "2026-10-24"

GROUPS = {
    "input_levels": ["io_pcm", "levels_core", "data_continuity", "levels_extended", "signal_quality"],
    "spectrum": ["fft", "psd", "stft", "spectrum_average", "peak_hold", "smoothing",
                 "spectrum_freeze", "relative_limit", "zoom_fft"],
    "frequency": ["frequency_tracking", "frequency_drift", "centroid", "flatness",
                  "cepstrum", "spectral_kurtosis"],
    "spatial": ["spatial_interface", "directed_das", "full_das", "band_das",
                "spatial_grid", "spatial_peaks"],
    "correlation": ["csd", "coherence_phase", "cross_correlation", "gcc_phat", "autocorrelation"],
    "events": ["event_trigger", "energy_change", "band_tracking", "spectral_flux"],
    "weighting_stats": ["frequency_time_weighting", "level_statistics", "relative_insulation"],
    "octave": ["octave", "third_octave"],
    "periodic": ["fundamental", "harmonic_ratio", "sidebands", "envelope_hilbert",
                 "envelope_spectrum", "modulation_spectrum"],
    "room": ["room_decay", "room_clarity", "spectral_decay", "stipa_experimental", "noise_rating"],
    "removed": ["srpdnn_main"],
}

# Units / input requirements / update method are taken from the real service
# metadata where it exists (PROFILE.json / service files), otherwise recorded as
# "not_specified" instead of guessing.
META = {
    "io_pcm": ("digital full scale (24-bit PCM codes)", "six I2S channels, raw ring", "continuous"),
    "levels_core": ("dBFS / ratio", "six channels FFT+time domain", "per FFT window (~11.72 Hz candidate)"),
    "data_continuity": ("count / flag", "raw frames + window timeline", "per window"),
    "fft": ("FS amplitude per bin", "2048-sample window, 1025 bins", "per window"),
    "psd": ("FS^2/Hz (Welch cumulative)", "selected channel, 2048 Hann, non-overlapping retained frames", "per P1 carousel"),
    "stft": ("FS^2/Hz", "2048-sample window, hop 512", "per window"),
    "spectrum_average": ("FS^2/bin", "shared FFT + scalar history", "per P1 carousel"),
    "spatial_interface": ("m / unit vector (interface only)", "shared FFT + scalar programs", "per service publication"),
    "signal_quality": ("validity flags", "window timeline + fault words", "per window"),
    "levels_extended": ("dBFS / ratio", "six channels", "per window"),
    "octave": ("FS^2 relative band energy", "2048 FFT bins 1..966", "per P1 carousel"),
    "third_octave": ("FS^2 relative band energy", "2048 FFT bins 2..767", "per P1 carousel"),
    "peak_hold": ("FS^2/bin", "shared FFT + history", "per P1 carousel"),
    "smoothing": ("FS^2/bin", "triangular smoothing over 1025 bins", "per P1 carousel"),
    "frequency_tracking": ("Hz", "dominant FFT peak", "per P1 carousel"),
    "frequency_drift": ("Hz, Hz/s", "dominant FFT peak + history", "per P1 carousel"),
    "directed_das": ("FS^2/Hz (user-specified direction)", "shared FFT + user direction", "per P2 task"),
    "csd": ("FS^2/Hz, rad, dimensionless", "selected channel pair, 1025 bins, count>=2", "per P2 task"),
    "coherence_phase": ("dimensionless, rad", "same as CSD", "per P2 task"),
    "energy_change": ("FS^2 ratio", "temporal features", "per P1 carousel"),
    "band_tracking": ("FS^2 per band", "temporal features + band edges", "per P1 carousel"),
    "centroid": ("Hz", "spectral shape", "per P1 carousel"),
    "flatness": ("dimensionless", "spectral shape", "per P1 carousel"),
    "event_trigger": ("event record + flags", "feature/detector/recorder + clip mailbox", "on event"),
    "frequency_time_weighting": ("A/C/Z weighting, FAST/SLOW", "every raw frame required", "per raw frame (not guaranteed by ordinary P1 carousel)"),
    "level_statistics": ("LeqFS, L10/L50/L90", "level history", "per P1 carousel"),
    "zoom_fft": ("FS^2/bin", "P2 spectrum zoom", "per P2 task"),
    "fundamental": ("Hz", "1024-sample linear correlation, default 100-2000 Hz", "per P2 task"),
    "harmonic_ratio": ("ratio / %", "fundamental + harmonics", "per P2 task"),
    "sidebands": ("ratio", "specified carrier + sidebands", "per P2 task"),
    "envelope_hilbert": ("FS envelope", "Hilbert transform chain", "per P2 task"),
    "envelope_spectrum": ("FS^2/bin", "envelope spectrum chain", "per P2 task"),
    "modulation_spectrum": ("FS^2/bin", "modulation chain", "per P2 task"),
    "autocorrelation": ("normalized correlation", "linear correlation, 1024 samples", "per P2 task"),
    "full_das": ("FS^2 (user-scan map)", "shared FFT + scan grid", "per P2 task"),
    "band_das": ("FS^2 (band-limited map)", "shared FFT + band grid", "per P2 task"),
    "cross_correlation": ("samples / normalized", "channel pair linear correlation", "per P2 task"),
    "gcc_phat": ("samples (delay observation)", "channel pair PHAT correlation", "per P2 task"),
    "spectral_flux": ("FS^2 delta", "spectral history", "per P1 carousel"),
    "spectrum_freeze": ("stored spectrum + ratio", "analysis statistics A/B", "per P1 carousel"),
    "relative_limit": ("ratio vs limit", "analysis statistics A/B", "per P1 carousel"),
    "cepstrum": ("real cepstrum", "P2 chain", "per P2 task"),
    "spectral_kurtosis": ("kurtosis prototype", "P2 spectrum", "per P2 task"),
    "spatial_grid": ("unit sphere grid", "shared FFT", "per P2 task"),
    "spatial_peaks": ("local peaks (assist only)", "spatial map", "per P2 task"),
    "room_decay": ("EDT/T20/T30 seconds", "impulse response capture", "per P2 task"),
    "relative_insulation": ("relative band difference", "two measurement positions", "per P2 task"),
    "stipa_experimental": ("uncalibrated STIPA prototype", "captured dual trace + finite stage graph", "staged high-cost graph"),
    "noise_rating": ("NC/NR relative prototype", "third-octave levels", "per P2 task"),
    "room_clarity": ("C50/C80/D50", "impulse response", "per P2 task"),
    "spectral_decay": ("per-band decay data", "impulse response", "per P2 task"),
    "srpdnn_main": ("n/a", "removed", "removed"),
}

QUALITY = {
    "not_ready": "物理采集/整机链路未验收；当前只能解析、存储、回放与夹具测试，不得显示为实时测量。",
    "experimental": "PL 微程序原生数值已验证但整服务 RTL/整机未验收；只可作为实验功能，不得宣称认证/实时实板测量。",
    "unsupported": "用户已取消的自动定位能力；不实现、不恢复、不聚合进产品。",
}


def derive_status(row: dict) -> tuple[str, str]:
    if row["hardwareState"] == "REMOVED_FROM_CANDIDATE":
        return "unsupported", "row removed by user decision (automatic DOA canceled); artifacts preserved read-only"
    if row["hardwareState"] == "PL_MICROPROGRAM_NATIVE_VERIFIED":
        return "experimental", "PL microprogram native values validated with independent references; whole-service RTL/system timing and board NOT TESTED"
    if row["hardwareState"] == "CONNECTED_EVENT_CAPTURE_CANDIDATE":
        return "not_ready", "event capture RTL pieces routed; full PCM/event/host-save composition and real board NOT TESTED"
    if row["hardwareState"] == "CONNECTED_PHYSICAL_CANDIDATE":
        return "not_ready", "physical capture/system acceptance NOT TESTED; cannot claim live measurement"
    return "not_ready", "no board acceptance evidence for this row"


def main() -> int:
    data = CSV.read_bytes()
    rows = list(csv.DictReader(data.decode("utf-8-sig").splitlines()))
    group_of = {fp: g for g, fps in GROUPS.items() for fp in fps}
    features = []
    counts = {"available": 0, "experimental": 0, "not_ready": 0, "unsupported": 0}
    for row in rows:
        fid = row["id"].strip()
        if fid not in group_of:
            raise SystemExit("feature id missing from group map: " + fid)
        if fid not in META:
            raise SystemExit("feature id missing from metadata map: " + fid)
        status, reason = derive_status(row)
        units, inputs, update = META[fid]
        counts[status] += 1
        features.append({
            "featureId": fid,
            "displayName": row["name"].strip(),
            "groupId": group_of[fid],
            "tier": row["tier"].strip(),
            "status": status,
            "statusReason": reason,
            "qualityNote": QUALITY[status],
            "units": units,
            "inputRequirement": inputs,
            "updateMethod": update,
            "experimental": status == "experimental",
            "requiresLiveDevice": row["hardwareState"] != "REMOVED_FROM_CANDIDATE",
            "livePlanned": row["hardwareState"] != "REMOVED_FROM_CANDIDATE",
            "evidence": {
                "sourceType": "FUNCTION_EXECUTION_MAP.csv",
                "softwareSourceLocated": row["softwareSourceLocated"] == "True",
                "softwareReference": row["softwareReference"].strip(),
                "hardwareState": row["hardwareState"].strip(),
                "provider": row["provider"].strip(),
                "completeFunctionHardwareAccepted": row["completeFunctionHardwareAccepted"] == "True",
                "wholeBoardAccepted": row["wholeBoardAccepted"] == "True",
                "integrationStatus": row["integrationStatus"].strip(),
                "missing": row["missing"].strip(),
                "sharedDependency": row["sharedDependency"].strip(),
            },
        })
    if len(features) != 52:
        raise SystemExit(f"expected 52 feature rows from the CSV, got {len(features)}")
    catalog = {
        "catalogVersion": 1,
        "generatedAt": FROZEN_AT,
        "source": "deployment/work_platform_20261013/phase15_analysis_only_20261023/integration/FUNCTION_EXECUTION_MAP.csv",
        "sourceSha256": hashlib.sha256(data).hexdigest(),
        "statusPolicy": [
            "available requires actual backend/firmware support AND acceptance evidence; none of the 52 rows qualifies today",
            "experimental = PL microprogram-native values validated, whole-service RTL/board not accepted",
            "not_ready = live path needs physical capture or real board link not yet accepted",
            "unsupported = removed by user (automatic DOA / XYZ / auto source count / trackId)",
        ],
        "summary": {"total": len(features), **counts,
                    "liveAvailableNow": False,
                    "note": "Counts are evidence-derived, not product promises; 0 available is the honest state before board acceptance."},
        "groups": {g: [f["featureId"] for f in features if f["groupId"] == g] for g in GROUPS},
        "features": features,
    }
    rendered = json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(rendered, encoding="utf-8")
    catalog["catalogSha256"] = hashlib.sha256(rendered.encode("utf-8")).hexdigest()

    lines = [
        "# 功能目录（真实状态，52 行逐行继承 FUNCTION_EXECUTION_MAP.csv）",
        "",
        f"生成时间：{FROZEN_AT}；来源 CSV sha256：{catalog['sourceSha256']}",
        f"状态统计：available={counts['available']}，experimental={counts['experimental']}，"
        f"not_ready={counts['not_ready']}，unsupported={counts['unsupported']}（共 {len(features)} 行）",
        "",
        "> available 必须同时具备真实后端/固件支持与验收证据。当前没有任何一行满足，",
        "> 因此 available=0 是**如实状态**，不是缺失；不得为了打开界面而改成 available。",
        "",
        "| featureId | 名称 | 组 | Tier | 状态 | 单位 | 输入 | 更新方式 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for f in features:
        lines.append(f"| {f['featureId']} | {f['displayName']} | {f['groupId']} | {f['tier']} | "
                     f"{f['status']} | {f['units']} | {f['inputRequirement']} | {f['updateMethod']} |")
    lines += ["", "## 状态判定规则", ""]
    lines += [f"- {p}" for p in catalog["statusPolicy"]]
    lines += ["", "详细证据（缺失项/共享依赖/整机验收）见 FEATURE_CATALOG.json 的 features[].evidence。"]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("FEATURE_CATALOG_GENERATED", len(features), "rows", counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
