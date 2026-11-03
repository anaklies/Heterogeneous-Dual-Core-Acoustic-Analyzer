"""SMC1 event file container: header, record stream, hash and manifest fields."""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..constants import (
    EVENT_CONTAINER_HEADER_BYTES, EVENT_CONTAINER_MAGIC, EVENT_CONTAINER_VERSION,
    EVENT_FLAG_ENV_INVALID, EVENT_FLAG_INCOMPLETE, EVENT_FLAG_LOST_EVENTS,
    EVENT_FLAG_POSE_INVALID, EVENT_FLAG_SUMMARY_STALE, PCM_RECORD_BYTES,
)
from ..errors import BackendError
from .framing import crc32
from .pcm import decode_record


@dataclass(frozen=True)
class EventContainerHeader:
    record_bytes: int = PCM_RECORD_BYTES
    channels: int = 6
    flags: int = 0
    clip_reason: int = 0
    event_id: int = 0
    first_sample_index: int = 0
    last_sample_index: int = 0
    record_count: int = 0
    sample_rate_bits: int = 0

    @property
    def sample_rate_hz(self) -> float:
        return struct.unpack("<f", struct.pack("<I", self.sample_rate_bits & 0xFFFFFFFF))[0]

    @property
    def incomplete(self) -> bool:
        return bool(self.flags & EVENT_FLAG_INCOMPLETE)

    @property
    def lost_events(self) -> bool:
        return bool(self.flags & EVENT_FLAG_LOST_EVENTS)

    @property
    def summary_stale(self) -> bool:
        return bool(self.flags & EVENT_FLAG_SUMMARY_STALE)

    @property
    def env_invalid(self) -> bool:
        return bool(self.flags & EVENT_FLAG_ENV_INVALID)

    @property
    def pose_invalid(self) -> bool:
        return bool(self.flags & EVENT_FLAG_POSE_INVALID)

    def to_bytes(self) -> bytes:
        header = bytearray(EVENT_CONTAINER_HEADER_BYTES)
        header[0:4] = EVENT_CONTAINER_MAGIC
        struct.pack_into("<HH", header, 4, EVENT_CONTAINER_VERSION, EVENT_CONTAINER_HEADER_BYTES)
        struct.pack_into("<II", header, 8, self.record_bytes, self.channels)
        struct.pack_into("<II", header, 16, self.flags, self.clip_reason)
        struct.pack_into("<QQQQ", header, 24, self.event_id, self.first_sample_index,
                         self.last_sample_index, self.record_count)
        struct.pack_into("<I", header, 56, self.sample_rate_bits)
        struct.pack_into("<I", header, 60, crc32(bytes(header[:56])))
        return bytes(header)


@dataclass(frozen=True)
class EventContainer:
    header: EventContainerHeader
    records: bytes
    sha256: str

    @property
    def total_bytes(self) -> int:
        return EVENT_CONTAINER_HEADER_BYTES + len(self.records)


def build_event_container(*, event_id: int, flags: int, clip_reason: int,
                          first_sample_index: int, last_sample_index: int,
                          sample_rate_hz: float, records: bytes) -> bytes:
    if len(records) % PCM_RECORD_BYTES:
        raise BackendError("bad_args", {"field": "records", "reason": "not-32-byte-records"})
    count = len(records) // PCM_RECORD_BYTES
    bits = struct.unpack("<I", struct.pack("<f", float(sample_rate_hz)))[0]
    header = EventContainerHeader(record_bytes=PCM_RECORD_BYTES, channels=6,
                                  flags=flags, clip_reason=clip_reason,
                                  event_id=event_id,
                                  first_sample_index=first_sample_index,
                                  last_sample_index=last_sample_index,
                                  record_count=count, sample_rate_bits=bits)
    return header.to_bytes() + records


def parse_event_container(data: bytes, *, verify_records: bool = True) -> EventContainer:
    if len(data) < EVENT_CONTAINER_HEADER_BYTES:
        raise BackendError("file_corrupt", {"reason": "event-container-short"})
    if data[0:4] != EVENT_CONTAINER_MAGIC:
        raise BackendError("file_corrupt", {"reason": "event-container-magic"})
    version, header_bytes = struct.unpack_from("<HH", data, 4)
    if version != EVENT_CONTAINER_VERSION or header_bytes != EVENT_CONTAINER_HEADER_BYTES:
        raise BackendError("file_corrupt", {"reason": "event-container-version"})
    record_bytes, channels = struct.unpack_from("<II", data, 8)
    if record_bytes != PCM_RECORD_BYTES or channels != 6:
        raise BackendError("file_corrupt", {"reason": "event-container-format"})
    flags, clip_reason = struct.unpack_from("<II", data, 16)
    event_id, first_index, last_index, count = struct.unpack_from("<QQQQ", data, 24)
    sample_rate_bits = struct.unpack_from("<I", data, 56)[0]
    header_crc = struct.unpack_from("<I", data, 60)[0]
    if crc32(data[:56]) != header_crc:
        raise BackendError("file_corrupt", {"reason": "event-header-crc"})
    records = data[EVENT_CONTAINER_HEADER_BYTES:]
    if len(records) != count * PCM_RECORD_BYTES:
        raise BackendError("file_corrupt", {"reason": "event-record-count",
                                            "declared": count,
                                            "actual": len(records) // PCM_RECORD_BYTES})
    if verify_records and count:
        first = decode_record(records[:PCM_RECORD_BYTES])
        last = decode_record(records[-PCM_RECORD_BYTES:])
        if first.sample_index != first_index or last.sample_index != last_index:
            raise BackendError("file_corrupt", {"reason": "event-sample-index-mismatch"})
    header = EventContainerHeader(record_bytes=record_bytes, channels=channels,
                                  flags=flags, clip_reason=clip_reason,
                                  event_id=event_id,
                                  first_sample_index=first_index,
                                  last_sample_index=last_index,
                                  record_count=count,
                                  sample_rate_bits=sample_rate_bits)
    return EventContainer(header=header, records=records,
                          sha256=hashlib.sha256(data).hexdigest())


def write_event_container(path: str | Path, data: bytes) -> dict[str, Any]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    container = parse_event_container(data)
    return {"path": str(path), "bytes": len(data), "sha256": container.sha256,
            "recordCount": container.header.record_count,
            "firstSampleIndex": str(container.header.first_sample_index),
            "lastSampleIndex": str(container.header.last_sample_index),
            "sampleRateHz": container.header.sample_rate_hz}
