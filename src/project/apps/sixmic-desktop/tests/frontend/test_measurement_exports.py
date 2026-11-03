"""File-only export tests: supplied numeric data and real captured PCM survive."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import wave

import pytest

from ui.viewmodels.measurement_exports import export_event_file, export_feature
from sixmic_backend.errors import BackendError
from sixmic_backend.protocol.event_file import build_event_container
from sixmic_backend.protocol.pcm import encode_record

BIG = 9007199254740993


def read_csv(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def workspace():
    return {"featureId": "stft", "jobId": "job-7", "sourceKind": "test-fixture",
            "provenance": ["Synthetic fixture, not acoustic measurement"],
            "chart": {"kind": "stft", "units": "FS²/Hz", "xAxis": {"unit": "Hz"},
                      "yAxis": {"unit": "dB"}, "colorScale": {"unit": "FS²/Hz"},
                      "series": [{"name": "CH1", "unit": "FS", "points": [[20, 0.5], [50, None], [100, float("nan")]]}],
                      "categories": [{"label": "125", "centerFrequency": 125, "value": -32.5, "unit": "dBFS", "valid": False}],
                      "scalarRows": [{"label": "Level", "value": -40.25, "unit": "dBFS", "valid": True}],
                      "raster": {"matrix": [[0.2, None], [float("inf"), 0.4]], "azimuths": [0, 30], "elevations": [0, 10]},
                      "frames": [{"time": 0.2, "frameFirstSampleIndex": str(BIG), "points": [[125, 0.3], [250, None]]}],
                      "points": [{"azimuthDeg": 30, "elevationDeg": 10, "power": 0.7, "valid": True}],
                      "panels": [{"series": [{"name": "phase", "points": [[125, 0.6]], "unit": "rad"}]}],
                      "channels": [{"name": "CH1", "values": [0.2, None], "bucketSize": 2, "sourceSampleCount": 4}],
                      "meters": [{"label": "CH1", "value": -40, "peak": -3, "valid": True, "clip": False}],
                      "events": [{"eventId": str(BIG), "label": "clip", "kind": "warn", "position": 0.5}]},
            "variants": [{"id": "A", "chart": {"scalarRows": [{"label": "Reference", "value": 12, "unit": "count", "valid": True}]}}]}


def test_feature_exports_typed_tables_and_preserves_invalid_data(tmp_path):
    raw = {"featureId": "stft", "jobId": "job-7", "sourceKind": "test-fixture",
           "schema": {"encoding": "float32-bits", "units": "FS²/Hz"},
           "configuration": {"generation": str(BIG)}, "totalWords": 3,
           "words": [0, 0x3F000000, 0xFFFFFFFF], "fixture": True}
    paths = export_feature(tmp_path, workspace(), raw)
    assert {"series", "categories", "scalars", "raster", "frames", "points", "channels", "meters", "events", "raw_words", "raw", "metadata", "readme"} <= paths.keys()
    series = read_csv(paths["series"])
    assert series[0]["y"] == "0.5" and series[0]["y_unit"] == "FS"
    assert series[1]["y"] == "" and series[1]["valid"] == "0"
    assert series[2]["y"] == "NaN" and series[2]["valid"] == "0"
    assert series[3]["chart"] == "chart.panels[0]" and series[3]["y_unit"] == "rad"
    category = read_csv(paths["categories"])[0]
    assert category["value"] == "-32.5" and category["valid"] == "0"
    raster = read_csv(paths["raster"])
    assert raster[1]["value"] == "" and raster[2]["value"] == "+Infinity"
    assert raster[3]["x"] == "30" and raster[3]["y"] == "10"
    assert read_csv(paths["frames"])[0]["sample_index"] == str(BIG)
    assert read_csv(paths["raw_words"])[2]["uint32"] == "4294967295"
    assert read_csv(paths["scalars"])[1]["chart"] == "variants[0].chart"
    metadata = json.loads(Path(paths["metadata"]).read_text(encoding="utf-8"))
    assert metadata["workspace"]["sourceKind"] == "test-fixture"
    assert metadata["rawMetadata"]["schema"] == raw["schema"]
    assert metadata["rawMetadata"]["configuration"] == raw["configuration"]
    assert metadata["chartCsvDisplayOnly"] is True and metadata["fullRawAvailable"] is True
    assert json.loads(Path(paths["raw"]).read_text(encoding="utf-8")) == raw


def test_exports_cannot_overwrite_and_do_not_invent_raster_coordinates(tmp_path):
    data = {"featureId": "../../fft", "chart": {"raster": {"matrix": [[1, None]]}}}
    first, second = export_feature(tmp_path, data), export_feature(tmp_path, data)
    assert first["metadata"] != second["metadata"]
    assert Path(first["metadata"]).is_relative_to(tmp_path)
    assert read_csv(first["raster"])[0]["x"] == ""
    assert json.loads(Path(first["metadata"]).read_text())["fullRawAvailable"] is False


@pytest.mark.parametrize("raw", [
    {"featureId": "other", "words": []},
    {"featureId": "stft", "jobId": "other", "words": []},
    {"sourceKind": "pl-live", "words": []},
    {"words": [1], "totalWords": 2},
    {"words": [-1]},
    {"words": [True]},
])
def test_feature_rejects_mixed_identity_or_incomplete_raw_before_writing(tmp_path, raw):
    with pytest.raises(ValueError):
        export_feature(tmp_path, workspace(), raw)
    assert list(tmp_path.iterdir()) == []


def event_file(directory, indices=None, *, sidecar=True, sample_rate=48009.775390625):
    indices = indices or [BIG, BIG + 1, BIG + 2]
    samples = [(-(1 << 23), (1 << 23) - 1, 123456, -123456, 1, -1),
               (456, -789, 0, 10, -20, 30), (999, 888, 777, 666, 555, 444)]
    records = b"".join(encode_record(samples[i % 3], index) for i, index in enumerate(indices))
    container = build_event_container(event_id=7, flags=1 | 4, clip_reason=5,
                                      first_sample_index=indices[0], last_sample_index=indices[-1],
                                      sample_rate_hz=sample_rate, records=records)
    path = directory / "event.smc"
    path.write_bytes(container)
    if sidecar:
        path.with_name("manifest.json").write_text(json.dumps({"eventId": "7", "sha256": hashlib.sha256(container).hexdigest(),
            "provenance": {"sourceKind": "test-fixture"}}), encoding="utf-8")
    return path, samples[:len(indices)], container


def pcm24_values(data):
    values = []
    for offset in range(0, len(data), 3):
        raw = int.from_bytes(data[offset:offset + 3], "little")
        values.append(raw - (1 << 24) if raw & (1 << 23) else raw)
    return values


def test_event_wav_is_actual_captured_pcm_and_csv_keeps_uint64_indices(tmp_path):
    path, samples, container = event_file(tmp_path)
    paths = export_event_file(path, tmp_path / "out")
    with wave.open(paths["wav"], "rb") as stream:
        assert (stream.getnchannels(), stream.getsampwidth(), stream.getnframes(), stream.getframerate()) == (6, 3, 3, 48010)
        assert pcm24_values(stream.readframes(3)) == [value for row in samples for value in row]
    rows = read_csv(paths["csv"])
    assert rows[0]["sample_index"] == str(BIG)
    assert rows[1]["sample_index"] == str(BIG + 1)
    assert rows[0]["ch1_pcm24"] == "-8388608"
    metadata = json.loads(Path(paths["metadata"]).read_text())
    assert metadata["sourceKind"] == "test-fixture" and metadata["fixture"] is True
    assert metadata["sourceSha256"] == hashlib.sha256(container).hexdigest()
    assert metadata["storedHashVerified"] is True
    assert metadata["realSampleRateHz"] == 48009.7734375  # Producer's actual float32 header.
    assert metadata["wavSegments"][0]["rateRoundingErrorHz"] == 48010 - 48009.7734375
    assert metadata["flags"]["incomplete"] and metadata["flags"]["summaryStale"]
    assert metadata["resampled"] is False and metadata["syntheticSamplesInserted"] == 0


def test_event_gaps_split_wav_without_inserting_or_collapsing_samples(tmp_path):
    path, _, _ = event_file(tmp_path, [BIG, BIG + 1, BIG + 6])
    paths = export_event_file(path, tmp_path / "out")
    assert "wav" not in paths and {"wav_001", "wav_002"} <= paths.keys()
    with wave.open(paths["wav_001"], "rb") as stream:
        assert stream.getnframes() == 2
    with wave.open(paths["wav_002"], "rb") as stream:
        assert stream.getnframes() == 1
    rows = read_csv(paths["csv"])
    assert rows[2]["segment"] == "2" and rows[2]["gap_before"] == "1"
    metadata = json.loads(Path(paths["metadata"]).read_text())
    assert metadata["gaps"] == [{"firstMissingSampleIndex": str(BIG + 2), "lastMissingSampleIndex": str(BIG + 5), "missingSamples": "4"}]


def test_event_missing_or_corrupt_input_does_not_create_export(tmp_path):
    target = tmp_path / "out"
    with pytest.raises(FileNotFoundError):
        export_event_file(tmp_path / "missing.smc", target)
    path = tmp_path / "event.smc"
    path.write_bytes(b"not an event")
    with pytest.raises(BackendError):
        export_event_file(path, target)
    assert not target.exists()


def test_event_hash_tamper_rejected_before_export(tmp_path):
    path, _, container = event_file(tmp_path)
    changed = bytearray(container)
    changed[64] ^= 1  # Changes a valid sample, not the header CRC or endpoints.
    path.write_bytes(changed)
    with pytest.raises(ValueError, match="SHA256"):
        export_event_file(path, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_event_missing_source_is_unknown_and_bad_middle_record_is_rejected(tmp_path):
    path, _, container = event_file(tmp_path, sidecar=False)
    paths = export_event_file(path, tmp_path / "out")
    metadata = json.loads(Path(paths["metadata"]).read_text())
    assert metadata["sourceKind"] == "unknown" and metadata["storedHashVerified"] is False
    changed = bytearray(container)
    changed[64 + 32 + 3] = 255  # Invalid sign extension in the middle record.
    path.write_bytes(changed)
    with pytest.raises(BackendError):
        export_event_file(path, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


def test_event_backwards_indices_and_invalid_rate_are_rejected(tmp_path):
    path, _, _ = event_file(tmp_path, [BIG, BIG + 2, BIG + 1], sidecar=False)
    with pytest.raises(ValueError, match="increase"):
        export_event_file(path, tmp_path / "out")
    path, _, _ = event_file(tmp_path, sidecar=False, sample_rate=float("nan"))
    with pytest.raises(ValueError, match="sample rate"):
        export_event_file(path, tmp_path / "out")
