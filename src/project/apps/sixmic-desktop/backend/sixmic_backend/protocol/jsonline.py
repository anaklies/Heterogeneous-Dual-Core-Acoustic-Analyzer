"""Strict UTF-8 JSON Lines framing for the control channel.

Rules from interfaces/pc_backend_v1/PROTOCOL.md section 2.1:
- one UTF-8 JSON object per LF-terminated line, max 65536 bytes including LF
- reject CR, invalid UTF-8, duplicate keys, NaN/Infinity, over-depth/over-node,
  empty lines are ignored and counted
- partial/sticky packets are handled by the byte-level buffer
"""
from __future__ import annotations

import json
import math
from typing import Any, Iterable

from ..constants import MAX_JSON_DEPTH, MAX_JSON_NODES, MAX_LINE_BYTES
from ..errors import BackendError


class _DuplicateKeyError(ValueError):
    pass


def _object_pairs_hook(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(f"duplicate key: {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant: {value}")


def _check_complexity(root: Any) -> None:
    stack: list[tuple[Any, int]] = [(root, 0)]
    visited = 0
    while stack:
        node, depth = stack.pop()
        visited += 1
        if visited > MAX_JSON_NODES:
            raise ValueError("JSON node limit exceeded")
        if depth > MAX_JSON_DEPTH:
            raise ValueError("JSON depth limit exceeded")
        if isinstance(node, float):
            if not math.isfinite(node):
                raise ValueError("non-finite JSON number")
        elif isinstance(node, int):
            if node.bit_length() > 64:
                raise ValueError("JSON integer exceeds 64 bits")
        elif isinstance(node, dict):
            stack.extend((child, depth + 1) for child in node.values())
        elif isinstance(node, list):
            stack.extend((child, depth + 1) for child in node)


def decode_line(line: bytes | str) -> dict[str, Any]:
    """Decode exactly one control line (without LF). Raises BackendError."""
    if isinstance(line, bytes):
        try:
            text = line.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise BackendError("bad_utf8", {"position": exc.start}) from exc
    else:
        text = line
    if "\r" in text:
        raise BackendError("bad_json", {"reason": "carriage-return-not-allowed"})
    if not text:
        raise BackendError("bad_json", {"reason": "empty-line"})
    try:
        payload = json.loads(text, object_pairs_hook=_object_pairs_hook,
                             parse_constant=_reject_constant)
    except _DuplicateKeyError as exc:
        raise BackendError("bad_json", {"reason": "duplicate-key"}) from exc
    except (ValueError, RecursionError) as exc:
        raise BackendError("bad_json", {"reason": "malformed-json",
                                        "technical": str(exc)[:200]}) from exc
    try:
        _check_complexity(payload)
    except ValueError as exc:
        raise BackendError("bad_json", {"reason": "complexity-limit",
                                        "technical": str(exc)}) from exc
    if not isinstance(payload, dict):
        raise BackendError("bad_json", {"reason": "not-a-json-object"})
    return payload


def encode_line(payload: dict[str, Any]) -> bytes:
    """Encode one control line including the terminating LF."""
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False)
    encoded = text.encode("utf-8") + b"\n"
    if len(encoded) > MAX_LINE_BYTES:
        raise BackendError("line_too_long", {"bytes": len(encoded),
                                             "limit": MAX_LINE_BYTES})
    return encoded


class LineDecoder:
    """Incremental byte-stream decoder for the control channel."""

    def __init__(self, max_line_bytes: int = MAX_LINE_BYTES) -> None:
        self.max_line_bytes = max_line_bytes
        self._buffer = bytearray()
        self.empty_lines = 0
        self.received_lines = 0

    def feed(self, data: bytes) -> list[dict[str, Any]]:
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("feed() requires bytes")
        self._buffer.extend(data)
        decoded: list[dict[str, Any]] = []
        while True:
            index = self._buffer.find(b"\n")
            if index < 0:
                if len(self._buffer) >= self.max_line_bytes:
                    raise BackendError("line_too_long",
                                       {"buffered": len(self._buffer),
                                        "limit": self.max_line_bytes})
                break
            raw = bytes(self._buffer[:index])
            del self._buffer[:index + 1]
            if len(raw) + 1 > self.max_line_bytes:
                raise BackendError("line_too_long",
                                   {"bytes": len(raw) + 1, "limit": self.max_line_bytes})
            if not raw:
                self.empty_lines += 1
                continue
            self.received_lines += 1
            decoded.append(decode_line(raw))
        return decoded

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    def reset(self) -> None:
        self._buffer.clear()


def dumps_compact(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
