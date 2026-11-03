"""SMC1 event container: header CRC, record integrity, tamper rejection, hashing."""
from __future__ import annotations

import hashlib

import pytest

from sixmic_backend.errors import BackendError
from sixmic_backend.protocol.event_file import (
    build_event_container, parse_event_container,
)
from sixmic_backend.protocol.pcm import PcmRecord, encode_record

BIG = 9007199254740993


def _container(**overrides) -> bytes:
    records = b"".join(encode_record([i, -i, 0, 1, -1, 2], BIG + i)
                       for i in range(4))
    kwargs = dict(event_id=7, flags=0, clip_reason=5,
                  first_sample_index=BIG, last_sample_index=BIG + 3,
                  sample_rate_hz=48009.775390625, records=records)
    kwargs.update(overrides)
    return build_event_container(**kwargs)


def test_roundtrip_and_hash():
    data = _container()
    parsed = parse_event_container(data)
    assert parsed.header.record_count == 4
    assert parsed.header.sample_rate_hz == pytest.approx(48009.7734375, abs=1e-6)
    assert parsed.sha256 == hashlib.sha256(data).hexdigest()
    assert len(parsed.records) == 4 * 32


def test_header_crc_tamper_rejected():
    data = bytearray(_container())
    data[60] ^= 0xFF
    with pytest.raises(BackendError):
        parse_event_container(bytes(data))


def test_record_hash_and_index_mismatch():
    records = b"".join(encode_record([0] * 6, BIG + 100 + i) for i in range(2))
    data = _container(records=records, first_sample_index=BIG,
                      last_sample_index=BIG + 1)
    with pytest.raises(BackendError):
        parse_event_container(data)


def test_flag_decoding():
    data = _container(flags=(1 | 2 | 4))
    parsed = parse_event_container(data)
    assert parsed.header.incomplete and parsed.header.lost_events
    assert parsed.header.summary_stale
    assert not parsed.header.env_invalid and not parsed.header.pose_invalid


def test_truncated_container_rejected():
    data = _container()
    with pytest.raises(BackendError):
        parse_event_container(data[:-4])
