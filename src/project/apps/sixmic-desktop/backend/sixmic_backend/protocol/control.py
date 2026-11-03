"""Control-channel envelopes and the frozen operation whitelist."""
from __future__ import annotations

import re
from typing import Any

from ..constants import MAX_REQUEST_ID_CHARS, MAX_SESSION_ID_CHARS, PROTOCOL_NAME, PROTOCOL_VERSION
from ..errors import BackendError

REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_U64_MAX = (1 << 64) - 1

READ_ONLY_OPS = frozenset({
    "capabilities.get", "status.get", "diagnostics.get", "heartbeat",
    "job.get", "job.list", "event.list", "event.get", "event.download",
    "event.ack", "recording.status", "config.read", "subscribe", "unsubscribe",
    "stream.open", "stream.close",
})
CONTROL_OPS = frozenset({
    "control.claim", "control.renew", "control.release",
    "config.write", "config.commit", "config.abort",
    "task.start", "task.cancel",
    "recording.start", "recording.stop",
    "event.discard",
    "profile.upload", "profile.activate", "profile.deactivate",
})
ALL_OPS = frozenset({"hello", "time.sync"}) | READ_ONLY_OPS | CONTROL_OPS
PROFILE_OPS = frozenset({"profile.upload", "profile.activate", "profile.deactivate"})
EVENT_TYPES = frozenset({
    "jobUpdated", "eventAdded", "deviceState", "configApplied",
    "recordingChanged", "streamGap", "diagnosticAdded", "controlChanged",
})
STREAM_TYPES = frozenset({"resultWords", "pcmRecord32", "serviceSnapshot", "events", "eventFile"})
JOB_KINDS = frozenset({"p1Carousel", "p2OneShot"})
RESPONSE_STATUSES = frozenset({"ok", "accepted", "error"})


def _require(mapping: dict[str, Any], key: str, kind: type | tuple[type, ...], field: str) -> Any:
    if key not in mapping:
        raise BackendError("bad_args", {"field": field, "reason": "missing"})
    value = mapping[key]
    if isinstance(value, bool) and kind is not bool:
        raise BackendError("bad_args", {"field": field, "reason": "bool-not-allowed"})
    if not isinstance(value, kind):
        raise BackendError("bad_args", {"field": field, "reason": "type",
                                        "expected": getattr(kind, "__name__", str(kind))})
    return value


def parse_u64(value: Any, field: str) -> int:
    """Parse a 64-bit counter: decimal string on the wire, int internally."""
    if isinstance(value, bool):
        raise BackendError("bad_args", {"field": field, "reason": "bool-not-allowed"})
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]{0,19}", value or ""):
        number = int(value)
    elif isinstance(value, str) and value.isdigit():
        number = int(value)
    else:
        raise BackendError("bad_args", {"field": field, "reason": "u64-string-expected"})
    if not 0 <= number <= _U64_MAX:
        raise BackendError("bad_args", {"field": field, "reason": "u64-range"})
    return number


