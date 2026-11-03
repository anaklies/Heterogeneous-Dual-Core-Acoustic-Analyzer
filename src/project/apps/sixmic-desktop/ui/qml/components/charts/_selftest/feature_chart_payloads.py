"""Deterministic test-fixture payloads for every feature chart kind.

Used by qml_load_check.py to load/render FeatureChart offscreen. These are
display fixtures only (sourceKind=test-fixture, never pl-live); no acoustic
computation is performed - the series are synthetic shapes for visual QA.
"""
from __future__ import annotations

import math

SAMPLE_RATE = 48000.0
BANDS = [63, 125, 250, 500, 1000, 2000, 4000, 8000]


def _log_points(start: float, stop: float, count: int, value_fn, *, log_x: bool = True):
    points = []
    for index in range(count):
        fraction = index / max(1, count - 1)
        if log_x:
            x = start * (stop / start) ** fraction
        else:
            x = start + (stop - start) * fraction
        points.append([round(x, 6), round(float(value_fn(fraction, x)), 6)])
    return points


def _spectrum(kind: str = "spectrum", *, subtitle: str = "test fixture"):
    series = [
        {"name": "CH1", "color": "#B9E7ED",
         "points": _log_points(20, 20000, 96,
                               lambda f, x: -92 + 40 * f - 14 * math.sin(f * 9) ** 2)},
        {"name": "CH2", "color": "#E2E649",
         "points": _log_points(20, 20000, 96,
                               lambda f, x: -98 + 34 * f - 10 * math.cos(f * 7) ** 2)},
    ]
    return {
        "kind": kind, "title": "FFT", "subtitle": subtitle, "chartRevision": 1,
        "xAxis": {"min": 20, "max": 20000, "scale": "log", "label": "Frequency", "unit": "Hz"},
        "yAxis": {"min": -120, "max": -20, "scale": "linear", "label": "Level", "unit": "dBFS"},
        "series": series,
        "markers": [{"x": 1000, "y": -44, "label": "peak", "kind": "peak"}],
        "referenceLines": [{"y": -60, "label": "limit", "dashed": True, "color": "#FFD166"}],
        "referenceBands": [{"y0": -70, "y1": -60, "color": "#14B8A6", "label": "target", "opacity": 0.1}],
    }


def _bands(kind: str):
    values = [-52, -46, -41, -37, -35, -39, -45, -52]
    categories = []
    for band, value in zip(BANDS, values):
        categories.append({"label": str(band), "value": value, "valid": True,
                           "centerFrequency": band})
    categories[5] = {"label": "2000", "value": None, "valid": False,
                     "centerFrequency": 2000}
    return {
        "kind": kind, "title": "Octave bands", "subtitle": "1/1 octave", "chartRevision": 2,
        "xAxis": {"min": 63, "max": 8000, "label": "Band", "unit": "Hz"},
        "yAxis": {"min": -70, "max": -20, "scale": "linear", "label": "Level", "unit": "dBFS"},
        "categories": categories,
        "limitLine": {"value": -30, "label": "limit"},
    }


def _stft():
    frames = []
    for index in range(12):
        time = round(index * 0.02, 6)
        points = []
        for band in _log_points(40, 16000, 48, lambda f, x: 0):
            frequency = band[0]
            level = (-88 + 26 * math.sin(index * 0.5 + frequency * 0.0006) ** 2
                     - 18 * math.cos(index * 0.31) ** 2)
            points.append([frequency, round(float(level), 6)])
        if index == 6:  # missing frame: must stay empty, never interpolated
            frames.append({"time": time, "points": []})
            continue
        frames.append({"time": time, "points": points})
    return {
        "kind": "stft", "title": "STFT", "subtitle": "time-frequency", "chartRevision": 3,
        "imageUrl": "",
        "xAxis": {"min": 0.0, "max": 0.22, "scale": "linear", "label": "Time", "unit": "s"},
        "yAxis": {"min": 40, "max": 16000, "scale": "log", "label": "Frequency", "unit": "Hz"},
        "colorScale": {"min": -90, "max": -40, "palette": "viridis",
                       "label": "Level", "unit": "dBFS"},
        "frames": frames,
    }


