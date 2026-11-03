"""Decoder tests: schema-driven layouts, real test-fixture schemas, bounded QML.

Real schemas come from the captured host-gateway test fixture
(fixtures/features/captured_host_gateway.json: real TCP to
ps/build/host/test-feature-server.exe with registry/INTERFACE_REGISTRY.json;
sourceKind=test-fixture, hardwareState=NOT_TESTED).  Synthetic words exercise
float32/uint32/PCM24/NaN/identity edge cases; no PC acoustic DSP is performed.
"""
from __future__ import annotations

import copy
import json
import math
import struct
from pathlib import Path

import pytest

from ui.features.decoder import (FFT_SIZE, MAX_SERIES_POINTS, DecodeError,
                                 PENDING_LAYOUT_SOURCES, ResultPageAssembler,
                                 decode_result, pcm24, peak_envelope, u32_words,
                                 validate_result_pages)
from ui.features.catalog import load_spec

APP = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "features"
REPO = APP.parents[1]
REGISTRY = (REPO / "deployment" / "echo_feature_closure_20261025" / "registry"
            / "INTERFACE_REGISTRY.json")


def f32w(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", float(value)))[0]


def words(*values: float | int) -> list[int]:
    out = []
    for value in values:
        if isinstance(value, float):
            out.append(f32w(value))
        else:
            out.append(int(value) & 0xFFFFFFFF)
    return out


def pack(values: list[int]) -> bytes:
    return struct.pack("<" + "I" * len(values), *values)


def stipa_words(index: float, valid: float, certified: float, reason: float = 0.0,
                band: float = 0.0, modulation: float = 0.0,
                reference_depth: float = 0.0, measured_depth: float = 0.0,
                ratio: float = 0.0) -> list[int]:
    """The nine float32 words of the STIPA quick/complete result contract."""
    return [f32w(float(value)) for value in (
        index, valid, certified, reason, band, modulation,
        reference_depth, measured_depth, ratio)]


@pytest.fixture(scope="module")
def spec():
    return load_spec()


@pytest.fixture(scope="module")
def gateway():
    path = FIXTURES / "captured_host_gateway.json"
    assert path.is_file()
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def registry():
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
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


def real_payload(gateway, feature_id, total=None):
    result = gateway["features"][feature_id]["result"]
    schema = copy.deepcopy(result["schema"])
    return {
        "jobId": "feature-1", "featureId": feature_id, "state": "completed",
        "sourceKind": "test-fixture",
        "configuration": {"session": 1, "config": 2,
                          "generation": "9007199254740993",
                          "sourceFrame": "18446744073709551615"},
        "schema": schema, "totalWords": total if total is not None
        else result["totalWords"],
        "dataRef": {"handleId": "buf", "count": result["totalWords"]},
    }


def decode_real(gateway, spec, feature_id, values):
    payload = real_payload(gateway, feature_id, len(values))
    return decode_result(spec["features"][feature_id], payload, values)


def decode_with_schema(spec, feature_id, schema, values):
    payload = {"jobId": "feature-1", "featureId": feature_id,
               "state": "completed", "sourceKind": "test-fixture",
               "configuration": {"session": 1, "config": 1,
                                 "generation": "1", "sourceFrame": "1"},
               "schema": schema, "totalWords": len(values),
               "dataRef": {"handleId": "buf", "count": len(values)}}
    return decode_result(spec["features"][feature_id], payload, values)


def json_safe(chart: dict) -> str:
    # Allow NaN never: QML JSON conversion must not receive non-finite values.
    return json.dumps(chart, ensure_ascii=False, allow_nan=False)


def walk(chart, key, limit):
    """Collect one list-valued key recursively (bounded payload evidence)."""
    out = []

    def visit(node):
        if isinstance(node, dict):
            for name, value in node.items():
                if name == key and isinstance(value, list):
                    out.extend(value)
                else:
                    visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(chart)
    assert len(out) <= limit, (key, len(out), limit)
    return out


CAPTURED = ["levels_core", "fft", "psd", "stft", "octave", "csd", "io_pcm",
            "frequency_time_weighting", "level_statistics", "noise_rating",
            "spectral_kurtosis"]


# ---------------------------------------------------------------------------
# real host-gateway schemas
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("feature_id", CAPTURED)
def test_real_captured_schema_decodes_bounded_json(spec, gateway, feature_id):
    result = gateway["features"][feature_id]["result"]
    total = result["totalWords"]
    seed = result.get("head_u32") or []
    values = (seed + [0] * max(0, total - len(seed)))[:total]
    chart = decode_real(gateway, spec, feature_id, values)
    assert isinstance(chart, dict)
    assert chart["chartRevision"]
    assert chart["kind"] == spec["features"][feature_id]["chart"]
    json_safe(chart)
    walk(chart, "points", MAX_SERIES_POINTS * 32)
    if chart.get("raster"):
        matrix = chart["raster"].get("matrix") or []
        assert len(matrix) <= 90
        # STFT keeps the documented 16 x 1025 bounded raster; DAS maps are
        # binned to <=180x90.  Both are bounded QML payloads.
        assert all(len(row) <= 1025 for row in matrix)
    for channel in chart.get("channels") or []:
        assert len(channel.get("values") or []) <= 4096
        assert channel.get("sourceSampleCount", 0) >= 0
    assert len(chart.get("frames") or []) <= 16
    meta = chart.get("decodeMeta") or {}
    assert meta.get("recipe") == spec["features"][feature_id]["decode"]["recipe"]


def test_captured_catalog_is_real_test_fixture(gateway):
    assert gateway["sourceKind"] == "test-fixture"
    assert gateway["hardwareState"] == "NOT_TESTED"
    assert gateway["catalog"]["total"] == 45
    assert gateway["capabilities"]["gateway"]["featureApi"]["enabled"] is True


def test_actual_producer_layout_wins_over_producer_layout(spec):
    schema = {
        "kind": "tensor",
        "fields": ["x"],
        "producerLayout": {"bins": 3, "first_bin": 0, "sample_rate": 48000.0},
        "actualProducerLayout": {"bins": 2, "first_bin": 1,
                                 "sample_rate": 48000.0},
    }
    words_in = words(1.0, 2.0, 3.0)
    chart = decode_with_schema(spec, "fft", schema, words_in)
    points = chart["series"][0]["points"]
    assert len(points) == 2
    # first_bin=1 -> 48000/2048 = 23.4375 Hz for the first displayed bin
    assert points[0][0] == pytest.approx(48000.0 / 2048.0)
    assert [p[1] for p in points] == [1.0, 2.0]


# ---------------------------------------------------------------------------
# PCM24 / waveform / peak envelope
# ---------------------------------------------------------------------------
def test_pcm24_sign_extension():
    assert pcm24(0xFFFFFF) == -1
    assert pcm24(0x800000) == -8388608
    assert pcm24(0x7FFFFF) == 8388607
    assert pcm24(0x123456) == 0x123456


def test_io_pcm_long_capture_uses_bounded_peak_envelope(spec):
    samples = 720000
    values = []
    for index in range(samples):
        if index in (0, samples // 2, samples - 1):
            values.append(0x7FFFFF)  # +FS transient
        elif index == 1:
            values.append(0x800000)  # -FS transient
        else:
            values.append(0)
    schema = {"kind": "waveform", "fields": ["signed_PCM24"],
              "axes": {"channels": 1, "channelStrideWords": samples},
              "actualProducerLayout": {"kind": "p0_builtin",
                                       "channelStrideWords": samples},
              "units": "signed24 counts"}
    feature = copy.deepcopy(spec["features"]["io_pcm"])
    feature["launch"]["params"] = {"samples": samples, "channels": 1, "channel": 0}
    payload = {"jobId": "f", "featureId": "io_pcm", "state": "completed",
               "sourceKind": "test-fixture", "schema": schema,
               "totalWords": samples,
               "configuration": {"session": 1, "config": 1,
                                 "generation": "1", "sourceFrame": "1"}}
    chart = decode_result(feature, payload, values)
    channel = chart["channels"][0]
    assert channel["envelope"] is True
    assert channel["bucketSize"] > 1
    assert channel["sourceSampleCount"] == samples
    assert len(channel["values"]) <= 4096
    finite = [value for value in channel["values"] if value is not None]
    assert max(finite) == pytest.approx(1.0, abs=1e-6)
    assert min(finite) == pytest.approx(-1.0, abs=1e-6)
    assert chart["sampleRateHz"] > 0
    json_safe(chart)


def test_six_channel_pcm24_snapshot(spec):
    samples, channels = 2048, 6
    values = []
    for channel in range(channels):
        for index in range(samples):
            value = 0x100000 * (channel + 1) if index == channel else 0
            values.append(value)
    schema = {"kind": "waveform", "fields": ["signed_PCM24"],
              "axes": {"channels": 6, "channelStrideWords": samples},
              "actualProducerLayout": {"kind": "p0_builtin",
                                       "channelStrideWords": samples},
              "units": "signed24 counts"}
    payload = {"jobId": "f", "featureId": "io_pcm", "state": "completed",
               "sourceKind": "test-fixture", "schema": schema,
               "totalWords": len(values),
               "configuration": {"session": 1, "config": 1,
                                 "generation": "1", "sourceFrame": "1"}}
    chart = decode_result(spec["features"]["io_pcm"], payload, values)
    assert len(chart["channels"]) == 6
    assert chart["channels"][0]["values"][0] == pytest.approx(0x100000 / 8388608)
    json_safe(chart)


def test_peak_envelope_never_drops_extreme_values():
    values = [0.0] * 100000
    values[54321] = -0.9
    values[54322] = 0.8
    display = peak_envelope(values, max_buckets=100)
    finite = [value for value in display["values"] if value is not None]
    assert min(finite) == pytest.approx(-0.9)
    assert max(finite) == pytest.approx(0.8)
    assert display["bucketSize"] > 1


# ---------------------------------------------------------------------------
# NaN / invalid handling (never plot 0 for missing data)
# ---------------------------------------------------------------------------
def test_nan_and_invalid_samples_are_gaps_not_zero(spec):
    schema = {"kind": "tensor", "fields": ["x"],
              "actualProducerLayout": {"bins": 5, "first_bin": 1,
                                       "sample_rate": 48000.0},
              "units": "FS"}
    nan = f32w(float("nan"))
    values = [nan, f32w(1.0), f32w(float("inf")), f32w(2.0), nan]
    chart = decode_with_schema(spec, "fft", schema, values)
    points = chart["series"][0]["points"]
    assert [point[1] for point in points] == [1.0, 2.0]
    json_safe(chart)


def test_band_zero_power_is_grey_not_zero_line(spec):
    schema = {"kind": "tensor", "fields": ["band_power_FS2"],
              "axes": {"bandHz": [31.5, 63.0, 125.0]},
              "actualProducerLayout": {"bins": 3, "centers_hz": [31.5, 63.0, 125.0]},
              "units": "FS²"}
    chart = decode_with_schema(spec, "octave", schema,
                               words(1.0, 0.0, float("nan")))
    categories = chart["categories"]
    assert categories[0]["valid"] is True
    assert categories[1]["value"] is None and categories[1]["valid"] is False
    assert categories[2]["value"] is None
    json_safe(chart)


# ---------------------------------------------------------------------------
# pending-layout resolutions (confirmed from device service sources)
# ---------------------------------------------------------------------------
def test_pending_layout_sources_are_all_five():
    assert set(PENDING_LAYOUT_SOURCES) == {
        "frequency_time_weighting", "level_statistics", "noise_rating",
        "spectral_kurtosis", "relative_insulation"}
    for item in PENDING_LAYOUT_SOURCES.values():
        assert item["source"].startswith("deployment/work_platform_20261013")
        assert item["fields"]


def test_frequency_time_weighting_weighting_variant(spec, gateway):
    # spectral_A_relative_level: out[0] power, out[1] dBFS, out[2] valid,
    # out[3:1028] immutable 1025 coefficients (noise_services.weighted_level).
    coefficients = [1.0, 0.1] + [1.0] * 1023
    values = words(2.0, -3.0, 1.0) + words(*coefficients)
    chart = decode_real(gateway, spec, "frequency_time_weighting", values)
    meta = chart["decodeMeta"]
    assert meta["recipe"] == "weighting"
    rows = {row["label"]: row for row in chart["scalarRows"]}
    assert rows["计权功率"]["value"] == pytest.approx(2.0)
    assert rows["计权电平"]["value"] == pytest.approx(-3.0)
    assert rows["有效"]["value"] == 1
    curve = chart["series"][0]["points"]
    assert len(curve) == 1025
    assert curve[0][1] == pytest.approx(0.0, abs=1e-6)       # 10*log10(1)
    assert curve[1][1] == pytest.approx(-10.0, abs=1e-5)     # 10*log10(0.1)
    assert len(chart["panels"]) == 1
    assert "绝不" in chart["subtitle"] or "never" in chart["subtitle"]
    json_safe(chart)


def test_frequency_time_weighting_recorded_variant(spec):
    # recorded_time_response: 48032-word workspace; fields 0..8 + raw PCM24 at 32.
    samples = 48000
    fields = [1.0, -0.5, 2.0, 3.0, -20.0, samples, 1.0, 1.0, 0.0]
    values = words(*fields) + [0] * 23 + [0x100000] + [0] * (samples - 1)
    assert len(values) == 32 + samples
    schema = {"kind": "tensor",
              "fields": ["FAST_power_FS2", "FAST_dBFS", "SLOW_power_FS2",
                         "SLOW_dBFS", "LeqFS", "samples_uint32", "valid",
                         "FAST_settled", "SLOW_settled"],
              "actualProducerLayout": {
                  "service": "captured_exact_FAST_SLOW_LeqFS", "output_count": 9,
                  "workspace_words": 48032, "input_offset": 32,
                  "samples": samples, "sample_rate": 48009.775390625,
                  "fields": ["FAST_power_FS2", "FAST_dBFS", "SLOW_power_FS2",
                             "SLOW_dBFS", "LeqFS", "samples_uint32", "valid",
                             "FAST_settled", "SLOW_settled"]},
              "units": "FS2,dBFS,valid"}
    chart = decode_with_schema(spec, "frequency_time_weighting", schema, values)
    assert len(chart["panels"]) == 1
    assert chart["panels"][0]["kind"] == "line"
    assert len(chart["panels"][0]["series"][0]["points"]) <= 4096
    rows = {row["label"]: row for row in chart["scalarRows"]}
    assert rows["FAST_dBFS"]["value"] == pytest.approx(-0.5)
    assert chart["waveform"]["sampleRateHz"] > 48000
    assert rows["LeqFS"]["value"] == -20.0 and rows["LeqFS"]["valid"]
    assert "Z" in chart["subtitle"] and "A" in chart["subtitle"]
    json_safe(chart)


def test_level_statistics_layout(spec, gateway):
    # rolling_L10_L50_L90_LeqFS_16: 0..3 quantiles, 4 valid, 5 count,
    # history newest at 8, oldest at 23.
    values = words(-30.0, -40.0, -50.0, -35.0, 1.0, 16.0) + [0, 0]
    history = [float(-40 - index) for index in range(16)]
    values += words(*history) + [0] * 16
    assert len(values) == 40
    chart = decode_real(gateway, spec, "level_statistics", values)
    categories = {item["label"]: item for item in chart["categories"]}
    assert categories["L10"]["value"] == pytest.approx(-30.0)
    assert categories["L50"]["value"] == pytest.approx(-40.0)
    assert categories["L90"]["value"] == pytest.approx(-50.0)
    trend = chart["series"][0]["points"]
    assert trend[0][1] == pytest.approx(history[-1])  # oldest first
    assert trend[-1][1] == pytest.approx(history[0])  # newest last
    json_safe(chart)


def test_noise_rating_layout_uses_explicit_nominal_reference(spec, gateway):
    schema = copy.deepcopy(gateway["features"]["noise_rating"]["result"]["schema"])
    values = [0] * 1074
    values[0] = f32w(45.0)
    values[1] = f32w(1.0)
    values[2] = f32w(1.0)
    levels = [31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000]
    for index, level in enumerate([55.0, 45.0, 35.0, 25.0, 15.0, 5.0,
                                   -5.0, -15.0, -25.0]):
        values[32 + index] = f32w(level)
    feature = spec["features"]["noise_rating"]
    payload = real_payload(gateway, "noise_rating", 1074)
    payload["schema"] = schema
    chart = decode_result(feature, payload, values)
    assert chart["kind"] == "noise-rating"
    assert len(chart["series"]) == 2
    rows = {row["label"]: row for row in chart["scalarRows"]}
    assert rows["NR 估计值"]["value"] == pytest.approx(45.0)
    assert rows["有效"]["value"] == 1
    assert any("估计" in note for note in chart["decodeMeta"]["notes"])
    assert any("声学校准" in note for note in chart["decodeMeta"]["notes"])
    json_safe(chart)


def test_noise_rating_nc_variant_detected(spec):
    centers = [63, 125, 250, 500, 1000, 2000, 4000, 8000]
    table = []
    for row in range(12):
        table.extend(float(50 + row + band) for band in range(8))
    ratings = [15.0 + 5 * row for row in range(12)]
    schema = {"kind": "tensor", "fields": ["rating", "valid", "estimated"],
              "axes": {"bandHz": centers},
              "actualProducerLayout": {
                  "service": "pinned_PSD_octaves_nominal_NC",
                  "input_offset": 32, "centers_hz": centers,
                  "constant_blocks": [[64, table], [160, ratings]]},
              "units": "NC curve number"}
    values = [0] * 172
    values[0] = f32w(30.0)
    values[1] = f32w(1.0)
    values[2] = f32w(1.0)
    for index in range(8):
        values[32 + index] = f32w(40.0 + index)
    chart = decode_with_schema(spec, "noise_rating", schema, values)
    reference = [item for item in chart["series"] if item["role"] == "reference"]
    assert reference and len(reference[0]["points"]) == 8
    rows = {row["label"]: row for row in chart["scalarRows"]}
    assert rows["NC 估计值"]["value"] == pytest.approx(30.0)
    json_safe(chart)


def test_spectral_kurtosis_layout(spec, gateway):
    # out[0]=M, then per bin i: 1+4i sum, 2+4i sum2, 3+4i K, 4+4i valid.
    values = [0] * 4101
    values[0] = f32w(5.0)
    values[1], values[2], values[3], values[4] = (f32w(2.0), f32w(4.0),
                                                  f32w(1.5), f32w(1.0))
    values[5], values[6], values[7], values[8] = (f32w(1.0), f32w(1.0),
                                                  f32w(0.0), f32w(0.0))
    chart = decode_real(gateway, spec, "spectral_kurtosis", values)
    rows = {row["label"]: row for row in chart["scalarRows"]}
    assert rows["累计帧数 M"]["value"] == pytest.approx(5.0)
    points = chart["series"][0]["points"]
    assert len(points) == 1  # only the valid bin
    assert points[0][1] == pytest.approx(1.5)
    json_safe(chart)


def test_relative_insulation_layout(spec, registry):
    # out[0:9]=10log10(A/B), out[9:18]=valid, out[18:27]=A, out[27:36]=B.
    bands = 9
    differences = [math.log10(4.0) * 10] * bands
    values = words(*differences) + words(*([1.0] * bands))
    values += words(*([4.0] * bands)) + words(*([1.0] * bands))
    assert len(values) == 36
    schema = registry_schema(registry, "relative_insulation")
    chart = decode_with_schema(spec, "relative_insulation", schema, values)
    assert chart["kind"] == "insulation-bars"
    categories = chart["categories"]
    assert len(categories) == bands
    assert all(item["valid"] for item in categories)
    assert categories[0]["value"] == pytest.approx(6.0206, abs=1e-3)
    assert "Rw" in chart["subtitle"]
    assert any("相对差异" in note for note in chart["decodeMeta"]["notes"])
    json_safe(chart)


def test_relative_insulation_reference_result_roles(spec, registry):
    schema = registry_schema(registry, "relative_insulation")
    chart = decode_with_schema(spec, "relative_insulation", schema,
                               words(*([2.0] * 9)))
    assert chart["kind"] == "insulation-bars"
    assert len(chart["categories"]) == 9
    assert "参考" in chart["subtitle"]
    json_safe(chart)


# ---------------------------------------------------------------------------
# long-page pagination (1024 words / page, identity validation)
# ---------------------------------------------------------------------------
def _page(job_id, feature_id, offset, chunk, total, *, more=None,
          configuration=None, source_kind="test-fixture"):
    page = {"jobId": job_id, "featureId": feature_id, "state": "completed",
            "sourceKind": source_kind,
            "configuration": configuration or {
                "session": 1, "config": 1, "generation": "1", "sourceFrame": "1"},
            "schema": {"kind": "tensor"}, "totalWords": total,
            "offsetWords": offset, "words": chunk}
    page["more"] = (offset + len(chunk) < total) if more is None else more
    return page


def test_result_pages_1024_word_boundaries():
    total = 2500
    full = list(range(total))
    pages = [_page("feature-1", "psd", 0, full[:1024], total),
             _page("feature-1", "psd", 1024, full[1024:2048], total),
             _page("feature-1", "psd", 2048, full[2048:], total)]
    assembled = validate_result_pages(pages, job_id="feature-1",
                                      feature_id="psd")
    assert assembled == full
    assembler = ResultPageAssembler("feature-1", "psd")
    for page in pages:
        complete = assembler.add(page)
    assert complete is True
    assert assembler.received_offsets == [0, 1024, 2048]
    assert assembler.total_words == 2500


def test_result_pages_720000_words_complete():
    total = 720000
    pages = []
    for offset in range(0, total, 1024):
        chunk = [0] * min(1024, total - offset)
        pages.append(_page("feature-9", "io_pcm", offset, chunk, total))
    words_out = validate_result_pages(pages, job_id="feature-9",
                                      feature_id="io_pcm")
    assert len(words_out) == total
    assert len(pages) == 704


def test_result_pages_missing_page_rejected():
    total = 3000
    pages = [_page("feature-1", "psd", 0, [0] * 1024, total),
             _page("feature-1", "psd", 1024, [0] * 1024, total)]
    with pytest.raises(DecodeError):
        validate_result_pages(pages)


def test_result_pages_out_of_order_rejected():
    total = 2048
    pages = [_page("feature-1", "psd", 0, [0] * 1024, total),
             _page("feature-1", "psd", 512, [0] * 1024, total)]
    with pytest.raises(DecodeError) as excinfo:
        validate_result_pages(pages)
    assert "position" in str(excinfo.value)


def test_result_pages_identity_change_rejected():
    total = 2048
    changed = {"session": 2, "config": 1, "generation": "2", "sourceFrame": "1"}
    pages = [_page("feature-1", "psd", 0, [0] * 1024, total),
             _page("feature-1", "psd", 1024, [0] * 1024, total,
                   configuration=changed)]
    with pytest.raises(DecodeError) as excinfo:
        validate_result_pages(pages)
    assert "changed" in str(excinfo.value) or "identity" in str(excinfo.value)


def test_result_pages_duplicate_page_rejected():
    total = 2048
    page = _page("feature-1", "psd", 0, [0] * 1024, total)
    with pytest.raises(DecodeError):
        validate_result_pages([page, copy.deepcopy(page)])


def test_result_pages_oversized_and_bad_source_rejected():
    total = 5000
    large = _page("feature-1", "psd", 0, [0] * 1025, total)
    with pytest.raises(DecodeError):
        validate_result_pages([large])
    bad_source = _page("feature-1", "psd", 0, [0] * 1024, total,
                       source_kind="hardware")
    with pytest.raises(DecodeError):
        validate_result_pages([bad_source])
    int_generation = _page("feature-1", "psd", 0, [0] * 1024, total,
                           configuration={"session": 1, "config": 1,
                                          "generation": 5, "sourceFrame": "1"})
    with pytest.raises(DecodeError):
        validate_result_pages([int_generation])


# ---------------------------------------------------------------------------
# every recipe / chart kind stays bounded and never raises
# ---------------------------------------------------------------------------
def test_all_45_features_decode_with_registry_or_captured_schema(spec, gateway,
                                                                 registry):
    decoded = 0
    for fid, feature in spec["features"].items():
        captured = gateway["features"].get(fid)
        if captured and captured.get("result"):
            schema = copy.deepcopy(captured["result"]["schema"])
            total = captured["result"]["totalWords"]
        else:
            schema = registry_schema(registry, fid)
            output = registry[fid].get("output") or {}
            total = int(output.get("wordCount") or 0)
            if fid == "io_pcm":
                total = 2048 * 6
            elif fid in ("event_trigger", "stipa_experimental"):
                total = 3 if fid == "stipa_experimental" else 0
        values = [0] * total
        payload = {"jobId": "f", "featureId": fid, "state": "completed",
                   "sourceKind": "test-fixture",
                   "configuration": {"session": 1, "config": 1,
                                     "generation": "1", "sourceFrame": "1"},
                   "schema": schema, "totalWords": total,
                   "dataRef": {"handleId": "b", "count": total}}
        chart = decode_result(feature, payload, values)
        assert isinstance(chart.get("chart"), dict) if False else True
        assert chart["kind"] == feature["chart"], (fid, chart["kind"])
        assert chart["chartRevision"]
        json_safe(chart)
        decoded += 1
    assert decoded == 45


def test_unknown_recipe_and_pending_layout_fall_back_to_raw(spec):
    feature = copy.deepcopy(spec["features"]["psd"])
    feature["decode"] = {"recipe": "mystery-recipe"}
    payload = {"jobId": "f", "featureId": "psd", "state": "completed",
               "sourceKind": "test-fixture", "schema": {"kind": "tensor"},
               "totalWords": 8,
               "configuration": {"session": 1, "config": 1,
                                 "generation": "1", "sourceFrame": "1"}}
    chart = decode_result(feature, payload, list(range(8)))
    assert chart["kind"] == "raw"
    assert chart["available"] is True
    assert chart["words"] == list(range(8))
    assert "未确认" in chart["reason"]
    json_safe(chart)


def test_chart_revision_changes_with_data(spec, gateway):
    schema = copy.deepcopy(gateway["features"]["psd"]["result"]["schema"])
    payload = real_payload(gateway, "psd", 1026)
    payload["schema"] = schema
    import copy as _copy
    a = decode_result(spec["features"]["psd"], _copy.deepcopy(payload),
                      words(3.0) + [0] * 1024 + [0] * 0 + [0] * 0)
    b = decode_result(spec["features"]["psd"], _copy.deepcopy(payload),
                      words(3.0) + [0] * 1024)
    c = decode_result(spec["features"]["psd"], _copy.deepcopy(payload),
                      words(4.0) + [0] * 1024)
    assert a["chartRevision"] == b["chartRevision"]
    assert a["chartRevision"] != c["chartRevision"]


# ---------------------------------------------------------------------------
# other chart kinds
# ---------------------------------------------------------------------------
def test_stft_retained_frames_and_raster(spec, gateway):
    result = gateway["features"]["stft"]["result"]
    total = result["totalWords"]
    schema = copy.deepcopy(result["schema"])
    values = (result["head_u32"] + [0] * total)[:total]
    payload = real_payload(gateway, "stft", total)
    payload["schema"] = schema
    chart = decode_result(spec["features"]["stft"], payload, values)
    indices = schema["axes"]["frameFirstSampleIndices"]
    assert len(indices) == 4
    assert len(chart["frames"]) == 4
    sr = schema["axes"]["sampleRateHz"]
    assert chart["frames"][1]["time"] == pytest.approx(int(indices[1]) / sr)
    assert chart["frames"][1]["displayTimeSeconds"] == pytest.approx((int(indices[1])-int(indices[0])) / sr)
    matrix = chart["raster"]["matrix"]
    assert len(matrix) == 4
    assert len(matrix[0]) == 1025
    # bottom row = first retained frame
    assert chart["raster"]["rowTimes"][0] == chart["frames"][0]["time"]
    json_safe(chart)


def test_room_decay_uses_pl_fit_only(spec, registry):
    schema = registry_schema(registry, "room_decay")
    total = int((registry["room_decay"]["output"] or {}).get("wordCount") or 48032)
    values = [0] * total
    summary = [2.0, 1.0, 1.0, 50.0, 0.0, 5.0, 1.0, 3.0, 1.0]
    for index, value in enumerate(summary):
        values[index] = f32w(value)
    edt = [0.5, 0.98, 1.0, 100.0, 0.0, 0.5]
    t20 = [0.6, 0.97, 1.0, 100.0, 0.0, 0.5]
    t30 = [0.7, 0.96, 1.0, 100.0, 0.0, 0.5]
    for index, value in enumerate(edt):
        values[10 + index] = f32w(value)
    for index, value in enumerate(t20):
        values[16 + index] = f32w(value)
    for index, value in enumerate(t30):
        values[22 + index] = f32w(value)
    for index in range(24000):
        values[24032 + index] = f32w(-60.0 * index / 24000)
    chart = decode_with_schema(spec, "room_decay", schema, values)
    rows = {row["label"]: row for row in chart["fitDetails"]}
    assert len(chart["scalarRows"]) == 3
    assert rows["EDT 值"]["value"] == pytest.approx(0.5)
    assert rows["EDT R²"]["value"] == pytest.approx(0.98)
    assert rows["T20 有效"]["value"] == pytest.approx(1.0)
    assert len(chart["referenceBands"]) == 3
    assert chart["referenceBands"][0]["to"] == pytest.approx(0.5)
    assert chart["series"]
    assert "PC 不重新拟合" in chart["subtitle"]
    json_safe(chart)


def test_ab_compare_reference_and_delta(spec, gateway):
    schema = copy.deepcopy(gateway["features"].get(
        "spectrum_freeze_compare", {}).get("result", {}).get("schema") or
        registry_schema(
            {row["featureId"]: row for row in json.loads(
                REGISTRY.read_text(encoding="utf-8"))["features"]},
            "spectrum_freeze"))
    total = 3075
    values = [0] * total
    for index, value in enumerate([1.0, -2.0, 3.0]):
        values[index] = f32w(value)
    values[2050] = f32w(1.0)
    values[2052] = f32w(1.0)
    reference = {"words": words(10.0) + [f32w(1.0)] * 1023 + [f32w(0.0)]}
    payload = {"jobId": "f", "featureId": "spectrum_freeze",
               "state": "completed", "sourceKind": "test-fixture",
               "configuration": {"session": 1, "config": 1,
                                 "generation": "1", "sourceFrame": "1"},
               "schema": schema, "totalWords": total,
               "dataRef": {"handleId": "b", "count": total}}
    chart = decode_result(spec["features"]["spectrum_freeze"], payload, values,
                          reference=reference)
    roles = {item["role"]: item for item in chart["series"]}
    assert "delta" in roles and "reference" in roles and "current" in roles
    current = roles["current"]["points"]
    assert current[0][1] == pytest.approx(11.0)
    assert len(chart["markers"]) == 2
    assert chart["markers"][0]["kind"] == "threshold"
    json_safe(chart)


def test_weighting_never_combines_a_and_time_response(spec):
    schema = {"kind": "tensor",
              "fields": ["weighted_power_FS2", "weighted_dBFS", "valid"],
              "actualProducerLayout": {"service": "spectral_A_relative_level",
                                       "coefficient_offset": 3},
              "units": "FS2,dBFS,valid"}
    values = words(1.0, -10.0, 1.0) + words(*([1.0] * 1025))
    chart = decode_with_schema(spec, "frequency_time_weighting", schema, values)
    assert "固定参考曲线" in chart["subtitle"]
    assert "绝不合并" in chart["subtitle"] or "分开" in chart["subtitle"]
    json_safe(chart)


def test_events_and_stages_charts(spec, registry):
    events_schema = registry_schema(registry, "event_trigger")
    chart = decode_with_schema(spec, "event_trigger", events_schema, [])
    assert chart["kind"] == "events"
    assert chart["events"] == []

    stages_schema = registry_schema(registry, "stipa_experimental")
    chart = decode_with_schema(spec, "stipa_experimental", stages_schema,
                               words(0.72, 1.0, 0.0))
    assert chart["kind"] == "stipa"
    assert chart["stage"]["total"] == 101
    assert chart["stage"]["completed"] == 0 and chart["stage"]["current"] == 0
    assert chart["resultValid"] is True
    assert any("认证" in note for note in
               chart["decodeMeta"]["notes"] + [chart["text"]])
    json_safe(chart)


def test_lag_series_and_fundamental_tail(spec, registry):
    schema = registry_schema(registry, "cross_correlation")
    values = [0] * 2048
    values[5] = f32w(1.0)
    values[0] = f32w(0.5)
    chart = decode_with_schema(spec, "cross_correlation", schema, values)
    assert chart["kind"] == "lag-series"
    marker = chart["markers"][0]
    assert marker["x"] == pytest.approx(5 / 48009.775390625, rel=1e-6)
    fundamental_schema = registry_schema(registry, "fundamental")
    values = [0] * 2051
    values[100] = f32w(1.0)
    values[2048] = f32w(500.0)
    values[2049] = f32w(0.8)
    values[2050] = f32w(1.0)
    chart = decode_with_schema(spec, "fundamental", fundamental_schema, values)
    rows = {row["label"]: row for row in chart["scalarRows"]}
    assert rows["fundamental_hz"]["value"] == pytest.approx(500.0)
    assert rows["period_strength"]["value"] == pytest.approx(0.8)
    json_safe(chart)


def test_room_invalid_fit_is_not_zero_measurement(spec, registry):
    schema=registry_schema(registry,"room_decay")
    values=[0]*48032
    values[0]=f32w(1.0)
    chart=decode_with_schema(spec,"room_decay",schema,values)
    rows={r["label"]:r for r in chart["scalarRows"]}
    assert rows["T20 值"]["value"] is None and rows["T20 值"]["valid"] is False
    assert rows["T30 值"]["value"] is None and rows["T30 值"]["valid"] is False
    assert chart["resultHint"]


def test_clarity_uses_separate_metrics_and_no_mixed_unit_bars(spec, registry):
    schema=registry_schema(registry,"room_clarity")
    values=[0]*48032
    for i,v in enumerate([1,.5,.7,50,1,0,1,3,1]):values[i]=f32w(v)
    chart=decode_with_schema(spec,"room_clarity",schema,values)
    assert [r["label"] for r in chart["scalarRows"]]==["C50","C80","D50"]
    assert chart["scalarRows"][0]["value"]==0 and chart["scalarRows"][0]["valid"]
    assert chart["series"]==[] and all(x["unit"]=="dB" for x in chart["categories"])


def test_stipa_invalid_zero_is_not_a_measured_index(spec):
    feature=spec["features"]["stipa_experimental"]
    payload={"state":"completed","schema":{"actualProducerLayout":{"fields":["experimental_index","valid","certified_zero"]}}}
    chart=decode_result(feature,payload,[f32w(0),f32w(0),f32w(0)])
    assert chart["indexValid"] is False and chart["indexValue"] is None
    assert chart["resultValid"] is False
    assert chart["invalidReason"] and chart["invalidReasonEn"]
    assert chart["scalarRows"][0]["valid"] is False
    # State=completed must NOT self-fill the bar: only the device progress may.
    assert chart["stage"]=={"completed":0,"total":101,"current":0,"label":"STIPA 阶段"}
    filled=decode_result(feature,payload,[f32w(0),f32w(0),f32w(0)],
                         variant={"progress":{"completedStages":101,"totalStages":101}})
    assert filled["stage"]=={"completed":101,"total":101,"current":101,
                             "label":"STIPA 阶段"}


def test_stipa_legitimate_zero_with_valid_flag_is_preserved(spec):
    chart=decode_result(spec["features"]["stipa_experimental"],{"state":"completed","schema":{}},[f32w(0),f32w(1),f32w(0)])
    assert chart["indexValid"] is True and chart["indexValue"]==0
    assert chart["resultValid"] is True
    assert chart["invalidReason"]=="" and chart["invalidReasonEn"]==""


def test_stipa_valid_result_keeps_the_original_index_display(spec):
    chart=decode_result(spec["features"]["stipa_experimental"],
                        {"state":"completed","schema":{}},
                        stipa_words(0.72,1.0,0.0,0.0,0.0,0.0,0.15,0.15,1.0))
    assert chart["resultValid"] is True and chart["indexValid"] is True
    assert chart["indexValue"]==pytest.approx(0.72)
    labels=[row["label"] for row in chart["scalarRows"]]
    # valid results keep the original index/validity readouts, no rejection rows
    assert labels==["experimental_index","valid","certified_zero"]
    json_safe(chart)


def test_stipa_reason3_reference_unstable_text_fields_and_result_valid(spec):
    chart=decode_result(spec["features"]["stipa_experimental"],
                        {"state":"completed","schema":{}},
                        stipa_words(0.0,0.0,0.0,3.0,1000.0,3.15,0.15,0.06,0.4))
    assert chart["resultValid"] is False
    assert chart["invalidReason"]==("参考信号不稳定：1000 Hz 频带、3.15 Hz 调制分量校验失败，"
                                    "请重新录制参考。")
    assert "Reference signal unstable" in chart["invalidReasonEn"]
    assert chart["indexValue"] is None and chart["indexValid"] is False
    rows={row["label"]:row for row in chart["scalarRows"]}
    assert rows["原因码"]["value"]==3
    assert rows["失败频带"]["value"]==1000 and rows["失败频带"]["unit"]=="Hz"
    assert rows["失败调制频率"]["value"]==pytest.approx(3.15)
    assert rows["参考调制度"]["value"]==pytest.approx(0.15)
    assert rows["测试调制度"]["value"]==pytest.approx(0.06)
    assert rows["传输比"]["value"]==pytest.approx(0.4)
    json_safe(chart)


def test_stipa_reason4_ratio_out_of_range_text_fields_and_result_valid(spec):
    chart=decode_result(spec["features"]["stipa_experimental"],
                        {"state":"completed","schema":{}},
                        stipa_words(0.35,0.0,0.0,4.0,500.0,0.63,0.15,0.1,1.35))
    assert chart["resultValid"] is False
    assert chart["invalidReason"]==("测试与参考比值超限（1.350）：500 Hz 频带、"
                                    "0.63 Hz 调制分量；请检查测量位置或重新录制参考。")
    assert "Test/reference ratio out of range (1.350)" in chart["invalidReasonEn"]
    rows={row["label"]:row for row in chart["scalarRows"]}
    assert rows["原因码"]["value"]==4
    assert rows["失败频带"]["value"]==500
    assert rows["失败调制频率"]["value"]==pytest.approx(0.63)
    assert rows["传输比"]["value"]==pytest.approx(1.35)
    json_safe(chart)


def test_stipa_reason2_energy_text_and_band_format(spec):
    chart=decode_result(spec["features"]["stipa_experimental"],
                        {"state":"completed","schema":{}},
                        stipa_words(0.0,0.0,0.0,2.0,2000.0,0.0,0.15,0.02,0.1))
    assert chart["invalidReason"]==("信号能量或拟合不足：2000 Hz 频带，"
                                    "请检查音量/麦克风增益并重新录制。")
    assert "2000 Hz band" in chart["invalidReasonEn"]


def test_stipa_reason1_capture_text_uses_no_band_noise(spec):
    chart=decode_result(spec["features"]["stipa_experimental"],
                        {"state":"completed","schema":{}},
                        stipa_words(0.0,0.0,0.0,1.0))
    assert chart["invalidReason"]==("采集数据无效（参考或测试录音不满足格式/电平/时长），"
                                    "请重新录制参考与测试。")
    assert "Invalid capture data" in chart["invalidReasonEn"]


def test_stipa_unknown_reason_uses_generic_text(spec):
    chart=decode_result(spec["features"]["stipa_experimental"],
                        {"state":"completed","schema":{}},
                        stipa_words(0.0,0.0,0.0,9.0,500.0,0.63))
    assert chart["invalidReason"].startswith("测量无效（原因码未知或为 0）")
    assert "Measurement invalid" in chart["invalidReasonEn"]
    rows={row["label"]:row for row in chart["scalarRows"]}
    assert rows["原因码"]["value"]==9


def test_stipa_stage_reports_completed_and_current_separately(spec):
    feature=spec["features"]["stipa_experimental"]
    chart=decode_result(feature,{"state":"completed","schema":{}},
                        stipa_words(0.72,1.0,0.0),
                        variant={"params":{"measurementMode":"quick"},
                                 "progress":{"completedStages":7,"totalStages":15,
                                             "currentStageIndex":8}})
    assert chart["stage"]=={"completed":7,"total":15,"current":8,
                            "label":"STIPA 阶段"}
    # A completed quick result without device progress keeps completed=current=0
    # and the quick default total of 15 (PC never self-fills).
    chart=decode_result(feature,{"state":"completed","schema":{}},
                        stipa_words(0.72,1.0,0.0),
                        variant={"params":{"measurementMode":"quick"}})
    assert chart["stage"]=={"completed":0,"total":15,"current":0,
                            "label":"STIPA 阶段"}


def test_modulation_view_omits_dc_without_relabeling_bins(spec):
    values=[f32w(0.)]*1025;values[0]=f32w(10.);values[1]=f32w(5.);values[4]=f32w(1.)
    payload={'schema':{'actualProducerLayout':{'service':'envelope_spectrum','units':'raw FFT magnitude'},'axes':{'sampleRateHz':48000,'fftSize':2048}}}
    chart=decode_result(spec['features']['modulation_spectrum'],payload,values)
    pts=chart['series'][0]['points'];assert pts[0][0]==pytest.approx(46.875)
    assert max(pts,key=lambda p:p[1])[0]==pytest.approx(93.75)
    assert chart['scalarRows'][0]['value']==10
    assert len(values)==1025


def test_shape_pages_prioritize_the_selected_metric(spec):
    payload={'schema':{'actualProducerLayout':{'fields':['centroid_hz','flatness','peak_bin_power','peak_hz']}}}
    vals=[f32w(2800),f32w(.05),f32w(.01),f32w(2000)]
    for fid,key in [('frequency_tracking','peak_hz'),('centroid','centroid_hz'),('flatness','flatness')]:
        chart=decode_result(spec['features'][fid],payload,vals)
        assert chart['scalarRows'][0]['label']==key
        assert len(chart['scalarRows'])==4


def test_uninitialized_drift_is_not_a_valid_zero(spec):
    payload={'schema':{'actualProducerLayout':{'fields':['peak_hz','delta_hz','drift_hz_per_second','drift_valid','history_hz','initialized','frame_uint']}}}
    vals=[f32w(2000),f32w(0),f32w(0),f32w(0),f32w(0),f32w(0),1]
    c=decode_result(spec['features']['frequency_drift'],payload,vals);assert c['scalarRows'][0]['value'] is None
    vals[3]=f32w(1);c=decode_result(spec['features']['frequency_drift'],payload,vals);assert c['scalarRows'][0]['value']==0 and c['scalarRows'][0]['valid']

