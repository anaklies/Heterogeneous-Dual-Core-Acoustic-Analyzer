"""Result-word decode rules (protocol 3) and service snapshot publish-header rules."""
from __future__ import annotations

import hashlib
import struct

import pytest

from sixmic_backend.constants import (
    CANDIDATE_SAMPLE_RATE_BITS, CANDIDATE_SAMPLE_RATE_FLOAT32_HZ, RESULT_WORD_COUNT,
    SERVICE_HEADER_MAGIC,
)
from sixmic_backend.errors import BackendError
from sixmic_backend.protocol.golden import GoldenSuite
from sixmic_backend.protocol.messages import (
    ServiceHeader, build_result_schema, decode_result_words, parse_service_snapshot,
    unpack_result_words, validate_stream_schema,
)

BIG = 9007199254740993


def golden_words(protocol_root) -> tuple[int, ...]:
    suite = GoldenSuite(protocol_root)
    frames = __import__("sixmic_backend.protocol.framing", fromlist=["FrameDecoder"]) \
        .FrameDecoder().feed(suite.read("binary/result_words32.bin"))
    return unpack_result_words(frames[0][1])


def test_result_words_decode(protocol_root):
    words = golden_words(protocol_root)
    assert len(words) == RESULT_WORD_COUNT and words[0] == 3
    decoded = decode_result_words(words)
    assert decoded["sampleIndex"] == BIG
    assert decoded["frameId"] == 1234 and decoded["configVersion"] == 10
    assert abs(decoded["sampleRateHz"] - CANDIDATE_SAMPLE_RATE_FLOAT32_HZ) < 1e-9
    assert decoded["valid"] == {"temperature": True, "pressure": True,
                                "pose": True, "soundSpeedModel": True}
    assert decoded["humidityRaw"] == 0x4A3C  # raw SHT code, NOT a percentage
    assert abs(decoded["soundSpeedMps"] - 343.0) < 1e-5
    assert decoded["poseRaw"]["imuScaleStatus"] == "unverified"
    assert decoded["faultDecoded"]["configRejected"] is False


def test_humidity_never_converted_to_percent(protocol_root):
    decoded = decode_result_words(golden_words(protocol_root))
    assert decoded["humidityRaw"] is not None
    assert not any("percent" in key.lower() for key in decoded)


def test_invalid_result_payload(protocol_root):
    with pytest.raises(BackendError):
        unpack_result_words(b"\x00" * 4)
    words = list(golden_words(protocol_root))
    words[0] = 2
    with pytest.raises(BackendError):
        unpack_result_words(struct.pack("<32I", *words))


def test_result_schema_validates():
    schema = build_result_schema(source_kind="test-fixture", device_id="dev",
                                 connection_epoch=3, simulated=True,
                                 sample_rate_hz=48009.775390625)
    schema["streamId"] = 1
    import json
    validated = validate_stream_schema(json.dumps(schema).encode())
    assert validated["streamType"] == "resultWords32"
    assert len(validated["wordMap"]) == 32
    with pytest.raises(BackendError):
        validate_stream_schema(json.dumps({**schema,
                                          "sourceKind": "pl-live"}).encode())


def _service_payload(session=1, config=10, generation=3, done=1, error=0,
                     length=3, commit=42) -> bytes:
    header = ServiceHeader(commit_sequence=commit, session=session, config=config,
                           generation=generation, program_version=2, source_frame=7,
                           sample_index_low=BIG & 0xFFFFFFFF,
                           sample_index_high=BIG >> 32, slot=0, length=length,
                           descriptor=600000, error=error, pc=1, done=done)
    body = struct.pack("<3I", 0x3F800000, 0x40000000, 0x00000000)
    return struct.pack("<16I", *header.to_words()) + body


def test_service_header_usable_rules():
    header, body = parse_service_snapshot(_service_payload())
    assert header.magic == SERVICE_HEADER_MAGIC
    assert header.sample_index == BIG
    assert header.usable(session=1, config=10, generation=3)
    assert not header.usable(session=2)
    assert not header.usable(config=11)
    assert not header.usable(generation=4)
    assert len(body) == 12
    _, body_bad = parse_service_snapshot(_service_payload(done=0))
    with pytest.raises(BackendError):
        header_bad, _ = parse_service_snapshot(_service_payload(error=5))
        if not header_bad.usable():
            raise BackendError("bad_state", {"reason": "service-error"})


def test_service_header_consistency_compare():
    first, _ = parse_service_snapshot(_service_payload(commit=42))
    second, _ = parse_service_snapshot(_service_payload(commit=43))
    assert first.consistent_with(first)
    assert not first.consistent_with(second)


def test_service_length_exceeds_payload():
    with pytest.raises(BackendError):
        parse_service_snapshot(_service_payload(length=99))


def test_pcm_schema_rejects_missing_fields():
    import json
    with pytest.raises(BackendError):
        validate_stream_schema(json.dumps({"streamType": "pcmRecord32"}).encode())