def u64(value: int) -> str:
    """Encode an internal uint64 as the wire decimal string."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise BackendError("bad_args", {"field": "u64", "reason": "int-required"})
    if not 0 <= value <= _U64_MAX:
        raise BackendError("bad_args", {"field": "u64", "reason": "range"})
    return str(value)


def validate_request(payload: dict[str, Any]) -> tuple[str, str | None, str, dict[str, Any]]:
    if payload.get("protocol") != PROTOCOL_NAME:
        raise BackendError("protocol_mismatch",
                           {"expected": PROTOCOL_NAME, "received": payload.get("protocol")})
    version = payload.get("version")
    if version != PROTOCOL_VERSION:
        raise BackendError("unsupported_version", {"version": version})
    request_id = payload.get("requestId")
    if not isinstance(request_id, str) or not REQUEST_ID_RE.match(request_id):
        raise BackendError("bad_args", {"field": "requestId"})
    op = payload.get("op")
    if not isinstance(op, str):
        raise BackendError("bad_args", {"field": "op"})
    if op not in ALL_OPS:
        raise BackendError("unknown_op", {"op": op})
    args = payload.get("args", {})
    if not isinstance(args, dict):
        raise BackendError("bad_args", {"field": "args"})
    session = payload.get("sessionId")
    if session is not None:
        if not isinstance(session, str) or not 1 <= len(session) <= MAX_SESSION_ID_CHARS:
            raise BackendError("bad_args", {"field": "sessionId"})
    if op != "hello" and not session:
        raise BackendError("not_authenticated", {"reason": "hello-required"})
    return request_id, session, op, args


def build_request(op: str, request_id: str, session_id: str | None, args: dict[str, Any] | None = None) -> dict[str, Any]:
    if op not in ALL_OPS:
        raise BackendError("unknown_op", {"op": op})
    if not REQUEST_ID_RE.match(request_id or ""):
        raise BackendError("bad_args", {"field": "requestId"})
    if op != "hello" and not session_id:
        raise BackendError("bad_args", {"field": "sessionId"})
    return {"protocol": PROTOCOL_NAME, "version": PROTOCOL_VERSION,
            "requestId": request_id, "sessionId": session_id,
            "op": op, "args": dict(args or {})}


def build_response(request_id: str, status: str, result: dict[str, Any] | None = None,
                   error: dict[str, Any] | None = None) -> dict[str, Any]:
    if status not in RESPONSE_STATUSES:
        raise BackendError("bad_args", {"field": "status"})
    if status == "error":
        if not isinstance(error, dict):
            raise BackendError("bad_args", {"field": "error"})
        return {"type": "response", "protocol": PROTOCOL_NAME,
                "version": PROTOCOL_VERSION, "requestId": request_id,
                "status": "error", "error": error}
    return {"type": "response", "protocol": PROTOCOL_NAME, "version": PROTOCOL_VERSION,
            "requestId": request_id, "status": status, "result": dict(result or {})}


def build_event(name: str, event_id: int, data: dict[str, Any]) -> dict[str, Any]:
    if name not in EVENT_TYPES:
        raise BackendError("bad_args", {"field": "event", "value": name})
    return {"type": "event", "protocol": PROTOCOL_NAME, "version": PROTOCOL_VERSION,
            "event": name, "eventId": u64(event_id), "data": data}


def validate_response(payload: dict[str, Any], request_id: str) -> dict[str, Any]:
    if payload.get("type") != "response":
        raise BackendError("schema_mismatch", {"reason": "not-a-response"})
    if payload.get("protocol") != PROTOCOL_NAME:
        raise BackendError("protocol_mismatch", {"received": payload.get("protocol")})
    if payload.get("version") != PROTOCOL_VERSION:
        raise BackendError("unsupported_version", {"version": payload.get("version")})
    if payload.get("requestId") != request_id:
        raise BackendError("schema_mismatch", {"reason": "requestId-mismatch"})
    status = payload.get("status")
    if status not in RESPONSE_STATUSES:
        raise BackendError("schema_mismatch", {"reason": "bad-status"})
    if status == "error":
        error = payload.get("error")
        if not isinstance(error, dict) or not isinstance(error.get("code"), str):
            raise BackendError("schema_mismatch", {"reason": "bad-error"})
    elif not isinstance(payload.get("result"), dict):
        raise BackendError("schema_mismatch", {"reason": "missing-result"})
    return payload


def validate_event(payload: dict[str, Any]) -> tuple[str, int, dict[str, Any]]:
    if payload.get("type") != "event":
        raise BackendError("schema_mismatch", {"reason": "not-an-event"})
    name = payload.get("event")
    if name not in EVENT_TYPES:
        raise BackendError("schema_mismatch", {"reason": "unknown-event", "event": name})
    event_id = parse_u64(payload.get("eventId"), "eventId")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise BackendError("schema_mismatch", {"reason": "event-data"})
    return name, event_id, data