def _das():
    markers = [{"x": 35, "y": 24, "label": "P1", "kind": "peak"},
               {"x": 300, "y": 55, "label": "P2", "kind": "peak"}]
    return {
        "kind": "das-map", "title": "DAS", "subtitle": "manual direction", "chartRevision": 4,
        "imageUrl": "",
        "azimuthRange": {"min": 0, "max": 360},
        "elevationRange": {"min": 0, "max": 90},
        "colorScale": {"min": -60, "max": 0, "palette": "viridis",
                       "label": "Relative power", "unit": "dB"},
        "markers": markers,
        "caption": "relative directional power; manual direction, not automatic DOA",
    }


def _lag(kind: str):
    points = []
    for index in range(129):
        lag = (index - 64) / SAMPLE_RATE
        value = -48 + 34 * math.exp(-((index - 64) ** 2) / 90.0)
        points.append([round(lag, 9), round(value, 6)])
    return {
        "kind": kind, "title": "Cross correlation", "subtitle": "lag series", "chartRevision": 5,
        "xAxis": {"min": points[0][0], "max": points[-1][0], "scale": "linear",
                  "label": "Lag", "unit": "s"},
        "yAxis": {"min": -60, "max": 0, "scale": "linear", "label": "Level", "unit": "dB"},
        "series": [{"name": "xcorr", "color": "#B9E7ED", "points": points}],
        "markers": [{"x": 0.0, "y": -14, "label": "peak", "kind": "peak"}],
        "referenceLines": [{"y": -3, "label": "confidence"}],
    }


def _decay():
    points = [[round(index * 0.04, 6), round(-0.02 * index ** 1.6, 6)] for index in range(51)]
    return {
        "kind": "room-decay", "title": "Room decay", "subtitle": "PL fit", "chartRevision": 6,
        "xAxis": {"min": 0, "max": 2, "scale": "linear", "label": "Time", "unit": "s"},
        "yAxis": {"min": -60, "max": 0, "scale": "linear", "label": "Level", "unit": "dB"},
        "series": [{"name": "decay", "color": "#B9E7ED", "points": points}],
        "referenceBands": [{"y0": -25, "y1": -5, "color": "#E2E649",
                            "label": "T20 PL fit interval", "opacity": 0.14}],
        "markers": [{"x": 0.0, "y": 0.0, "label": "onset", "kind": "onset"}],
        "scalarRows": [
            {"label": "EDT", "value": 0.48, "unit": "s", "valid": True},
            {"label": "T20", "value": 0.51, "unit": "s", "valid": True},
            {"label": "T30", "value": None, "unit": "s", "valid": False},
            {"label": "R2", "value": 0.986, "valid": True},
        ],
    }


def _readout(kind: str, title: str, series, scalar_rows):
    return {
        "kind": kind, "title": title, "subtitle": "test fixture", "chartRevision": 7,
        "xAxis": {"min": 20, "max": 20000, "scale": "log", "label": "Band", "unit": "Hz"},
        "yAxis": {"min": -10, "max": 20, "scale": "linear", "label": "Value", "unit": "dB"},
        "series": series,
        "markers": [],
        "scalarRows": scalar_rows,
    }


def _panels(kind: str, title: str, panels, scalar_rows=None):
    payload = {
        "kind": kind, "title": title, "subtitle": "dual panel", "chartRevision": 8,
        "xAxis": {"min": 20, "max": 20000, "scale": "log", "label": "Frequency", "unit": "Hz"},
        "panels": panels,
    }
    if kind == "statistics":
        payload["xAxis"] = {"min": -60, "max": -20, "scale": "linear",
                            "label": "Level", "unit": "dBFS"}
    if scalar_rows:
        payload["scalarRows"] = scalar_rows
    return payload


