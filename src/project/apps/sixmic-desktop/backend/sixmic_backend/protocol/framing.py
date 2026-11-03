"""SMA1 binary framing: explicit 64-byte little-endian header + CRC32.

All multi-byte fields are encoded/decoded field by field; the code never memory
maps a compiler struct onto the wire.
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field

from ..constants import (
    DEFAULT_MAX_BINARY_PAYLOAD, FLAG_CRC32_VALID, FLAGS_KNOWN_MASK,
    MESSAGE_NAMES, MSG_BYE, MSG_HEARTBEAT, PROTOCOL_VERSION,
)
from ..errors import BackendError

MAGIC = b"SMA1"
HEADER_BYTES = 64
MAX_PAYLOAD_CEILING = 16777216


def crc32(payload: bytes) -> int:
    """IEEE reflected CRC-32 (poly 0xEDB88320, init/xorout 0xFFFFFFFF)."""
    return zlib.crc32(payload) & 0xFFFFFFFF


@dataclass(frozen=True)
class SmaHeader:
    protocol_version: int = PROTOCOL_VERSION
    header_bytes: int = HEADER_BYTES
    message_type: int = 0
    flags: int = 0
    payload_bytes: int = 0
    stream_id: int = 0
    sequence: int = 0
    connection_epoch: int = 0
    first_sample_index: int = 0
    device_monotonic_ns: int = 0
    frame_id: int = 0
    config_version: int = 0
    payload_crc32: int = 0

    @property
    def message_name(self) -> str:
        return MESSAGE_NAMES.get(self.message_type, f"0x{self.message_type:04X}")

    @property
    def crc_valid_flag(self) -> bool:
        return bool(self.flags & FLAG_CRC32_VALID)

    @property
    def gap_before(self) -> bool:
        return bool(self.flags & (1 << 1))

    @property
    def first_chunk(self) -> bool:
        return bool(self.flags & (1 << 3))

    @property
    def last_chunk(self) -> bool:
        return bool(self.flags & (1 << 2))

    @property
    def device_monotonic_valid(self) -> bool:
        return bool(self.flags & (1 << 4))

    @property
    def sample_index_valid(self) -> bool:
        return bool(self.flags & (1 << 5))

    @property
    def unknown_flag_bits(self) -> int:
        return self.flags & ~FLAGS_KNOWN_MASK & 0xFFFF

    def pack(self) -> bytes:
        if not 0 <= self.payload_bytes <= MAX_PAYLOAD_CEILING:
            raise BackendError("bad_args", {"field": "payload_bytes"})
        header = bytearray(HEADER_BYTES)
        header[0:4] = MAGIC
        struct.pack_into("<HHHH", header, 4, self.protocol_version, self.header_bytes,
                         self.message_type, self.flags)
        struct.pack_into("<III", header, 12, self.payload_bytes, self.stream_id,
                         self.sequence)
        struct.pack_into("<QQQ", header, 24, self.connection_epoch,
                         self.first_sample_index, self.device_monotonic_ns)
        struct.pack_into("<III", header, 48, self.frame_id, self.config_version,
                         self.payload_crc32)
        struct.pack_into("<I", header, 60, 0)
        return bytes(header)

    @classmethod
    def unpack(cls, data: bytes, negotiated_max_payload: int = DEFAULT_MAX_BINARY_PAYLOAD) -> "SmaHeader":
        if len(data) != HEADER_BYTES:
            raise BackendError("bad_args", {"field": "header-length", "bytes": len(data)})
        if data[0:4] != MAGIC:
            raise BackendError("protocol_mismatch", {"reason": "bad-magic"})
        version, header_bytes, message_type, flags = struct.unpack_from("<HHHH", data, 4)
        payload_bytes, stream_id, sequence = struct.unpack_from("<III", data, 12)
        epoch, first_sample, device_ns = struct.unpack_from("<QQQ", data, 24)
        frame_id, config_version, payload_crc = struct.unpack_from("<III", data, 48)
        reserved = struct.unpack_from("<I", data, 60)[0]
        if version != PROTOCOL_VERSION:
            raise BackendError("unsupported_version", {"binaryVersion": version})
        if header_bytes != HEADER_BYTES:
            raise BackendError("bad_args", {"field": "headerBytes", "value": header_bytes})
        if reserved != 0:
            raise BackendError("bad_args", {"field": "reserved", "value": reserved})
        if not 0 <= payload_bytes <= negotiated_max_payload:
            raise BackendError("line_too_long",
                               {"reason": "binary-payload-over-negotiated-limit",
                                "payloadBytes": payload_bytes,
                                "limit": negotiated_max_payload})
        header = cls(protocol_version=version, header_bytes=header_bytes,
                     message_type=message_type, flags=flags,
                     payload_bytes=payload_bytes, stream_id=stream_id,
                     sequence=sequence, connection_epoch=epoch,
                     first_sample_index=first_sample, device_monotonic_ns=device_ns,
                     frame_id=frame_id, config_version=config_version,
                     payload_crc32=payload_crc)
        if payload_bytes and not header.crc_valid_flag:
            raise BackendError("crc_mismatch", {"reason": "crc-flag-missing"})
        if message_type in (MSG_HEARTBEAT, MSG_BYE) and payload_bytes:
            # HEARTBEAT must be empty; BYE carries a JSON reason, handled by sender flag.
            if message_type == MSG_HEARTBEAT:
                raise BackendError("bad_args", {"field": "heartbeatPayload",
                                                "value": payload_bytes})
        return header


def encode_frame(header: SmaHeader, payload: bytes = b"") -> bytes:
    if len(payload) != header.payload_bytes:
        raise BackendError("bad_args", {"field": "payloadBytes",
                                        "declared": header.payload_bytes,
                                        "actual": len(payload)})
    flags = header.flags
    if payload:
        flags |= FLAG_CRC32_VALID
        header = SmaHeader(**{**header.__dict__, "flags": flags,
                              "payload_crc32": crc32(payload)})
    return header.pack() + payload


class FrameDecoder:
    """Incremental SMA1 frame decoder with bounded payload handling."""

    def __init__(self, negotiated_max_payload: int = DEFAULT_MAX_BINARY_PAYLOAD) -> None:
        self.negotiated_max_payload = negotiated_max_payload
        self._buffer = bytearray()
        self.unknown_messages = 0
        self.heartbeats = 0

    def feed(self, data: bytes) -> list[tuple[SmaHeader, bytes]]:
        self._buffer.extend(data)
        frames: list[tuple[SmaHeader, bytes]] = []
        while len(self._buffer) >= HEADER_BYTES:
            header = SmaHeader.unpack(bytes(self._buffer[:HEADER_BYTES]),
                                      self.negotiated_max_payload)
            total = HEADER_BYTES + header.payload_bytes
            if len(self._buffer) < total:
                break
            payload = bytes(self._buffer[HEADER_BYTES:total])
            del self._buffer[:total]
            if header.payload_bytes:
                if header.crc_valid_flag and crc32(payload) != header.payload_crc32:
                    raise BackendError("crc_mismatch",
                                       {"messageType": header.message_type,
                                        "streamId": header.stream_id,
                                        "sequence": header.sequence})
            elif header.message_type == MSG_HEARTBEAT:
                self.heartbeats += 1
            frames.append((header, payload))
        return frames

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    def reset(self) -> None:
        self._buffer.clear()


def build_frame(message_type: int, payload: bytes = b"", *, flags: int = 0,
                stream_id: int = 0, sequence: int = 0, connection_epoch: int = 0,
                first_sample_index: int = 0, device_monotonic_ns: int = 0,
                frame_id: int = 0, config_version: int = 0) -> bytes:
    header = SmaHeader(message_type=message_type, flags=flags, payload_bytes=len(payload),
                       stream_id=stream_id, sequence=sequence,
                       connection_epoch=connection_epoch,
                       first_sample_index=first_sample_index,
                       device_monotonic_ns=device_monotonic_ns,
                       frame_id=frame_id, config_version=config_version)
    if payload:
        header = SmaHeader(**{**header.__dict__,
                              "flags": header.flags | FLAG_CRC32_VALID,
                              "payload_crc32": crc32(payload)})
    return header.pack() + payload
