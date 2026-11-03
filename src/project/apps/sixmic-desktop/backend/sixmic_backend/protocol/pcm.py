"""Raw PCM record codec: 32 bytes, six sign-extended 24-bit LE int32 + u64 index."""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterable

from ..constants import PCM_CHANNELS, PCM_RECORD_BYTES, PCM_SAMPLE_INDEX_OFFSET
from ..errors import BackendError

MIN_SAMPLE = -(1 << 23)
MAX_SAMPLE = (1 << 23) - 1


@dataclass(frozen=True)
class PcmRecord:
    samples: tuple[int, int, int, int, int, int]
    sample_index: int

    def __post_init__(self) -> None:
        if len(self.samples) != PCM_CHANNELS:
            raise BackendError("bad_args", {"field": "samples", "reason": "six-channels-required"})
        for channel, value in enumerate(self.samples):
            if isinstance(value, bool) or not isinstance(value, int):
                raise BackendError("bad_args", {"field": f"channel{channel}", "reason": "int-required"})
            if not MIN_SAMPLE <= value <= MAX_SAMPLE:
                raise BackendError("bad_args", {"field": f"channel{channel}",
                                                "reason": "24-bit-range", "value": value})
        if isinstance(self.sample_index, bool) or not isinstance(self.sample_index, int):
            raise BackendError("bad_args", {"field": "sampleIndex", "reason": "int-required"})
        if not 0 <= self.sample_index < (1 << 64):
            raise BackendError("bad_args", {"field": "sampleIndex", "reason": "u64-range"})

    def to_bytes(self) -> bytes:
        return encode_record(self.samples, self.sample_index)


def sign_extend_24(raw: int) -> int:
    """Sign-extend a 24-bit unsigned pattern to a Python int."""
    raw &= 0xFFFFFF
    return raw - 0x1000000 if raw & 0x800000 else raw


def encode_record(samples: Iterable[int], sample_index: int) -> bytes:
    values = tuple(samples)
    record = PcmRecord(values, sample_index)  # validates
    out = bytearray(PCM_RECORD_BYTES)
    for channel, value in enumerate(record.samples):
        pattern = value & 0xFFFFFF
        if pattern & 0x800000:  # sign-extend bit23 into bits 31:24 on the wire
            pattern |= 0xFF000000
        struct.pack_into("<I", out, 4 * channel, pattern)
    struct.pack_into("<Q", out, PCM_SAMPLE_INDEX_OFFSET, record.sample_index)
    return bytes(out)


def decode_record(record: bytes) -> PcmRecord:
    if len(record) != PCM_RECORD_BYTES:
        raise BackendError("file_corrupt", {"reason": "record-size",
                                            "bytes": len(record)})
    samples = []
    for channel in range(PCM_CHANNELS):
        pattern = struct.unpack_from("<I", record, 4 * channel)[0]
        raw = pattern & 0xFFFFFF
        expected = raw | 0xFF000000 if raw & 0x800000 else raw
        if pattern != expected:
            raise BackendError("file_corrupt", {"reason": "sign-extension-bits-invalid",
                                                "channel": channel,
                                                "pattern": f"0x{pattern:08X}"})
        samples.append(sign_extend_24(raw))
    index = struct.unpack_from("<Q", record, PCM_SAMPLE_INDEX_OFFSET)[0]
    return PcmRecord(tuple(samples), index)


def decode_records(payload: bytes) -> list[PcmRecord]:
    if not payload or len(payload) % PCM_RECORD_BYTES:
        raise BackendError("bad_args", {"field": "pcmPayload", "reason": "not-multiple-of-32",
                                        "bytes": len(payload)})
    return [decode_record(payload[offset:offset + PCM_RECORD_BYTES])
            for offset in range(0, len(payload), PCM_RECORD_BYTES)]


def encode_records(records: Iterable[PcmRecord]) -> bytes:
    return b"".join(record.to_bytes() for record in records)


def sample_index_span(records: list[PcmRecord]) -> tuple[int, int]:
    if not records:
        raise BackendError("bad_args", {"field": "records", "reason": "empty"})
    return records[0].sample_index, records[-1].sample_index


def check_contiguous(records: list[PcmRecord], expected_first: int | None = None) -> list[dict[str, int]]:
    """Return detected discontinuities: [{at, expected, actual}]."""
    problems: list[dict[str, int]] = []
    if not records:
        return problems
    if expected_first is not None and records[0].sample_index != expected_first:
        problems.append({"at": 0, "expected": expected_first,
                         "actual": records[0].sample_index})
    previous = records[0].sample_index
    for position, record in enumerate(records[1:], start=1):
        expected = previous + 1
        if record.sample_index != expected:
            problems.append({"at": position, "expected": expected,
                             "actual": record.sample_index})
        previous = record.sample_index
    return problems


def chunk_records(payload: bytes, max_records: int) -> list[bytes]:
    if max_records < 1:
        raise BackendError("bad_args", {"field": "maxRecords"})
    stride = max_records * PCM_RECORD_BYTES
    return [payload[offset:offset + stride] for offset in range(0, len(payload), stride)]