def _ab():
    frequencies = [20, 40, 80, 160, 315, 630, 1250, 2500, 5000, 10000, 20000]
    a = [[f, round(-95 + 4.0 * math.log10(f), 6)] for f in frequencies]
    b = [[f, round(v[1] - 3.0 * math.sin(math.log10(f) * 2.0), 6)] for f, v in
         zip(frequencies, a)]
    delta = [[av[0], round(av[1] - bv[1], 6)] for av, bv in zip(a, b)]
    return {
        "kind": "ab-spectrum", "title": "A/B spectrum", "subtitle": "frozen reference", "chartRevision": 9,
        "xAxis": {"min": 20, "max": 20000, "scale": "log", "label": "Frequency", "unit": "Hz"},
        "yAxis": {"min": -100, "max": -40, "scale": "linear", "label": "Level", "unit": "dBFS"},
        "deltaYAxis": {"min": -8, "max": 8, "scale": "linear", "label": "Delta", "unit": "dB"},
        "series": [
            {"name": "A reference", "role": "a", "color": "#B9E7ED", "points": a},
            {"name": "B current", "role": "b", "color": "#E2E649", "points": b, "dashed": True},
            {"name": "B - A", "role": "delta", "color": "#C74BDA", "points": delta}],
        "referenceLines": [{"y": 3, "label": "threshold", "dashed": True, "color": "#FFD166"}],
        "referenceBands": [{"y0": -3, "y1": 3, "color": "#14B8A6", "label": "tolerance",
                            "opacity": 0.12}],
    }


def _waveform():
    values = []
    for index in range(1600):
        t = index / SAMPLE_RATE
        envelope = 0.25 if index < 420 else (0.85 if index < 460 else 0.35)
        values.append(round(envelope * math.sin(2 * math.pi * 440 * t), 6))
    return {
        "kind": "waveform", "title": "PCM 24-bit", "subtitle": "peak-envelope display", "chartRevision": 10,
        "sampleRate": SAMPLE_RATE, "startSampleIndex": "0",
        "channels": [
            {"name": "CH1", "color": "#B9E7ED", "values": values},
            {"name": "CH2", "color": "#E2E649",
             "values": [round(-0.6 * v + 0.02, 6) for v in values]}],
        "gaps": [{"start": 500, "end": 540}],
        "xAxis": {"label": "Time", "unit": "s"},
        "yAxis": {"label": "Amplitude", "unit": "FS"},
    }


def _events():
    events = []
    for index in range(9):
        state = ["downloaded", "pending", "failed"][index % 3]
        kind = ["info", "warn", "error"][index % 3]
        events.append({"position01": round(0.06 + index * 0.1, 3),
                       "label": "event " + str(index + 1),
                       "kind": kind, "downloadState": state,
                       "detail": "fixture event"})
    return {
        "kind": "events", "title": "Event monitor", "subtitle": "real event timeline",
        "chartRevision": 11,
        "timeAxis": {"min": 0, "max": 10, "label": "Time", "unit": "s"},
        "events": events,
        "downloadLabels": {"downloaded": "downloaded", "pending": "pending",
                           "failed": "failed"},
    }


def _noise():
    return {
        "kind": "noise-rating", "title": "NC / NR", "subtitle": "reference estimate",
        "chartRevision": 12,
        "xAxis": {"min": 63, "max": 8000, "scale": "log", "label": "Band", "unit": "Hz"},
        "yAxis": {"min": 0, "max": 80, "scale": "linear", "label": "Level", "unit": "dB"},
        "series": [{"name": "measured", "color": "#B9E7ED",
                    "points": [[63, 42], [125, 38], [250, 33], [500, 29], [1000, 26],
                               [2000, 23], [4000, 21], [8000, 20]]}],
        "referenceFamilies": [
            {"name": "NC-30", "color": "#72D6C9", "dashed": True,
             "points": [[63, 57], [125, 48], [250, 41], [500, 35], [1000, 31], [2000, 29],
                        [4000, 28], [8000, 27]]},
            {"name": "NC-40", "color": "#C74BDA", "dashed": True,
             "points": [[63, 64], [125, 56], [250, 50], [500, 45], [1000, 41], [2000, 39],
                        [4000, 38], [8000, 37]]}],
        "markers": [{"x": 500, "y": 29, "label": "NC-30", "kind": "peak"}],
        "scalarRows": [{"label": "NC", "value": 30, "unit": "", "valid": True},
                       {"label": "NR", "value": 27, "unit": "", "valid": True},
                       {"label": "reference", "value": 0, "unit": "dB", "valid": True}],
        "note": "estimate with explicit reference; not a certified NC/NR rating",
    }


