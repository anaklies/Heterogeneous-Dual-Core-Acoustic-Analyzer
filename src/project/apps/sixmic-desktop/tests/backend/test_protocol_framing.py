"""SMA1 binary framing: explicit layout, CRC, golden wire equality, bounds."""
from __future__ import annotations

import struct

import pytest

from sixmic_backend.constants import (
    FLAG_CRC32_VALID, FLAG_FIRST_CHUNK, FLAG_LAST_CHUNK, FLAG_SAMPLE_INDEX_VALID,
    MSG_BYE, MSG_EVENT_FILE_CHUNK, MSG_HEARTBEAT, MSG_HELLO, MSG_HELLO_ACK,
    MSG_PCM_RECORD32, MSG_RESULT_WORDS32, MSG_SERVICE_SNAPSHOT, MSG_STREAM_GAP,
    MSG_STREAM_SCHEMA, PROTOCOL_VERSION,
)
from sixmic_backend.errors import BackendError
from sixmic_backend.protocol.framing import (
    FrameDecoder, SmaHeader, build_frame, crc32, encode_frame,
)
from sixmic_backend.protocol.golden import GoldenSuite


def test_message_type_numbering_is_frozen():
    assert (MSG_HELLO, MSG_HELLO_ACK, MSG_STREAM_SCHEMA, MSG_PCM_RECORD32,
            MSG_RESULT_WORDS32, MSG_SERVICE_SNAPSHOT, MSG_EVENT_FILE_CHUNK,
            MSG_STREAM_GAP, MSG_HEARTBEAT, MSG_BYE) == (
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
    assert PROTOCOL_VERSION == 1


def test_header_layout_explicit_offsets():
    header = SmaHeader(message_type=MSG_RESULT_WORDS32, payload_bytes=128,
                       stream_id=2, sequence=5, connection_epoch=3,
                       first_sample_index=9007199254740993,
                       device_monotonic_ns=0, frame_id=1234, config_version=10,
                       payload_crc32=0x11223344, flags=FLAG_SAMPLE_INDEX_VALID)
    raw = header.pack()
    assert len(raw) == 64
    assert raw[0:4] == b"SMA1"
    assert struct.unpack_from("<H", raw, 4)[0] == 1
    assert struct.unpack_from("<H", raw, 6)[0] == 64
    assert struct.unpack_from("<H", raw, 8)[0] == MSG_RESULT_WORDS32
    assert struct.unpack_from("<H", raw, 10)[0] == FLAG_SAMPLE_INDEX_VALID
    assert struct.unpack_from("<I", raw, 12)[0] == 128
    assert struct.unpack_from("<I", raw, 16)[0] == 2
    assert struct.unpack_from("<I", raw, 20)[0] == 5
    assert struct.unpack_from("<Q", raw, 24)[0] == 3
    assert struct.unpack_from("<Q", raw, 32)[0] == 9007199254740993
    assert struct.unpack_from("<Q", raw, 40)[0] == 0
    assert struct.unpack_from("<I", raw, 48)[0] == 1234
    assert struct.unpack_from("<I", raw, 52)[0] == 10
    assert struct.unpack_from("<I", raw, 56)[0] == 0x11223344
    assert struct.unpack_from("<I", raw, 60)[0] == 0


def test_crc32_ieee_vectors():
    assert crc32(b"") == 0x00000000
    assert crc32(b"123456789") == 0xCBF43926
    assert crc32(b"sixmic-analysis") == crc32(b"sixmic-analysis")


def test_frame_roundtrip_and_crc_detection():
    payload = struct.pack("<32I", *([3] + [0] * 31))
    frame = build_frame(MSG_RESULT_WORDS32, payload, stream_id=2, sequence=7,
                        connection_epoch=3, first_sample_index=9007199254740993)
    header, body = FrameDecoder().feed(frame)[0]
    assert header.sequence == 7 and header.first_sample_index == 9007199254740993
    assert body == payload
    corrupted = bytearray(frame)
    struct.pack_into("<I", corrupted, 56, crc32(payload) ^ 1)
    with pytest.raises(BackendError) as info:
        FrameDecoder().feed(bytes(corrupted))
    assert info.value.code == "crc_mismatch"


def test_bad_magic_header_bytes_reserved_and_limits():
    good = build_frame(MSG_HEARTBEAT, b"", connection_epoch=3)
    for field, value, error in (
            (0, b"XXXX", "protocol_mismatch"),
            (6, 32, "bad_args"),
            (60, 1, "bad_args"),
            (4, 2, "unsupported_version")):
        corrupted = bytearray(good)
        if field == 0:
            corrupted[0:4] = value
        elif field == 6:
            struct.pack_into("<H", corrupted, 6, value)
        elif field == 60:
            struct.pack_into("<I", corrupted, 60, value)
        elif field == 4:
            struct.pack_into("<H", corrupted, 4, value)
        with pytest.raises(BackendError) as info:
            FrameDecoder().feed(bytes(corrupted))
        assert info.value.code == error
    oversize = bytearray(good)
    struct.pack_into("<I", oversize, 12, 2 * 1024 * 1024)
    with pytest.raises(BackendError):
        FrameDecoder(negotiated_max_payload=1048576).feed(bytes(oversize))


def test_unknown_message_type_is_bounded_skip():
    frame = build_frame(0x1234, b"payload", stream_id=9, sequence=1, connection_epoch=3)
    frames = FrameDecoder().feed(frame)
    assert len(frames) == 1 and frames[0][0].message_type == 0x1234


def test_golden_frames_match_production_encoder(protocol_root):
    suite = GoldenSuite(protocol_root)
    result = suite.verify()
    assert result["failures"] == []
    assert result["checked"] >= 20
    # The production encoder must reproduce the golden HELLO_ACK bytes exactly.
    payload = suite.read("binary/hello_ack_frame.bin")[64:]
    golden = suite.read("binary/hello_ack_frame.bin")
    header = SmaHeader.unpack(golden[:64])
    rebuilt = encode_frame(header, payload)
    assert rebuilt == golden
    # And every binary golden file decodes with bounded payloads.
    for name in suite.entries():
        if name.startswith("binary/"):
            frames = FrameDecoder().feed(suite.read(name))
            assert frames, name
