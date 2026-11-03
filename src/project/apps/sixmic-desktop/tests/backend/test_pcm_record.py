"""Raw PCM 32-byte record: sign extension, channel order, sampleIndex, WAV/24-bit."""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sixmic_backend.constants import PCM_RECORD_BYTES
from sixmic_backend.errors import BackendError
from sixmic_backend.model.audio import read_24bit_wav, write_wav6_24bit
from sixmic_backend.protocol.pcm import (
    MAX_SAMPLE, MIN_SAMPLE, PcmRecord, check_contiguous, decode_record,
    decode_records, encode_record, encode_records, sign_extend_24,
)

BIG = 9007199254740993


def test_record_size_and_layout():
    payload = encode_record([1, -1, 0, 8388607, -8388608, 42], BIG)
    assert len(payload) == PCM_RECORD_BYTES
    assert payload[:4] == b"\x01\x00\x00\x00"
    assert payload[4:8] == b"\xff\xff\xff\xff"      # -1 sign-extended 24-bit
    assert payload[8:12] == b"\x00\x00\x00\x00"
    assert payload[12:16] == b"\xff\xff\x7f\x00"    # +8388607
    assert payload[16:20] == b"\x00\x00\x80\xff"    # -8388608 sign-extended
    assert struct.unpack_from("<Q", payload, 24)[0] == BIG


def test_sign_extension_and_extremes():
    assert sign_extend_24(0x7FFFFF) == 8388607
    assert sign_extend_24(0x800000) == -8388608
    assert sign_extend_24(0xFFFFFF) == -1
    for value in (MIN_SAMPLE, MAX_SAMPLE, -1, 0, 1):
        record = decode_record(encode_record([value] * 6, 5))
        assert record.samples == (value,) * 6


def test_channel_order_preserved():
    record = PcmRecord((1, 2, 3, 4, 5, 6), 7)
    decoded = decode_record(record.to_bytes())
    assert decoded.samples == (1, 2, 3, 4, 5, 6)


def test_invalid_pattern_rejected():
    payload = bytearray(encode_record([0] * 6, 1))
    payload[3] = 0x7F  # invalid sign-extension byte (bit23 clear -> bits31:24 must be 0)
    with pytest.raises(BackendError):
        decode_record(bytes(payload))


def test_sample_index_contiguity_and_gap_detection():
    records = [PcmRecord((0,) * 6, BIG + offset) for offset in range(4)]
    assert check_contiguous(records) == []
    broken = records[:2] + [PcmRecord((0,) * 6, BIG + 9)]
    problems = check_contiguous(broken)
    assert problems and problems[0]["expected"] == BIG + 2
    assert decode_records(encode_records(records))[0].sample_index == BIG


def test_bad_payload_length():
    with pytest.raises(BackendError):
        decode_records(b"x" * 31)
    with pytest.raises(BackendError):
        decode_records(b"")


def test_wav24_roundtrip(tmp_path: Path):
    records = [PcmRecord((index, -index, 0, 8388607, -8388608, index * 2),
                         1000 + index) for index in range(1, 6)]
    payload = encode_records(records)
    wav_info = write_wav6_24bit(tmp_path / "audio.wav", payload,
                                real_sample_rate_hz=48009.775390625)
    assert wav_info["integerRateHz"] == 48010
    assert abs(wav_info["rateRoundingErrorHz"] - (48010 - 48009.775390625)) < 1e-9
    decoded_payload, read_info = read_24bit_wav(wav_info["path"])
    assert read_info["frames"] == 5
    # WAV is 24-bit audio: sample values must match exactly; the 64-bit sample
    # index lives in the raw 32-byte record stream / recording manifest.
    assert [record.samples for record in decode_records(decoded_payload)] == \
        [record.samples for record in records]
    assert [record.sample_index for record in decode_records(payload)] == \
        [1001, 1002, 1003, 1004, 1005]