def _stipa():
    return {
        "kind": "stipa", "title": "Experimental STIPA", "subtitle": "101 stages",
        "chartRevision": 13,
        "stage": {"index": 64, "total": 101, "label": "stage 64 / 101"},
        "indexValue": 0.68, "indexLabel": "STI", "indexUnit": "", "indexValid": True,
        "scalarRows": [
            {"label": "index", "value": 0.68, "valid": True},
            {"label": "arithmetic validity", "value": 1, "valid": True},
            {"label": "certified", "value": 0, "valid": True},
            {"label": "modulation", "value": 0.71, "valid": True}],
        "caption": "experimental result; certified index is always 0 for this feature",
    }


def build_payloads() -> dict:
    """One deterministic test-fixture payload per chart kind (24 kinds)."""
    return {
        "spectrum": _spectrum(),
        "zoom-spectrum": {**_spectrum("zoom-spectrum", subtitle="zoom FFT"),
                          "xAxis": {"min": 900, "max": 1100, "scale": "linear",
                                    "label": "Frequency", "unit": "Hz"}},
        "spectral-decay": {
            "kind": "spectral-decay", "title": "Spectral decay", "subtitle": "filtered bands",
            "chartRevision": 14,
            "xAxis": {"min": 0, "max": 2, "scale": "linear", "label": "Time", "unit": "s"},
            "yAxis": {"min": -60, "max": 0, "scale": "linear", "label": "Level", "unit": "dB"},
            "series": [
                {"name": "1 kHz", "color": "#B9E7ED",
                 "points": [[round(i * 0.05, 4), round(-0.015 * i ** 1.7, 4)] for i in range(41)]},
                {"name": "4 kHz", "color": "#E2E649", "dashed": True,
                 "points": [[round(i * 0.05, 4), round(-0.022 * i ** 1.5, 4)] for i in range(41)]}],
            "scalarRows": [{"label": "EDT 1 kHz", "value": 0.42, "unit": "s", "valid": True}],
        },
        "beam-spectrum": {
            "kind": "beam-spectrum", "title": "Directed beam spectrum", "subtitle": "manual 0/0",
            "chartRevision": 15,
            "xAxis": {"min": 20, "max": 20000, "scale": "log", "label": "Frequency", "unit": "Hz"},
            "yAxis": {"min": -100, "max": 0, "scale": "linear", "label": "Level", "unit": "dBFS"},
            "series": [{"name": "beam", "color": "#72D6C9",
                        "points": _log_points(20, 20000, 64,
                                              lambda f, x: -90 + 35 * f - 8 * math.sin(f * 8) ** 2)}],
            "referenceLines": [{"y": -55, "label": "noise floor"}],
        },
        "lag-series": _lag("lag-series"),
        "bands": _bands("bands"),
        "harmonic-bars": {
            "kind": "harmonic-bars", "title": "Harmonics", "subtitle": "THD",
            "chartRevision": 16,
            "yAxis": {"min": -80, "max": 0, "scale": "linear", "label": "Power", "unit": "FS^2"},
            "categories": [{"label": "H1", "value": -6, "valid": True},
                           {"label": "H2", "value": -28, "valid": True},
                           {"label": "H3", "value": -36, "valid": True},
                           {"label": "H4", "value": -44, "valid": True},
                           {"label": "H5", "value": None, "valid": False}],
            "referenceValues": [{"value": -20, "label": "THD ref", "color": "#E2E649"}],
            "scalarRows": [{"label": "THD", "value": 0.08, "valid": True}],
        },
        "insulation-bars": {
            "kind": "insulation-bars", "title": "Relative insulation", "subtitle": "no Rw claim",
            "chartRevision": 17,
            "yAxis": {"min": -10, "max": 40, "scale": "linear", "label": "Difference", "unit": "dB"},
            "categories": [{"label": "125", "value": 5, "valid": True},
                           {"label": "250", "value": 12, "valid": True},
                           {"label": "500", "value": 9, "valid": True},
                           {"label": "1k", "value": -3, "valid": True},
                           {"label": "2k", "value": None, "valid": False}],
            "limitLine": {"value": 0, "label": "no difference"},
        },
        "stft": _stft(),
        "das-map": _das(),
        "pair-spectra": _panels("pair-spectra", "Sxx / Syy / CSD", [
            {"title": "Auto spectra", "series": [
                {"name": "Sxx", "color": "#B9E7ED",
                 "points": _log_points(20, 20000, 64, lambda f, x: -70 + 20 * f)},
                {"name": "Syy", "color": "#E2E649",
                 "points": _log_points(20, 20000, 64, lambda f, x: -74 + 18 * f)}]},
            {"title": "Cross spectrum", "series": [
                {"name": "Re", "color": "#72D6C9",
                 "points": _log_points(20, 20000, 64, lambda f, x: -40 + 12 * math.sin(f * 9))},
                {"name": "Im", "color": "#C74BDA", "dashed": True,
                 "points": _log_points(20, 20000, 64, lambda f, x: -40 + 12 * math.cos(f * 7))}]}]),
        "coherence-phase": _panels("coherence-phase", "Coherence and phase", [
            {"title": "Coherence", "yAxis": {"min": 0, "max": 1, "label": "Coherence", "unit": ""},
             "series": [{"name": "coherence", "color": "#B9E7ED",
                         "points": _log_points(20, 20000, 64,
                                               lambda f, x: 0.35 + 0.6 * math.sin(f * 6) ** 2)}]},
            {"title": "Phase", "yAxis": {"min": -3.2, "max": 3.2, "label": "Phase", "unit": "rad"},
             "series": [{"name": "phase", "color": "#E2E649", "unit": "rad",
                         "points": _log_points(20, 20000, 64,
                                               lambda f, x: 3.0 * math.sin(f * 11))}]}]),
        "weighting": _panels("weighting", "Frequency / time weighting", [
            {"title": "Relative frequency weighting A/C/Z", "series": [
                {"name": "A", "color": "#B9E7ED",
                 "points": _log_points(20, 20000, 48, lambda f, x: -50 * (1 - f) - 9 * f ** 4)},
                {"name": "C", "color": "#E2E649",
                 "points": _log_points(20, 20000, 48, lambda f, x: -6 * (1 - f) - 11 * f ** 4)},
                {"name": "Z", "color": "#72D6C9", "dashed": True,
                 "points": _log_points(20, 20000, 48, lambda f, x: 0.0)}]},
            {"title": "Z time weighting FAST / SLOW / Leq", "series": [
                {"name": "FAST", "color": "#B9E7ED",
                 "points": [[round(i * 0.1, 3), round(-34 + 4 * math.sin(i * 0.7) ** 2, 3)]
                            for i in range(40)]},
                {"name": "SLOW", "color": "#C74BDA", "dashed": True,
                 "points": [[round(i * 0.1, 3), round(-36 + 3 * math.sin(i * 0.4) ** 2, 3)]
                            for i in range(40)]},
                {"name": "LeqFS", "color": "#E2E649",
                 "points": [[round(i * 0.1, 3), round(-33 + 2 * math.sin(i * 0.25) ** 2, 3)]
                            for i in range(40)]}]}]),
        "room-decay": _decay(),
        "room-clarity": _readout("room-clarity", "Room clarity", [
            {"name": "C50", "color": "#B9E7ED",
             "points": [[63, 1], [125, 3], [250, 5], [500, 7], [1000, 8], [2000, 9],
                        [4000, 10], [8000, 9]]},
            {"name": "C80", "color": "#E2E649", "dashed": True,
             "points": [[63, 3], [125, 5], [250, 7], [500, 9], [1000, 10], [2000, 11],
                        [4000, 12], [8000, 11]]}],
            [{"label": "C50", "value": 7.2, "unit": "dB", "valid": True},
             {"label": "C80", "value": 9.4, "unit": "dB", "valid": True},
             {"label": "D50", "value": 48, "unit": "%", "valid": True}]),
        "statistics": _panels("statistics", "Level statistics", [
            {"title": "Level distribution", "xAxis": {"min": -60, "max": -20,
                                                      "scale": "linear", "label": "Level",
                                                      "unit": "dBFS"},
             "yAxis": {"min": 0, "max": 1, "scale": "linear", "label": "Fraction", "unit": ""},
             "series": [{"name": "CDF", "color": "#B9E7ED",
                         "points": [[-60, 0], [-50, 0.02], [-40, 0.15], [-35, 0.4],
                                    [-30, 0.7], [-25, 0.92], [-20, 1.0]]}],
             "markers": [{"x": -31, "y": 0.5, "label": "L50", "kind": "peak"}]},
            {"title": "Leq trend", "yAxis": {"min": -45, "max": -20, "scale": "linear",
                                             "label": "Leq", "unit": "dBFS"},
             "series": [{"name": "Leq", "color": "#E2E649",
                         "points": [[round(i * 0.5, 2), round(-34 + 2 * math.sin(i * 0.3), 2)]
                                    for i in range(20)]}]}],
            [{"label": "L10", "value": -26.4, "unit": "dBFS", "valid": True},
             {"label": "L50", "value": -31.2, "unit": "dBFS", "valid": True},
             {"label": "L90", "value": -38.7, "unit": "dBFS", "valid": True},
             {"label": "Leq", "value": -33.5, "unit": "dBFS", "valid": True}]),
        "noise-rating": _noise(),
        "ab-spectrum": _ab(),
        "level-bars": {
            "kind": "level-bars", "title": "Channel levels", "subtitle": "six channels",
            "chartRevision": 18,
            "meters": [
                {"label": "CH1", "color": "#B9E7ED", "value": -18.4, "peak": -9.2, "valid": True},
                {"label": "CH2", "color": "#E2E649", "value": -22.1, "peak": -12.4, "valid": True},
                {"label": "CH3", "color": "#C74BDA", "value": -30.2, "peak": -21.0, "valid": True,
                 "clip": True},
                {"label": "CH4", "color": "#72D6C9", "value": -27.8, "peak": -17.6, "valid": True},
                {"label": "CH5", "color": "#93D272", "value": None, "valid": False},
                {"label": "CH6", "color": "#B2C4F0", "value": -41.2, "peak": -33.1, "valid": True}],
            "scale": {"min": -60, "max": 0, "label": "Level", "unit": "dBFS"},
        },
        "waveform": _waveform(),
        "scalars": {
            "kind": "scalars", "title": "Continuity counters", "subtitle": "instrument readouts",
            "chartRevision": 19,
            "scalarRows": [
                {"label": "frames", "value": 1200, "valid": True},
                {"label": "samples", "value": 7372800, "valid": True},
                {"label": "dropped frames", "value": 2, "valid": True, "tone": "warn"},
                {"label": "last frame", "value": None, "valid": False}],
        },
        "capability": {
            "kind": "capability", "title": "Spatial interface capability", "subtitle": "manual",
            "chartRevision": 20,
            "text": ("Directional analysis capability only: manual azimuth/elevation "
                     "selection is available; automatic DOA, XYZ source positions and "
                     "tracking are not part of this interface."),
            "scalarRows": [{"label": "channels", "value": 6, "valid": True},
                           {"label": "auto DOA", "value": None, "valid": False}],
            "caption": "capability description; no automatic DOA is provided",
        },
        "events": _events(),
        "stipa": _stipa(),
    }
