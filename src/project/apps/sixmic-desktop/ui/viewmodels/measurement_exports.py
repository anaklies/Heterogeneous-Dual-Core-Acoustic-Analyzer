"""Lossless file/format exports for device results; no acoustic computation.

Chart CSVs contain the supplied display samples, not a claim of full-resolution
measurement data. Raw words/schema are exported separately when available.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

MAX_EVENT_BYTES = 64 * 1024 * 1024


def _safe_json(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return "NaN" if math.isnan(value) else ("+Infinity" if value > 0 else "-Infinity")
    if isinstance(value, dict):
        return {str(key): _safe_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_safe_json(item) for item in value]
    return value


def _json(path: Path, payload: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(_safe_json(payload), stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(_safe_json(value), ensure_ascii=False, allow_nan=False)
    return _safe_json(value)


def _csv(path: Path, columns: list[str], rows: Iterable[Iterable[Any]]) -> None:
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([_csv_value(value) for value in row])


def _folder(directory: Path, identity: str) -> Path:
    name = "".join(char for char in str(identity) if char.isalnum() or char in "-_")[:80] or "measurement"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    folder = Path(directory) / f"{name}-{stamp}-{uuid4().hex}"
    folder.mkdir(parents=True, exist_ok=False)
    return folder


def _valid(value: Any, explicit: Any = True) -> bool:
    return explicit is not False and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _axis(chart: dict[str, Any], name: str) -> dict[str, Any]:
    value = chart.get(name)
    return value if isinstance(value, dict) else {}


def export_feature(directory: Path, workspace: dict, raw_payload: dict | None = None) -> dict[str, str]:
    """Export current workspace display tables, exact metadata and optional raw words.

    The caller must snapshot the workspace and matching raw payload together.
    Source labels, invalid samples, references and variants are retained. A CSV
    suffix identifies its table; metadata.json records the original payloads.
    """
    if not isinstance(workspace, dict):
        raise ValueError("Feature export requires a workspace object")
    fid = str(workspace.get("featureId") or "measurement")
    if raw_payload is not None:
        if not isinstance(raw_payload, dict):
            raise ValueError("Raw result must be an object")
        if raw_payload.get("featureId") and raw_payload["featureId"] != fid:
            raise ValueError("Workspace and raw result feature identities differ")
        if workspace.get("jobId") and raw_payload.get("jobId") and workspace["jobId"] != raw_payload["jobId"]:
            raise ValueError("Workspace and raw result job identities differ")
        if workspace.get("sourceKind") and raw_payload.get("sourceKind") and workspace["sourceKind"] != raw_payload["sourceKind"]:
            raise ValueError("Workspace and raw result sources differ")
        words = raw_payload.get("words") or []
        if not isinstance(words, (list, tuple)) or any(isinstance(word, bool) or not isinstance(word, int) or not 0 <= word <= 0xFFFFFFFF for word in words):
            raise ValueError("Raw words must be unsigned 32-bit integers")
        if int(raw_payload.get("totalWords", len(words))) != len(words):
            raise ValueError("Full raw result is unavailable or its word count is inconsistent")

    tables: dict[str, tuple[list[str], list[list[Any]]]] = {
        "series": (["chart", "series", "point_index", "x", "y", "x_unit", "y_unit", "valid"], []),
        "categories": (["chart", "category_index", "label", "center_frequency_hz", "value", "unit", "valid"], []),
        "scalars": (["chart", "row_index", "label", "value", "unit", "valid"], []),
        "raster": (["chart", "row", "column", "x", "y", "value", "unit", "valid"], []),
        "frames": (["chart", "frame_index", "time_seconds", "sample_index", "point_index", "frequency_hz", "value", "unit", "valid", "relative_time_seconds"], []),
        "points": (["chart", "point_index", "azimuth_deg", "elevation_deg", "power", "unit", "valid"], []),
        "events": (["chart", "event_index", "event_id", "position", "label", "kind", "event_json"], []),
        "channels": (["chart", "channel", "display_sample_index", "value", "unit", "valid", "bucket_size", "source_sample_count"], []),
        "meters": (["chart", "channel", "value", "peak", "unit", "valid", "clip"], []),
    }

    def collect(chart: Any, location: str) -> None:
        if not isinstance(chart, dict):
            return
        unit = chart.get("units", chart.get("unit", ""))
        xu, yu = _axis(chart, "xAxis").get("unit", ""), _axis(chart, "yAxis").get("unit", unit)
        for si, series in enumerate(chart.get("series") or []):
            if not isinstance(series, dict):
                continue
            for pi, point in enumerate(series.get("points") or []):
                if not isinstance(point, (list, tuple)):
                    continue
                x, y = (point[0] if point else None), (point[1] if len(point) > 1 else None)
                tables["series"][1].append([location, series.get("name", si), pi, x, y, xu, series.get("unit", yu), _valid(x) and _valid(y, series.get("valid", True))])
        for ci, category in enumerate(chart.get("categories") or []):
            if isinstance(category, dict):
                value = category.get("value")
                tables["categories"][1].append([location, ci, category.get("label", ""), category.get("centerFrequency"), value, category.get("unit", yu), _valid(value, category.get("valid", True))])
        for ri, row in enumerate(chart.get("scalarRows") or []):
            if isinstance(row, dict):
                value = row.get("value")
                valid = row.get("valid", value is not None) is not False
                if isinstance(value, float) and not math.isfinite(value):
                    valid = False
                tables["scalars"][1].append([location, ri, row.get("label", ""), value, row.get("unit", unit), valid])
        raster = chart.get("raster") or {}
        if isinstance(raster, dict):
            xs = raster.get("azimuths") or raster.get("xValues") or []
            ys = raster.get("elevations") or raster.get("yValues") or []
            for ri, row in enumerate(raster.get("matrix") or []):
                if not isinstance(row, (list, tuple)):
                    continue
                for ci, value in enumerate(row):
                    tables["raster"][1].append([location, ri, ci, xs[ci] if ci < len(xs) else None, ys[ri] if ri < len(ys) else None, value, _axis(chart, "colorScale").get("unit", unit), _valid(value)])
        for fi, frame in enumerate(chart.get("frames") or []):
            if not isinstance(frame, dict):
                continue
            for pi, point in enumerate(frame.get("points") or []):
                if isinstance(point, (list, tuple)):
                    x, y = (point[0] if point else None), (point[1] if len(point) > 1 else None)
                    tables["frames"][1].append([location, fi, frame.get("time"), frame.get("frameFirstSampleIndex", frame.get("sampleIndex", frame.get("firstSampleIndex"))), pi, x, y, _axis(chart, "colorScale").get("unit", unit), _valid(x) and _valid(y, frame.get("valid", True)), frame.get("displayTimeSeconds")])
        for pi, point in enumerate(chart.get("points") or []):
            if isinstance(point, dict):
                value = point.get("power")
                tables["points"][1].append([location, pi, point.get("azimuthDeg"), point.get("elevationDeg"), value, unit, _valid(value, point.get("valid", True))])
        for ei, event in enumerate(chart.get("events") or []):
            if isinstance(event, dict):
                tables["events"][1].append([location, ei, event.get("eventId"), event.get("position"), event.get("label"), event.get("kind"), event])
        for ci, channel in enumerate(chart.get("channels") or []):
            if isinstance(channel, dict):
                for index, value in enumerate(channel.get("values") or []):
                    tables["channels"][1].append([location, channel.get("name", ci), index, value, yu, _valid(value), channel.get("bucketSize"), channel.get("sourceSampleCount")])
        for ci, meter in enumerate(chart.get("meters") or []):
            if isinstance(meter, dict):
                value = meter.get("value")
                tables["meters"][1].append([location, meter.get("label", ci), value, meter.get("peak"), yu, _valid(value, meter.get("valid", True)), meter.get("clip")])
        for pi, panel in enumerate(chart.get("panels") or []):
            collect(panel, f"{location}.panels[{pi}]")

    collect(workspace.get("chart"), "chart")
    for vi, variant in enumerate(workspace.get("variants") or []):
        if isinstance(variant, dict):
            collect(variant.get("chart"), f"variants[{vi}].chart")
    folder = _folder(directory, fid)
    paths: dict[str, str] = {}
    for name, (columns, rows) in tables.items():
        if rows:
            path = folder / f"{name}.csv"
            _csv(path, columns, rows)
            paths[name] = str(path)
    if raw_payload is not None:
        path = folder / "raw.json"
        _json(path, raw_payload)
        paths["raw"] = str(path)
        path = folder / "raw_words.csv"
        _csv(path, ["word_index", "uint32"], enumerate(raw_payload.get("words") or []))
        paths["raw_words"] = str(path)
    path = folder / "metadata.json"
    _json(path, {"format": "echo-feature-export-v1", "workspace": workspace,
                 "rawMetadata": {key: value for key, value in (raw_payload or {}).items() if key != "words"},
                 "chartCsvDisplayOnly": True, "fullRawAvailable": raw_payload is not None,
                 "nonFiniteEncoding": "NaN/+Infinity/-Infinity strings; null remains null",
                 "files": paths})
    paths["metadata"] = str(path)
    path = folder / "README.txt"
    path.write_text("Chart CSV files contain supplied display samples and preserve invalid cells.\n"
                    "Full measurement words, when available, are in raw.json/raw_words.csv; use their schema/configuration.\n"
                    "No DSP, interpolation or inferred coordinates are performed. Units and provenance are in metadata.json.\n"
                    "MATLAB: T = readtable('series.csv'); M = jsondecode(fileread('metadata.json'));\n"
                    "For uint64 sample indices in frame/event CSV, import sample_index/event_id as string to avoid double rounding.\n", encoding="utf-8")
    paths["readme"] = str(path)
    return paths


def export_event_file(event_path: Path, directory: Path) -> dict[str, str]:
    """Export verified SMC1 samples as PCM24 WAV segment(s), CSV and metadata.

    Gaps are explicit and split WAV files; missing time is never filled with
    synthetic silence or collapsed into a single continuous audio stream.
    """
    from sixmic_backend.model.audio import write_wav6_24bit
    from sixmic_backend.protocol.event_file import parse_event_container
    from sixmic_backend.protocol.pcm import decode_record

    event_path = Path(event_path)
    if event_path.stat().st_size > MAX_EVENT_BYTES:
        raise ValueError("Event exceeds the 64 MiB export limit")
    container = parse_event_container(event_path.read_bytes())
    header = container.header
    if not math.isfinite(header.sample_rate_hz) or not 0.5 < header.sample_rate_hz <= 0xFFFFFFFF // (header.channels * 3):
        raise ValueError("Event has no valid positive sample rate")
    if header.record_count == 0:
        raise ValueError("Event contains no PCM samples to export")
    manifest_path = event_path.with_name("manifest.json")
    manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        candidate = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(candidate, dict):
            raise ValueError("Event manifest must be a JSON object")
        manifest = candidate
        if manifest.get("sha256") and str(manifest["sha256"]).lower() != container.sha256.lower():
            raise ValueError("Event SHA256 does not match its stored manifest")
        if manifest.get("eventId") is not None and str(manifest["eventId"]) != str(header.event_id):
            raise ValueError("Event identity differs from its stored manifest")
    segments = []
    gaps = []
    segment_start = 0
    segment_first = header.first_sample_index
    previous_index = None
    for offset in range(0, len(container.records), header.record_bytes):
        record = decode_record(container.records[offset:offset + header.record_bytes])
        if previous_index is not None and record.sample_index <= previous_index:
            raise ValueError("Event sample indices must increase strictly")
        gap = previous_index is not None and record.sample_index != previous_index + 1
        if gap:
            position = offset // header.record_bytes
            segments.append((segment_start, position, segment_first, previous_index))
            segment_start = position
            segment_first = record.sample_index
            gaps.append({"firstMissingSampleIndex": str(previous_index + 1),
                         "lastMissingSampleIndex": str(record.sample_index - 1),
                         "missingSamples": str(record.sample_index - previous_index - 1)})
        previous_index = record.sample_index
    segments.append((segment_start, header.record_count, segment_first, previous_index))
    folder = _folder(directory, f"event-{header.event_id}")
    paths = {}
    wav_segments = []
    for index, (start, end, first_index, last_index) in enumerate(segments):
        key = "wav" if len(segments) == 1 else f"wav_{index + 1:03d}"
        path = folder / f"{key}.wav"
        audio = write_wav6_24bit(path, container.records[start * header.record_bytes:end * header.record_bytes], real_sample_rate_hz=header.sample_rate_hz)
        audio.update(firstSampleIndex=str(first_index),
                     lastSampleIndex=str(last_index),
                     firstCsvRow=start, lastCsvRow=end - 1)
        wav_segments.append(audio)
        paths[key] = str(path)
    path = folder / "samples.csv"
    def rows():
        segment = 0
        for i in range(header.record_count):
            offset = i * header.record_bytes
            sample = decode_record(container.records[offset:offset + header.record_bytes])
            if i >= segments[segment][1]:
                segment += 1
            yield [str(sample.sample_index), (sample.sample_index - header.first_sample_index) / header.sample_rate_hz,
                   segment + 1, i == segments[segment][0] and segment > 0, *sample.samples]
    _csv(path, ["sample_index", "relative_time_s", "segment", "gap_before", "ch1_pcm24", "ch2_pcm24", "ch3_pcm24", "ch4_pcm24", "ch5_pcm24", "ch6_pcm24"], rows())
    paths["csv"] = str(path)
    provenance = manifest.get("provenance") or {}
    source = manifest.get("sourceKind") or (provenance.get("sourceKind") if isinstance(provenance, dict) else None) or "unknown"
    if manifest.get("fixture") is True:
        source = "test-fixture"
    path = folder / "metadata.json"
    _json(path, {"format": "echo-event-export-v1", "eventId": str(header.event_id),
                 "sourceKind": source, "fixture": source == "test-fixture",
                 "sourceFile": str(event_path), "sourceSha256": container.sha256,
                 "storedHashVerified": bool(manifest.get("sha256")), "storedManifest": manifest,
                 "realSampleRateHz": header.sample_rate_hz, "sampleRateBits": header.sample_rate_bits,
                 "channelCount": header.channels, "bitsPerSample": 24, "recordCount": header.record_count,
                 "firstSampleIndex": str(header.first_sample_index), "lastSampleIndex": str(header.last_sample_index),
                 "flags": {"raw": header.flags, "incomplete": header.incomplete,
                           "lostEvents": header.lost_events, "summaryStale": header.summary_stale,
                           "envInvalid": header.env_invalid, "poseInvalid": header.pose_invalid},
                 "clipReasonRaw": header.clip_reason, "gaps": gaps, "wavSegments": wav_segments,
                 "csvSamplesUnit": "signed PCM24 codes; divide by 8388608 for digital full scale",
                 "resampled": False, "syntheticSamplesInserted": 0,
                 "note": "WAV rate is integer rounded; the exact producer float rate and rounding error are preserved per segment. Gaps split WAV files.",
                 "files": paths})
    paths["metadata"] = str(path)
    path = folder / "README.txt"
    path.write_text("Audio contains only captured PCM24 samples; no resampling or synthetic silence.\n"
                    "Each discontinuity splits a WAV segment; samples.csv preserves absolute indices and source-relative time.\n"
                    "MATLAB: [audio,Fs] = audioread('wav.wav'); % use wav_001.wav etc. for gapped events\n"
                    "opts = detectImportOptions('samples.csv'); opts = setvartype(opts,'sample_index','string'); T = readtable('samples.csv',opts);\n"
                    "M = jsondecode(fileread('metadata.json')); % includes exact sample rate, flags, source and gaps\n", encoding="utf-8")
    paths["readme"] = str(path)
    return paths
