
"""Generate ui/config/feature_view_spec.json for the echo-features-1 PC wiring.

Single source of truth for the 51-feature PC presentation/decoder/parameter
metadata. Inputs are the authoritative candidate-device documents:

  deployment/echo_feature_closure_20261025/51_FEATURE_CALLS.csv
  deployment/echo_feature_closure_20261025/registry/INTERFACE_REGISTRY.json

plus the curated UI mapping/decode tables below (page, icon, short name,
chart kind, wire layout recipe).  The generator never invents acoustic
algorithms; it only records protocol/display metadata.  Run:

    python ui/tools/build_feature_view_spec.py
    python ui/tools/build_feature_view_spec.py --check
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = APP_ROOT.parents[1]
CLOSURE = REPO_ROOT / "deployment" / "echo_feature_closure_20261025"
CSV_PATH = CLOSURE / "51_FEATURE_CALLS.csv"
IREG_PATH = CLOSURE / "registry" / "INTERFACE_REGISTRY.json"
OUT_PATH = APP_ROOT / "ui" / "config" / "feature_view_spec.json"

SAMPLE_RATE_HZ = 49162010 / 1024.0          # fixed device analysis rate (48 009.775390625)
FFT_SIZE = 2048
SPEC_VERSION = "echo-features-1"

# --------------------------------------------------------------------------
# curated mapping: unique primary entry per featureId (task section 4)
# chart kinds are the PC display recipes implemented by ui/features/decoder.py
# --------------------------------------------------------------------------
VIEW = {
    # 采集、电平与输入质量 -> time
    "io_pcm":            dict(page="time", group="acquisition", shortZh="PCM采集", shortEn="PCM Capture", nameEn="Six-channel WAV/PCM", icon="audio-waveform", chart="waveform"),
    "levels_core":       dict(page="time", group="acquisition", shortZh="电平核心", shortEn="Levels", nameEn="RMS/Peak/dBFS/Crest/Clipping", icon="activity", chart="level-bars"),
    "levels_extended":   dict(page="time", group="acquisition", shortZh="扩展电平", shortEn="Ext. Levels", nameEn="Peak-to-peak and extended levels", icon="activity", chart="level-bars"),
    "data_continuity":   dict(page="time", group="acquisition", shortZh="采样连续性", shortEn="Continuity", nameEn="Sample continuity and input anomalies", icon="link-2", chart="scalars"),
    "signal_quality":    dict(page="time", group="acquisition", shortZh="输入质量", shortEn="Input Quality", nameEn="Input validity and freshness", icon="shield-check", chart="scalars"),

    # 频谱及比较 -> spectrum
    "fft":               dict(page="spectrum", group="analysis", shortZh="FFT幅度谱", shortEn="FFT", nameEn="FFT amplitude / power spectrum", icon="chart-line", chart="spectrum"),
    "psd":               dict(page="spectrum", group="analysis", shortZh="Welch PSD", shortEn="PSD", nameEn="Welch power spectral density", icon="chart-line", chart="spectrum"),
    "stft":              dict(page="spectrum", group="analysis", shortZh="STFT时频", shortEn="STFT", nameEn="STFT spectrogram / waterfall", icon="layers", chart="stft"),
    "spectrum_average":  dict(page="spectrum", group="analysis", shortZh="谱平均", shortEn="Avg Spectrum", nameEn="Spectrum power average (EMA)", icon="chart-line", chart="spectrum"),
    "peak_hold":         dict(page="spectrum", group="analysis", shortZh="峰值保持", shortEn="Peak Hold", nameEn="Spectrum peak hold", icon="chart-line", chart="spectrum"),
    "smoothing":         dict(page="spectrum", group="analysis", shortZh="谱平滑", shortEn="Smoothing", nameEn="PL spectrum smoothing", icon="chart-line", chart="spectrum"),
    "zoom_fft":          dict(page="spectrum", group="analysis", shortZh="Zoom FFT", shortEn="Zoom FFT", nameEn="Heterodyne FIR zoom FFT", icon="zoom-in", chart="zoom-spectrum"),
    "spectrum_freeze":   dict(page="spectrum", group="compare", shortZh="频谱冻结A/B", shortEn="Freeze A/B", nameEn="Spectrum freeze and A/B delta", icon="git-compare", chart="ab-spectrum"),
    "relative_limit":    dict(page="spectrum", group="compare", shortZh="相对限值", shortEn="Rel. Limit", nameEn="Relative limit detection vs reference", icon="octagon-alert", chart="ab-spectrum"),

    # 频带、计权与统计 -> bands
    "octave":            dict(page="bands", group="bands", shortZh="1/1倍频程", shortEn="1/1 Octave", nameEn="1/1 octave band energy", icon="chart-bar", chart="bands"),
    "third_octave":      dict(page="bands", group="bands", shortZh="1/3倍频程", shortEn="1/3 Octave", nameEn="1/3 octave band energy", icon="chart-bar", chart="bands"),
    "frequency_time_weighting": dict(page="bands", group="stats", shortZh="频率/时间计权", shortEn="Weighting", nameEn="A/C/Z weighting and Z FAST/SLOW/LeqFS", icon="sliders-horizontal", chart="weighting"),
    "level_statistics":  dict(page="bands", group="stats", shortZh="电平统计", shortEn="Level Stats", nameEn="LeqFS and L10/L50/L90 statistics", icon="chart-column", chart="statistics"),
    "noise_rating":      dict(page="bands", group="stats", shortZh="NC/NR估计", shortEn="NC/NR", nameEn="NC/NR estimate with explicit reference", icon="chart-bar", chart="noise-rating"),

    # 周期、调制及频率特征 -> periodic (advanced tools sub-page)
    "frequency_tracking": dict(page="periodic", group="shape", shortZh="主峰跟踪", shortEn="Peak Track", nameEn="Dominant peak frequency tracking", icon="activity", chart="scalars"),
    "frequency_drift":   dict(page="periodic", group="shape", shortZh="频率漂移", shortEn="Drift", nameEn="Peak frequency drift", icon="activity", chart="scalars"),
    "centroid":          dict(page="periodic", group="shape", shortZh="谱质心", shortEn="Centroid", nameEn="Spectral centroid", icon="crosshair", chart="scalars"),
    "flatness":          dict(page="periodic", group="shape", shortZh="谱平坦度", shortEn="Flatness", nameEn="Spectral flatness", icon="chart-line", chart="scalars"),
    "spectral_kurtosis": dict(page="periodic", group="shape", shortZh="谱峭度", shortEn="Kurtosis", nameEn="Cumulative spectral kurtosis", icon="chart-line", chart="spectrum"),
    "cepstrum":          dict(page="periodic", group="cepstrum", shortZh="倒谱", shortEn="Cepstrum", nameEn="Real cepstrum", icon="wave-sine", chart="lag-series"),
    "fundamental":       dict(page="periodic", group="cepstrum", shortZh="基频", shortEn="Fundamental", nameEn="Autocorrelation fundamental estimate", icon="wave-sine", chart="lag-series"),
    "harmonic_ratio":    dict(page="periodic", group="cepstrum", shortZh="谐波/THD", shortEn="Harmonics", nameEn="Harmonic band powers and THD", icon="chart-column", chart="harmonic-bars"),
    "sidebands":         dict(page="periodic", group="cepstrum", shortZh="边带", shortEn="Sidebands", nameEn="Carrier sidebands", icon="chart-column", chart="harmonic-bars"),
    "envelope_hilbert":  dict(page="periodic", group="envelope", shortZh="Hilbert包络", shortEn="Envelope", nameEn="Hilbert analytic envelope", icon="audio-lines", chart="waveform"),
    "envelope_spectrum": dict(page="periodic", group="envelope", shortZh="包络谱", shortEn="Env. Spectrum", nameEn="Envelope spectrum", icon="chart-line", chart="spectrum"),
    "modulation_spectrum": dict(page="periodic", group="envelope", shortZh="调制谱", shortEn="Mod Spectrum", nameEn="Modulation spectrum", icon="chart-line", chart="spectrum"),

    # 多通道与相关 -> multichannel
    "csd":               dict(page="multichannel", group="pair", shortZh="CSD/CSM", shortEn="CSD", nameEn="Cross spectral density / matrix", icon="git-compare", chart="pair-spectra"),
    "coherence_phase":   dict(page="multichannel", group="pair", shortZh="相干与相位", shortEn="Coherence", nameEn="Coherence and phase difference", icon="git-compare", chart="coherence-phase"),
    "autocorrelation":   dict(page="multichannel", group="correlation", shortZh="自相关", shortEn="Autocorr", nameEn="Auto-correlation", icon="wave-sine", chart="lag-series"),
    "cross_correlation": dict(page="multichannel", group="correlation", shortZh="互相关", shortEn="Cross-corr", nameEn="Cross-correlation", icon="git-compare", chart="lag-series"),
    "gcc_phat":          dict(page="multichannel", group="correlation", shortZh="GCC-PHAT", shortEn="GCC-PHAT", nameEn="GCC-PHAT delay observation", icon="crosshair", chart="lag-series"),

    # 手动空间分析 -> directional

    # 变化与事件监测 -> events
    "energy_change":     dict(page="events", group="change", shortZh="能量变化", shortEn="Energy Change", nameEn="Short-time energy change", icon="activity", chart="scalars"),
    "band_tracking":     dict(page="events", group="change", shortZh="频带跟踪", shortEn="Band Track", nameEn="Selected band energy tracking", icon="chart-column", chart="scalars"),
    "spectral_flux":     dict(page="events", group="change", shortZh="谱通量", shortEn="Spectral Flux", nameEn="Spectral structure change", icon="activity", chart="spectrum"),
    "event_trigger":     dict(page="events", group="monitor", shortZh="事件监测", shortEn="Event Monitor", nameEn="Sound change event monitoring", icon="bell-ring", chart="events"),

    # 房间及相对测量 -> room
    "room_decay":        dict(page="room", group="decay", shortZh="房间衰减", shortEn="Room Decay", nameEn="EDT/T20/T30 room decay", icon="activity", chart="room-decay"),
    "room_clarity":      dict(page="room", group="decay", shortZh="清晰度", shortEn="Clarity", nameEn="C50/C80/D50 clarity", icon="chart-line", chart="room-clarity"),
    "spectral_decay":    dict(page="room", group="decay", shortZh="分频衰减", shortEn="Band Decay", nameEn="Filtered per-band decay", icon="layers", chart="spectral-decay"),
    "relative_insulation": dict(page="room", group="relative", shortZh="相对隔声", shortEn="Rel. Insulation", nameEn="Relative insulation difference", icon="building", chart="insulation-bars"),
    "stipa_experimental": dict(page="room", group="relative", shortZh="实验STIPA", shortEn="STIPA (exp.)", nameEn="Experimental STIPA (not certified)", icon="chart-spline", chart="stipa"),
}

# page -> ordered groups.  The prompt's EIGHT logical categories are the
# authoritative grouping shown by the in-page feature entry row; each page hosts
# exactly one category group (unique primary entry per featureId).  Sub-groups
# are deliberately NOT shown again — the earlier finer split was rejected.
PAGE_GROUPS = {
    "time": [("acquisition", "采集、电平与输入质量", "Acquisition, levels & input quality")],
    "spectrum": [("spectrum_compare", "频谱及比较", "Spectrum & comparison")],
    "bands": [("bands_stats", "频带、计权与统计", "Bands, weighting & statistics")],
    "periodic": [("periodic", "周期、调制及频率特征", "Periodic, modulation & frequency features")],
    "multichannel": [("multichannel", "多通道与相关", "Multichannel & correlation")],
    "events": [("events", "变化与事件监测", "Change & event monitoring")],
    "room": [("room", "房间及相对测量", "Room & relative measurement")],
}
CATEGORY_PAGE_HINT_EN = {
    "time": "Overview / Time / Device records: six-channel waveform, levels, continuity and freshness",
    "spectrum": "Spectrum / time-frequency: lines, heatmap, 3D waterfall, freeze A/B and limit overlay",
    "bands": "Bands / noise: compact gradient bars, statistics trends and reference curves",
    "periodic": "Spectrum helpers / advanced sub-group: frequency trends, cepstrum, harmonics, envelope and modulation spectra",
    "multichannel": "Multichannel: CSD, coherence, phase and correlation/delay plots",
    "events": "Events/monitoring: trends, event timeline, device event list and capture records",
    "room": "Advanced tools / room sub-group: decay, clarity, band decay, relative insulation, experimental STIPA",
}
CATEGORY_PAGE_HINT = {
    "time": "现有总览/时域/设备记录：六通道波形、电平、连续性和新鲜度",
    "spectrum": "现有频谱/时频：折线、热力图、3D瀑布、冻结A/B和限值叠加",
    "bands": "现有频带/噪声：紧凑渐变柱图、统计趋势和参考曲线",
    "periodic": "频谱辅助工具/高级工具对应子组：频率趋势、倒谱、谐波、包络与调制谱",
    "multichannel": "现有多通道页：CSD、相干性、相位及相关/时延图",
    "events": "现有事件/监测：趋势、事件时间轴、设备事件列表与采集记录",
    "room": "现有高级工具/房间子组：衰减、清晰度、分频衰减、相对隔声、实验STIPA",
}
PAGE_TITLES = {
    "time": ("时域与电平", "Time & Levels"),
    "spectrum": ("频谱与时频", "Spectrum & Time-Frequency"),
    "bands": ("频带与噪声", "Bands & Noise"),
    "periodic": ("周期与调制", "Periodic & Modulation"),
    "multichannel": ("多通道关联", "Multichannel Correlation"),
    "events": ("异常事件", "Events"),
    "room": ("房间指标", "Room Metrics"),
}

# --------------------------------------------------------------------------
# decode recipes: pure display layout metadata (no DSP).  "pending-layout"
# means the wire words need a per-feature field map confirmed from the device
# producer source before values may be shown; such features display raw words
# plus an explicit reason until resolved (never guessed floats).
# --------------------------------------------------------------------------
SPECTRUM = dict(recipe="series", offset=0, count=1025, firstBin=0, fftSize=FFT_SIZE,
                sampleRateHz=SAMPLE_RATE_HZ, xAxis="frequencyHz", encoding="float32")
LAG = dict(recipe="lag-series", offset=0, count=2048, lagBase=1024,
           sampleRateHz=SAMPLE_RATE_HZ, xAxis="lagSeconds", encoding="float32")
DECODE = {
    "io_pcm": dict(recipe="waveform", encoding="pcm24", fullWords="samples*channels",
                   displayDecimation="peak-envelope", maxDisplayPoints=4096,
                   units="signed24 counts"),
    "levels_core": dict(recipe="channel-fields", channels=6, stride=8,
                        fields=["rms_FS", "peak_FS", "peakToPeak_FS", "mean_FS",
                                "rms_dBFS", "crest", "clipCount", "nonzeroValid"]),
    "levels_extended": dict(recipe="channel-fields", channels=6, stride=8,
                            fields=["rms_FS", "peak_FS", "peakToPeak_FS", "mean_FS",
                                    "rms_dBFS", "crest", "clipCount", "nonzeroValid"]),
    "data_continuity": dict(recipe="snapshot", words=32, dataFaultMask=1023,
                            fields=[{"key": "source_frame_id", "word": 2, "type": "uint32"},
                                    {"key": "config", "word": 3, "type": "uint32"},
                                    {"key": "session", "word": 4, "type": "uint32"},
                                    {"key": "slot", "word": 5, "type": "uint32"},
                                    {"key": "sample_index", "words": [8, 9], "type": "u64dec"},
                                    {"key": "faults", "word": 10, "type": "uint32"},
                                    {"key": "missed", "word": 12, "type": "uint32"},
                                    {"key": "dropped", "word": 13, "type": "uint32"},
                                    {"key": "lost_events", "word": 29, "type": "uint32"},
                                    {"key": "handoff_drops", "word": 30, "type": "uint32"},
                                    {"key": "sample_rate_hz", "word": 31, "type": "float32"}],
                            derived=[{"key": "continuity_ok", "expr": "faults & 1023 == 0", "type": "bool"}]),
    "signal_quality": dict(recipe="snapshot", words=32, dataFaultMask=1023,
                           fields=[{"key": "source_frame_id", "word": 2, "type": "uint32"},
                                   {"key": "config", "word": 3, "type": "uint32"},
                                   {"key": "session", "word": 4, "type": "uint32"},
                                   {"key": "slot", "word": 5, "type": "uint32"},
                                   {"key": "sample_index", "words": [8, 9], "type": "u64dec"},
                                   {"key": "faults", "word": 10, "type": "uint32"},
                                   {"key": "missed", "word": 12, "type": "uint32"},
                                   {"key": "dropped", "word": 13, "type": "uint32"},
                                   {"key": "sample_rate_hz", "word": 31, "type": "float32"}],
                           derived=[{"key": "capture_valid", "expr": "faults & 1023 == 0", "type": "bool"},
                                    {"key": "fresh", "expr": "frame != previousFrame", "type": "bool",
                                     "note": "display comparison of successive frames"}],
                           requiresZeroWords=False),
    "fft": dict(SPECTRUM, field="bin_power_FS2",
                wireNote="P0 snapshot triplet lane 2 (bin_power_FS2) per gateway P0 capture contract"),
    "psd": dict(recipe="count-then-series", countIndex=0, offset=1, count=1025,
                firstBin=0, fftSize=FFT_SIZE, sampleRateHz=SAMPLE_RATE_HZ,
                xAxis="frequencyHz", encoding="float32",
                field="mean_PSD_FS2_per_Hz", countType="uint32"),
    "stft": dict(recipe="stft", bins=1025, fftSize=FFT_SIZE,
                 sampleRateHzFrom="schema.axes.sampleRateHz",
                 frameIndicesFrom="schema.axes.frameFirstSampleIndices",
                 framesParam="frames", order="frame-major", field="PSD"),
    "spectrum_average": dict(SPECTRUM, field="EMA_bin_power_FS2"),
    "peak_hold": dict(SPECTRUM, field="max_bin_power_FS2"),
    "smoothing": dict(SPECTRUM, field="smoothed_bin_power_FS2"),
    "zoom_fft": dict(recipe="zoom", pairs=2048, wordCount=4096,
                     amplitudeWordOffset=0, psdWordOffset=1, stride=2,
                     frequencyAxis="unshifted center + fftfreq(2048, decimation/fs); "
                                   "display fftshift only",
                     passbandFraction=0.30, layout="two-sided complex amplitude / PSD pairs"),
    "spectrum_freeze": dict(recipe="ab-compare", count=1025,
                            deltaOffset=0, middleOffset=1025, flagsOffset=2050,
                            fftSize=FFT_SIZE, sampleRateHz=SAMPLE_RATE_HZ,
                            encoding="float32"),
    "relative_limit": dict(recipe="ab-compare", count=1025,
                           deltaOffset=0, middleOffset=1025, flagsOffset=2050,
                           fftSize=FFT_SIZE, sampleRateHz=SAMPLE_RATE_HZ,
                           encoding="float32"),
    "octave": dict(recipe="bands", centersFrom="schema.axes.bandHz", encoding="float32",
                   xAxis="centerFrequencyHz"),
    "third_octave": dict(recipe="bands", centersFrom="schema.axes.bandHz", encoding="float32",
                         xAxis="centerFrequencyHz"),
    "frequency_time_weighting": dict(recipe="weighting", words=1028,
                                     spectralFields=["weighted_power_FS2", "weighted_dBFS", "valid"],
                                     recordedFields=["FAST_power_FS2", "FAST_dBFS",
                                                     "SLOW_power_FS2", "SLOW_dBFS",
                                                     "LeqFS", "samples_uint32", "valid",
                                                     "FAST_settled", "SLOW_settled"],
                                     recordedWords=48032, recordedWorkspace=True,
                                     recordedInputOffset=32,
                                     layoutSource="noise_services.weighted_level 与 "
                                                  "recorded_time_response；host APL "
                                                  "spectral_A_relative_level + "
                                                  "captured_exact_FAST_SLOW_LeqFS"),
    "level_statistics": dict(recipe="level-statistics", words=40, observations=16,
                             fields=["L10DBFS", "L50DBFS", "L90DBFS", "LeqFS", "valid", "count"],
                             layoutSource="noise_services.level_statistics；"
                                          "L10/L50/L90/Leq@0-3, valid@4, count@5, "
                                          "rolling history@8:24（新→旧）, scratch@24:40"),

    "noise_rating": dict(recipe="noise-rating",
                         layoutSource="noise_services.noise_curve；rating/valid/estimated@0-2, "
                                      "octave input levels@32, 曲线表@64, 评分列表在曲线表之后"
                                      "（NR@973 / NC@160）；0偏移只是名义参考，不是声学校准",
                         note="NC/NR 参考族曲线仅在生产者提供表格时绘制；PC 不生成标准曲线"),
    "frequency_tracking": dict(recipe="scalars", fields=["centroid_hz", "flatness",
                                                         "peak_bin_power", "peak_hz"]),
    "frequency_drift": dict(recipe="scalars", fields=["peak_hz", "delta_hz",
                                                      "drift_hz_per_second", "drift_valid",
                                                      "history_hz", "initialized", "frame_uint"],
                            uint32Fields=["frame_uint"]),
    "centroid": dict(recipe="scalars", fields=["centroid_hz", "flatness",
                                               "peak_bin_power", "peak_hz"]),
    "flatness": dict(recipe="scalars", fields=["centroid_hz", "flatness",
                                               "peak_bin_power", "peak_hz"]),
    "spectral_kurtosis": dict(recipe="kurtosis", words=4101, bins=1025, firstBin=0,
                              fftSize=FFT_SIZE, sampleRateHz=SAMPLE_RATE_HZ,
                              fieldCount=4, validityTail=1,
                              layoutSource="extra_spectral.spectral_kurtosis；M@0，"
                                           "每频点 sum/sum²/K/valid 交错 @1+4i..4+4i"),
    "cepstrum": dict(LAG, count=2048, xAxis="quefrencySeconds", field="real_cepstrum_log_FS"),
    "fundamental": dict(recipe="lag-series+tail", offset=0, count=2048, lagBase=1024,
                        sampleRateHz=SAMPLE_RATE_HZ, xAxis="lagSeconds",
                        tailFields=["fundamental_hz", "period_strength", "valid"],
                        tailOffset=2048),
    "harmonic_ratio": dict(recipe="harmonic-bars", harmonicCount=8, thdIndex=8, validIndex=9,
                           binRangesFrom="actualProducerLayout.bin_ranges",
                           f0From="actualProducerLayout.f0_hz"),
    "sidebands": dict(recipe="field-bars", fields=["lower_FS2", "carrier_FS2", "upper_FS2",
                                                    "lower_carrier_ratio", "upper_carrier_ratio",
                                                    "valid"]),
    "envelope_hilbert": dict(recipe="waveform", encoding="float32", count=2048,
                             countFrom="words", sampleRateHz=SAMPLE_RATE_HZ,
                             xAxis="timeSeconds", displayDecimation="peak-envelope",
                             maxDisplayPoints=4096),
    "envelope_spectrum": dict(SPECTRUM, field="envelope_FFT_magnitude"),
    "modulation_spectrum": dict(SPECTRUM, field="envelope_FFT_magnitude"),
    "csd": dict(recipe="pair-bins", countIndex=0, bins=1025, stride=11, firstBin=0,
                fftSize=FFT_SIZE, sampleRateHz=SAMPLE_RATE_HZ,
                fields=["sum_xx", "sum_yy", "sum_real", "sum_imag", "Sxx", "Syy",
                        "CSD_real", "CSD_imag", "coherence", "phase_rad", "valid"],
                conventionFrom="actualProducerLayout.convention"),
    "coherence_phase": dict(recipe="pair-bins", countIndex=0, bins=1025, stride=11, firstBin=0,
                            fftSize=FFT_SIZE, sampleRateHz=SAMPLE_RATE_HZ,
                            fields=["sum_xx", "sum_yy", "sum_real", "sum_imag", "Sxx", "Syy",
                                    "CSD_real", "CSD_imag", "coherence", "phase_rad", "valid"],
                            conventionFrom="actualProducerLayout.convention"),
    "autocorrelation": dict(LAG, field="linear_correlation_FS2_sum"),
    "cross_correlation": dict(LAG, field="linear_correlation_FS2_sum"),
    "gcc_phat": dict(LAG, field="relative_PHAT_correlation"),
    "directed_das": dict(recipe="beam-spectrum", bins=128, firstBin=1, stride=3,
                         fftSize=FFT_SIZE, sampleRateHz=SAMPLE_RATE_HZ,
                         fields=["beam_fft_real_FS", "beam_fft_imag_FS", "beam_psd_FS2_per_Hz"],
                         anglesFrom="actualProducerLayout.azimuth_deg|elevation_deg"),
    "full_das": dict(recipe="das-map", powerOffset=8192, peakOffset=10240, maxPeaks=3,
                     pointsFrom="actualProducerLayout.points", binsField="bins",
                     powerCountFrom="points", peakStride=3),
    "band_das": dict(recipe="das-map", powerOffset=8192, peakOffset=10240, maxPeaks=3,
                     pointsFrom="actualProducerLayout.points", binsField="bins",
                     powerCountFrom="points", peakStride=3),
    "spatial_grid": dict(recipe="das-map", powerOffset=8192, peakOffset=10240, maxPeaks=3,
                         pointsFrom="actualProducerLayout.points", binsField="bins",
                         powerCountFrom="points", peakStride=3),
    "spatial_peaks": dict(recipe="das-map+peaks", powerOffset=8192, peakOffset=10240,
                          maxPeaks=3, pointsFrom="actualProducerLayout.points",
                          binsField="bins", powerCountFrom="points", peakStride=3),
    "spatial_interface": dict(recipe="capability"),
    "energy_change": dict(recipe="scalars", fields=["power_FS2", "previous_power_FS2",
                                                     "delta_FS2", "delta_valid",
                                                     "history_power_FS2", "initialized"]),
    "band_tracking": dict(recipe="scalars", fields=["power_FS2", "previous_power_FS2",
                                                     "delta_FS2", "delta_valid",
                                                     "history_power_FS2", "initialized"]),
    "spectral_flux": dict(recipe="scalars+history", fields=["positive_flux",
                                                            "absolute_delta_sum", "rms_delta"],
                          historyOffset=3, historyCount=1025),
    "event_trigger": dict(recipe="events", note="continuous monitoring; records come from "
                            "event.list/get/download/ack + 48121 event files, not feature.result"),
    "room_decay": dict(recipe="room", summaryWords=32, irOffset=32, decayOffset=24032,
                       samples=24000, sampleRateHz=SAMPLE_RATE_HZ,
                       fieldMap={"energy": 0, "early50": 1, "early80": 2, "D50_percent": 3,
                                 "tail_nonstationary": 4, "C50_db": 5, "C50_valid": 6,
                                 "C80_db": 7, "C80_valid": 8,
                                 "EDT": [10, 11, 12, 13, 14, 15],
                                 "T20": [16, 17, 18, 19, 20, 21],
                                 "T30": [22, 23, 24, 25, 26, 27]}),
    "room_clarity": dict(recipe="room", summaryWords=32, irOffset=32, decayOffset=24032,
                         samples=24000, sampleRateHz=SAMPLE_RATE_HZ,
                         fieldMap={"energy": 0, "early50": 1, "early80": 2, "D50_percent": 3,
                                   "tail_nonstationary": 4, "C50_db": 5, "C50_valid": 6,
                                   "C80_db": 7, "C80_valid": 8,
                                   "EDT": [10, 11, 12, 13, 14, 15],
                                   "T20": [16, 17, 18, 19, 20, 21],
                                   "T30": [22, 23, 24, 25, 26, 27]}),
    "spectral_decay": dict(recipe="room", summaryWords=32, irOffset=32, decayOffset=24032,
                           samples=24000, sampleRateHz=SAMPLE_RATE_HZ,
                           centerHzFrom="actualProducerLayout.center_hz",
                           fractionFrom="actualProducerLayout.fraction",
                           fieldMap={"energy": 0, "early50": 1, "early80": 2, "D50_percent": 3,
                                     "tail_nonstationary": 4, "C50_db": 5, "C50_valid": 6,
                                     "C80_db": 7, "C80_valid": 8,
                                     "EDT": [10, 11, 12, 13, 14, 15],
                                     "T20": [16, 17, 18, 19, 20, 21],
                                     "T30": [22, 23, 24, 25, 26, 27]}),
    "relative_insulation": dict(recipe="insulation", words=36, inputOffset=18,
                                layoutSource="noise_services.relative_band_difference + "
                                             "gateway prepare_inputs；diff dB@0:9, valid@9:18, "
                                             "A@18:27, B@27:36（9倍频程）",
                                note="两次倍频程能量采集 A/B；仅相对 dB 差异，不标 Rw/DnT"),
    "stipa_experimental": dict(recipe="stages", fields=["experimental_index", "valid",
                                                         "certified_zero"],
                               stagesTotal=101, staged=True),
}

SPECIAL = {
    "spectrum_freeze": dict(type="reference_compare", referenceAction="reference",
                            compareAction="compare", referenceParam="referenceJobId",
                            requiresSavedReference=True,
                            note="capture/freeze reference first; compare only on matching "
                                 "channel/grid/gain/source identity"),
    "relative_limit": dict(type="reference_compare", referenceAction="reference",
                           compareAction="compare", referenceParam="referenceJobId",
                           requiresSavedReference=True,
                           note="reference must be a completed PL power capture; threshold "
                                "flags are absolute-change flags, not dB SPL limits"),
    "relative_insulation": dict(type="reference_measure", referenceAction="reference",
                                measureAction="measure", referenceParam="referenceJobId",
                                confirmParam="confirmed",
                                note="same excitation/gain/measurement chain required; "
                                     "relative difference only, never labelled Rw"),
    "stipa_experimental": dict(type="staged_stipa", referenceFeature="io_pcm",
                               referenceParams={"samples": 720000, "channels": 1, "channel": 0},
                               confirmParam="testSignalConfirmed", stagesTotal=101,
                               note="experimental, not certified STIPA; requires known active "
                                    "reference capture and all 101 stages valid"),
    "room_decay": dict(type="room_stimulus", stimulusParam="stimulus",
                       stimulusEnum=["clap", "impulse"], confirm=True,
                       note="user-declared excitation; approximate onset trim on PL, not a "
                            "certified RIR/RT60 measurement"),
    "room_clarity": dict(type="room_stimulus", stimulusParam="stimulus",
                         stimulusEnum=["clap", "impulse"], confirm=True,
                         note="user-declared excitation; approximate onset trim on PL"),
    "spectral_decay": dict(type="room_stimulus", stimulusParam="stimulus",
                           stimulusEnum=["clap", "impulse"], confirm=True,
                           note="user-declared excitation; filtered decay, not certified"),
    "noise_rating": dict(type="noise_rating",
                         requiredParams=["referenceConfirmed", "referenceOffsetDb",
                                         "calibrationSource"],
                         note="explicit nominal reference is not acoustic calibration; "
                              "show NC/NR estimate only"),
    "frequency_time_weighting": dict(type="time_weighting", weightingParam="weighting",
                                     timeResponseParam="timeResponse",
                                     note="default is A/C/Z relative frequency weighting; "
                                          "timeResponse=true is independent Z/FAST/SLOW/LeqFS, "
                                          "never combined A-weighted FAST/SLOW"),
    "event_trigger": dict(type="event_monitor",
                          note="continuous monitoring job; stop page/close and wait canceled; "
                               "events via event.list/get/download/ack"),
}

# gateway control_parameter() set: accepted for any plan without recompilation
CONTROL_PARAMS = {"frames", "channels", "referenceJobId", "stimulus", "confirmed", "action",
                  "testSignalConfirmed", "referenceOffsetDb", "calibrationSource",
                  "referenceConfirmed", "timeResponse"}
# parameters that select a precompiled variant (channel / pair / family)
VARIANT_PARAMS = {"channel", "channel_i", "channel_j", "other", "family"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_csv() -> dict[str, dict]:
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {row["featureId"]: row for row in rows}


def parse_json_field(value: str, default):
    if value is None or not str(value).strip():
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def infer_param(key: str, spec: dict, feature: str, mode: str) -> dict:
    default = spec.get("default")
    required_raw = spec.get("required", False)
    required = required_raw is True or (isinstance(required_raw, str) and bool(required_raw))
    entry = {"key": key, "default": default, "required": bool(required),
             "unit": spec.get("unit", ""), "description": spec.get("description", "")}
    if "enum" in spec:
        entry["enum"] = list(spec["enum"])
        entry["type"] = "enum"
    elif spec.get("type") == "bool" or isinstance(default, bool):
        entry["type"] = "bool"
    elif spec.get("type") == "string":
        entry["type"] = "string"
    elif isinstance(default, int):
        entry["type"] = "int"
    elif isinstance(default, float):
        entry["type"] = "float"
    elif isinstance(default, dict) or isinstance(spec.get("default"), list):
        entry["type"] = "json"
    else:
        entry["type"] = "string"
    rng = spec.get("range")
    if isinstance(rng, list) and len(rng) == 2 and all(isinstance(x, (int, float)) for x in rng):
        entry["min"], entry["max"] = rng
    return entry


def mutability(key: str, policy: dict, feature: str, mode: str, param: dict) -> tuple[str, str]:
    runtime = set(policy.get("runtimeMutableParams") or [])
    if key in runtime:
        return "runtime", ""
    if key in CONTROL_PARAMS:
        if key == "channels" and feature == "io_pcm":
            return "control", ""
        if key in ("referenceJobId", "action") and feature in (
                "spectrum_freeze", "relative_limit", "relative_insulation"):
            return "flow", "由参考/比较流程自动填写"
        return "control", ""
    if key in VARIANT_PARAMS:
        return "variant", "已预编译全部通道/通道对/族组合"
    if key in ("azimuth_deg", "elevation_deg") and feature == "directed_das":
        return "runtime", "阵列本地坐标，运行时可变"
    if key in ("samples", "channels") and feature == "io_pcm":
        return "control", ""
    if key == "frames" and feature == "stft":
        return "control", ""
    if mode == "p0" and key == "channel":
        return "control", ""
    return "compiled", "非默认值需按接口文档重新编译PL计划"


def param_form(feature: str, registry_entry: dict, csv_row: dict) -> tuple[dict, dict]:
    params = dict(registry_entry.get("params") or {})
    csv_params = parse_json_field(csv_row.get("params", ""), {}) or {}
    for key, spec in csv_params.items():
        if key not in params and isinstance(spec, dict):
            params[key] = spec
    # documented runtime inputs that are not plan params on older registries
    if feature == "noise_rating":
        params.setdefault("referenceConfirmed", {"default": None, "required": True,
                                                 "type": "bool", "runtimeInput": True})
        params.setdefault("referenceOffsetDb", {"default": None, "required": True,
                                                "type": "float", "unit": "dB",
                                                "runtimeInput": True})
        params.setdefault("calibrationSource", {"default": None, "required": True,
                                                "type": "string", "runtimeInput": True})
    if feature == "stipa_experimental":
        params.setdefault("referenceJobId", {"default": None, "required": True,
                                             "type": "string", "runtimeInput": True})
        params.setdefault("testSignalConfirmed", {"default": False, "required": True,
                                                  "type": "bool", "runtimeInput": True})
    if feature == "spectrum_freeze" or feature == "relative_limit":
        params.setdefault("action", {"default": "compare", "enum": ["reference", "compare"]})
        params.setdefault("referenceJobId", {"default": None, "type": "string"})
    if feature == "relative_insulation":
        params.setdefault("action", {"default": "measure", "enum": ["reference", "measure"]})
        params.setdefault("referenceJobId", {"default": None, "type": "string"})
        params.setdefault("confirmed", {"default": False, "type": "bool"})
    policy = dict(registry_entry.get("parameterPolicy") or csv_row.get("parameterPolicy") and
                  parse_json_field(csv_row["parameterPolicy"], {}) or {})
    mode = str(registry_entry.get("mode") or csv_row.get("mode") or "")
    form, defaults = [], {}
    for key in params:
        spec = params[key]
        entry = infer_param(key, spec if isinstance(spec, dict) else {}, feature, mode)
        kind, reason = mutability(key, policy, feature, mode, entry)
        entry["mutability"] = kind
        entry["disabledReason"] = reason
        entry["labelZh"], entry["labelEn"] = PARAM_LABELS.get(key, (key, key))
        form.append(entry)
        if entry["default"] is not None and kind in ("runtime", "control", "variant"):
            defaults[key] = entry["default"]
    # required special inputs that are not in paramSpec must still be editable
    required_extra = {
        "noise_rating": ["referenceConfirmed", "referenceOffsetDb", "calibrationSource"],
        "stipa_experimental": ["referenceJobId", "testSignalConfirmed"],
        "room_decay": ["stimulus"], "room_clarity": ["stimulus"], "spectral_decay": ["stimulus"],
    }.get(feature, [])
    for key in required_extra:
        if not any(item["key"] == key for item in form):
            form.append({"key": key, "type": "string", "default": None, "required": True,
                         "unit": "", "description": "", "mutability": "runtime",
                         "disabledReason": "", "labelZh": key, "labelEn": key})
    return {"fields": form, "startDefaults": defaults}, params


PARAM_LABELS = {
    "channel": ("通道", "Channel"), "channels": ("通道数", "Channels"),
    "samples": ("采样点数", "Samples"), "frames": ("帧数", "Frames"),
    "count": ("频点数", "Bins"), "first": ("首频点", "First bin"),
    "channel_i": ("参考通道", "Channel i"), "channel_j": ("对比通道", "Channel j"),
    "other": ("对比通道", "Other channel"), "action": ("动作", "Action"),
    "referenceJobId": ("参考任务", "Reference job"), "stimulus": ("激励方式", "Stimulus"),
    "confirmed": ("测量链确认", "Chain confirmed"),
    "testSignalConfirmed": ("测试信号确认", "Test signal confirmed"),
    "referenceConfirmed": ("参考确认", "Reference confirmed"),
    "referenceOffsetDb": ("参考偏移", "Reference offset"),
    "calibrationSource": ("校准来源", "Calibration source"),
    "timeResponse": ("时间计权响应", "Time response"),
    "weighting": ("频率计权", "Weighting"),
    "sample_rate": ("采样率", "Sample rate"), "fs": ("采样率", "Sample rate"),
    "azimuth_deg": ("方位角", "Azimuth"), "elevation_deg": ("俯仰角", "Elevation"),
    "f0": ("基频", "f0"), "orders": ("阶次数", "Orders"),
    "carrier": ("载频", "Carrier"), "spacing": ("边带间隔", "Spacing"),
    "half_width": ("半带宽", "Half width"), "low": ("低截止", "Low"),
    "high": ("高截止", "High"), "floor": ("下限", "Floor"),
    "center_hz": ("中心频率", "Center"), "decimation": ("抽取倍数", "Decimation"),
    "taps": ("滤波阶数", "Taps"), "points": ("网格点", "Grid points"),
    "sound_speed": ("声速", "Sound speed"), "max_peaks": ("最大峰数", "Max peaks"),
    "separation_deg": ("峰间隔", "Separation"), "family": ("族", "Family"),
    "input_unit": ("输入单位", "Input unit"), "alpha": ("平滑系数", "Alpha"),
    "window_energy": ("窗能量", "Window energy"), "contiguous": ("连续采集", "Contiguous"),
}


def build() -> dict:
    csv_rows = load_csv()
    registry = load_json(IREG_PATH)
    reg_features = {item["featureId"]: item for item in registry["features"]}
    if set(csv_rows) != set(VIEW) or set(reg_features) != set(VIEW):
        raise SystemExit("feature sets differ: csv=%d registry=%d view=%d" % (
            len(csv_rows), len(reg_features), len(VIEW)))
    features: dict[str, dict] = {}
    pages: dict[str, dict] = {}
    for page, groups in PAGE_GROUPS.items():
        label_zh, label_en = PAGE_TITLES[page]
        pages[page] = {"labelZh": label_zh, "labelEn": label_en, "groups": [],
                       "categoryHintZh": CATEGORY_PAGE_HINT.get(page, ""),
                       "categoryHintEn": CATEGORY_PAGE_HINT_EN.get(page, "")}
        for group_id, group_zh, group_en in groups:
            pages[page]["groups"].append({"id": group_id, "labelZh": group_zh,
                                          "labelEn": group_en, "features": []})
    for feature_id, view in VIEW.items():
        row = csv_rows[feature_id]
        reg = reg_features[feature_id]
        form, params = param_form(feature_id, reg, row)
        policy = reg.get("parameterPolicy") or parse_json_field(row.get("parameterPolicy", ""), {})
        schema = reg.get("schema") or parse_json_field(row.get("resultSchema", ""), {})
        output = reg.get("output") or parse_json_field(row.get("plOutput", ""), {})
        decode = DECODE.get(feature_id)
        if decode is None:
            raise SystemExit("missing decode recipe: " + feature_id)
        decode = dict(decode)
        decode.setdefault("encoding", "float32")
        units = str(schema.get("units") or _schema_field(row.get("resultSchema", ""), "units") or "")
        validity = str(schema.get("validity") or _schema_field(row.get("resultSchema", ""), "validity") or "")
        limitations = list(schema.get("limitations") or [])
        launch = _launch(feature_id, view, form, reg)
        entry = {
            "featureId": feature_id,
            "name": str((DISPLAY_NAME_OVERRIDES.get(feature_id) or {}).get("zh")
                        or reg.get("name") or row.get("name") or feature_id),
            "shortZh": view["shortZh"], "shortEn": view["shortEn"],
            "nameEn": str((DISPLAY_NAME_OVERRIDES.get(feature_id) or {}).get("en")
                          or view["nameEn"]),
            "page": view["page"], "group": view["group"], "icon": view["icon"],
            "chart": view["chart"],
            "tier": str(reg.get("tier") or row.get("tier") or ""),
            "mode": str(reg.get("mode") or row.get("mode") or ""),
            "launch": launch,
            "params": form,
            "paramSpec": params,
            "parameterPolicy": policy,
            "decode": decode,
            "specialFlow": SPECIAL.get(feature_id),
            "units": units,
            "validity": validity,
            "limitations": limitations,
            "schemaKind": str(schema.get("kind") or ""),
            "producer": str(reg.get("producer") or row.get("plProducer") or ""),
            "devicePath": {
                "softwareState": str(row.get("softwareState") or ""),
                "hardwareState": str(row.get("hardwareState") or ""),
                "implementedDevicePath": str(row.get("softwareState") or "") == "IMPLEMENTED_DEVICE_PATH",
                "hardwareAccepted": False,
                "numericVerified": False,
                "knownGap": KNOWN_DEVICE_GAPS.get(feature_id),
            },
            "runtime": {
                "featureApiVersion": SPEC_VERSION,
                "controlPort": int(row.get("controlPort") or 48120),
                "requiresFeatureApi": True,
                "exclusive": str(reg.get("mode")) in ("p2", "staged"),
                "continuous": feature_id not in {"spatial_interface", "event_trigger", "room_decay", "room_clarity", "spectral_decay", "relative_insulation", "stipa_experimental"},
                "autoStart": str(reg.get("mode")) in ("p0","p1") and feature_id != "spatial_interface",
                "producerManaged": True,
            },
            "prerequisites": _prerequisites(feature_id, reg, row),
            "display": _display(feature_id, view),
        }
        features[feature_id] = entry
        for group in pages[view["page"]]["groups"]:
            # One category group per page: every feature of that page belongs to
            # the prompt's logical category, regardless of its finer sub-topic.
            group["features"].append(feature_id)
            entry["group"] = group["id"]
    for page in pages.values():
        for group in page["groups"]:
            group["features"].sort(key=lambda fid: list(VIEW).index(fid))
    spec = {
        "version": 1,
        "interfaceVersion": SPEC_VERSION,
        "networkProtocol": {"name": "sixmic-analysis", "version": 1},
        "generatedFrom": {
            "csv": str(CSV_PATH.relative_to(REPO_ROOT)).replace("\\", "/"),
            "csvSha256": sha256(CSV_PATH),
            "registry": str(IREG_PATH.relative_to(REPO_ROOT)).replace("\\", "/"),
            "registrySha256": sha256(IREG_PATH),
        },
        "deviceDefault": {"sampleRateHz": SAMPLE_RATE_HZ, "fftSize": FFT_SIZE,
                          "channels": 6, "catalogPageSize": 8, "catalogMaxPageSize": 16,
                          "maxResultWordsPerPage": 1024, "maxJobSlots": 8},
        "pages": pages,
        "features": features,
        "notes": [
            "hardwareState=NOT_TESTED is preserved verbatim: device-path implementation never "
            "implies board or acoustic acceptance.",
            "decode recipes only describe wire layout/required display metadata; no PC DSP is "
            "performed. layoutStatus=pending-layout-resolution must show raw words plus a reason "
            "until the producer field map is confirmed from device sources.",
            "chart kinds map to QML components; tooltips/units come from this file, not hardcoded QML.",
            "feature.result is fetched over TCP 48120; no new binary message ids are invented.",
            "devicePath.knownGap records verified device-package gaps: the PC keeps the real "
            "request wiring, shows the device-side reason, and never substitutes a PC result.",
        ],
    }
    return spec


FIXED_CALIBRATION_SOURCE = "名义数字参考（用户声明，非声学校准）"

# Verified candidate-package gaps that are device-side, not PC-side.  The PC
# still wires the feature and sends the real request, but the UI must say why a
# run cannot succeed instead of pretending the button works.
DISPLAY_NAME_OVERRIDES = {
    # CSV/registry full names kept the old engineering phrasing; entries and
    # tooltips use the plainer wording below.
    "signal_quality": {"zh": "输入信号状态检查", "en": "Input signal status check"},
}

# 2026-10-26 zoom_fft registry fix: the candidate registry now carries
# acquisitionPreparationPlan.inputWords=4159 / inputWordOffset=1069056.
# Host test-feature-server verified feature.start -> completed -> 4096 words.
# The physical board is still NOT_TESTED and numericDSPVerified=false, so the
# devicePath retains hardwareState=NOT_TESTED / hardwareAccepted=false; only the
# blocking knownGap is removed.
KNOWN_DEVICE_GAPS = {}


def _launch(feature_id: str, view: dict, form: dict, reg: dict) -> dict:
    """Fixed, hidden launch preset.  The user never edits measurement parameters.

    Only documented workflow confirmations stay interactive (stimulus kind,
    measurement-chain / test-signal acknowledgement, reference A/B actions and
    derived channel pairs).  Everything else is sent exactly as generated here.
    """
    defaults = dict(form.get("startDefaults") or {})
    launches = {
        "io_pcm": {"kind": "single", "params": {"channel": 0}},
        "stft": {"kind": "single", "params": {"frames": 8, "channel": 0}},
        "zoom_fft": {"kind": "single", "params": {}},
        "directed_das": {"kind": "single", "params": {"azimuth_deg": 0.0, "elevation_deg": 0.0},
                         "note": "固定阵列本地 0°/0°；可在空间图上点选方向后自动重发（示意图交互）"},
        "spectrum_freeze": {"kind": "reference_compare", "referenceParams": {"action": "reference"},
                            "compareParams": {"action": "compare"}},
        "relative_limit": {"kind": "reference_compare", "referenceParams": {"action": "reference"},
                           "compareParams": {"action": "compare"}},
        "relative_insulation": {"kind": "reference_measure",
                                "referenceParams": {"action": "reference"},
                                "measureParams": {"action": "measure", "confirmed": True}},
        "stipa_experimental": {"kind": "staged_stipa",
                               "referenceParams": {"samples": 720000, "channels": 1,
                                                   "channel": 0},
                               "stipaParams": {"testSignalConfirmed": True},
                               "confirmation": "testSignalConfirmed"},
        "room_decay": {"kind": "room_stimulus", "confirmation": "stimulus"},
        "room_clarity": {"kind": "room_stimulus", "confirmation": "stimulus"},
        "spectral_decay": {"kind": "room_stimulus", "confirmation": "stimulus"},
        "noise_rating": {"kind": "dual_variant", "runs": [
                            {"id": "NR", "params": {"family": "NR", "channel": 0,
                                                    "referenceConfirmed": True,
                                                    "referenceOffsetDb": 0.0,
                                                    "calibrationSource": FIXED_CALIBRATION_SOURCE}},
                            {"id": "NC", "params": {"family": "NC", "channel": 0,
                                                    "referenceConfirmed": True,
                                                    "referenceOffsetDb": 0.0,
                                                    "calibrationSource": FIXED_CALIBRATION_SOURCE}}],
                         "confirmation": "referenceConfirmed",
                         "note": "显式名义数字参考，不是声学校准；仅显示NC/NR估计"},
        "frequency_time_weighting": {"kind": "dual_variant", "runs": [
                            {"id": "frequency", "params": {"weighting": "A", "timeResponse": False}},
                            {"id": "time", "params": {"timeResponse": True}}],
                         "note": "两次独立PL运行：A/C/Z相对频率计权 与 独立Z/未计权FAST/SLOW/LeqFS，"
                                 "图表分开标注，绝不合并为A计权时间响应"},
        "event_trigger": {"kind": "monitor", "params": {"channel": 0}},
    }
    if feature_id == "zoom_fft":
        preset = {"kind": "single",
                  "params": {k: v for k, v in defaults.items() if k not in ("referenceJobId",)}}
    else:
        preset = launches.get(feature_id, {"kind": "single", "params": defaults})
    if feature_id in ("full_das", "band_das", "spatial_grid", "spatial_peaks"):
        preset["params"] = {k: v for k, v in defaults.items() if k in ("channel",)}
    if feature_id in ("autocorrelation", "cross_correlation", "gcc_phat", "csd",
                      "coherence_phase"):
        if feature_id in ("csd", "coherence_phase"):
            preset["params"] = {"channel_i": 0, "channel_j": 1}
        elif feature_id in ("cross_correlation", "gcc_phat"):
            preset["params"] = {"channel": 0, "other": 1}
        else:
            preset["params"] = {"channel": 0}
    preset = dict(preset)
    preset.setdefault("note", "")
    preset["policy"] = "fixed-hidden"
    preset["userEditable"] = False
    preset["confirmation"] = preset.get("confirmation", "")
    return preset


def _schema_field(raw: str, key: str) -> str:
    parsed = parse_json_field(raw, {})
    if isinstance(parsed, dict):
        value = parsed.get(key)
        if isinstance(value, str):
            return value
    return ""


def _prerequisites(feature_id: str, reg: dict, row: dict) -> list[dict]:
    out = []
    input_doc = reg.get("input") or {}
    for item in input_doc.get("requires") or []:
        out.append({"kind": "device", "text": str(item)})
    if feature_id in ("directed_das",):
        out.append({"kind": "manual", "text": "手动指定阵列本地方位/俯仰角；不是自动DOA"})
    if feature_id in ("full_das", "band_das", "spatial_grid", "spatial_peaks"):
        out.append({"kind": "manual", "text": "手动DAS空间图与辅助峰；不是自动声源恢复/跟踪"})
    if feature_id == "stipa_experimental":
        out.append({"kind": "reference", "text": "先完成 io_pcm 720000点单通道已知参考采集"})
    if feature_id in ("spectrum_freeze", "relative_limit"):
        out.append({"kind": "reference", "text": "先 action=reference 冻结参考并保存 referenceJobId"})
    if feature_id == "relative_insulation":
        out.append({"kind": "reference", "text": "先 action=reference，再 measure 并 confirmed=true"})
    if feature_id in ("room_decay", "room_clarity", "spectral_decay"):
        out.append({"kind": "manual", "text": "用户明确选择拍手/脉冲激励并启动采集"})
    if feature_id == "noise_rating":
        out.append({"kind": "manual", "text": "显式参考确认、有限 referenceOffsetDb、非空校准来源"})
    out.append({"kind": "deviceSoftware", "text": "需要设备软件升级到 echo-features-1 (featureApi)"})
    return out


def _display(feature_id: str, view: dict) -> dict:
    chart = view["chart"]
    log_default = chart in ("spectrum", "zoom-spectrum", "coherence-phase", "pair-spectra",
                            "beam-spectrum", "ab-spectrum", "stft")
    return {"logXDefault": log_default,
            "cursorDefault": chart in ("spectrum", "zoom-spectrum", "lag-series", "stft",
                                       "room-decay", "spectral-decay", "waveform",
                                       "coherence-phase", "pair-spectra", "beam-spectrum",
                                       "bands"),
            "legendDefault": chart in ("spectrum", "pair-spectra", "coherence-phase",
                                        "ab-spectrum", "lag-series", "level-bars"),
            "exportFormats": ["png", "json-raw", "csv"],
            "channelColors": ["#B9E7ED", "#E2E649", "#C74BDA", "#72D6C9", "#93D272", "#B2C4F0"],
            "bandRamp": ["#6A5ACD", "#4E6BD6", "#3E8FC9", "#37AFAF", "#72D6C9",
                         "#A9D96C", "#E2E649"],
            }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate existing output only")
    parser.add_argument("--output", type=Path, default=OUT_PATH)
    args = parser.parse_args()
    spec = build()
    payload = json.dumps(spec, ensure_ascii=False, indent=1) + "\n"
    if args.check:
        if not args.output.is_file():
            print("MISSING", args.output)
            return 1
        current = args.output.read_text(encoding="utf-8")
        if current != payload:
            print("OUTDATED", args.output)
            return 1
        print("OK", len(spec["features"]), "features")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8")
    print(json.dumps({"output": str(args.output), "features": len(spec["features"]),
                      "pages": {page: sum(len(g["features"]) for g in data["groups"])
                                for page, data in spec["pages"].items()},
                      "decodedLayoutPending": [fid for fid, item in spec["features"].items()
                                               if item["decode"].get("layoutStatus") ==
                                               "pending-layout-resolution"],
                      "evidence": "spec generation only; no hardware/acoustic acceptance"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
