"""Structured backend errors with stable machine codes.

The catalog is loaded from the frozen interface file when available; a bundled
copy of the codes is kept here so runtime never depends on the repo layout.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ERROR_CODES: dict[str, dict[str, Any]] = {
    "bad_json": {"retryable": False, "messageKey": "errors.bad_json"},
    "bad_utf8": {"retryable": False, "messageKey": "errors.bad_utf8"},
    "line_too_long": {"retryable": False, "messageKey": "errors.line_too_long"},
    "protocol_mismatch": {"retryable": False, "messageKey": "errors.protocol_mismatch"},
    "unsupported_version": {"retryable": False, "messageKey": "errors.unsupported_version"},
    "unknown_op": {"retryable": False, "messageKey": "errors.unknown_op"},
    "bad_args": {"retryable": False, "messageKey": "errors.bad_args"},
    "bad_state": {"retryable": False, "messageKey": "errors.bad_state"},
    "not_authenticated": {"retryable": False, "messageKey": "errors.not_authenticated"},
    "unknown_session": {"retryable": False, "messageKey": "errors.unknown_session"},
    "epoch_mismatch": {"retryable": False, "messageKey": "errors.epoch_mismatch"},
    "bad_token": {"retryable": False, "messageKey": "errors.bad_token"},
    "control_conflict": {"retryable": True, "messageKey": "errors.control_conflict"},
    "control_not_held": {"retryable": False, "messageKey": "errors.control_not_held"},
    "rejected": {"retryable": False, "messageKey": "errors.rejected"},
    "not_ready": {"retryable": False, "messageKey": "errors.not_ready"},
    "unsupported_feature": {"retryable": False, "messageKey": "errors.unsupported_feature"},
    "busy": {"retryable": True, "messageKey": "errors.busy"},
    "timeout": {"retryable": True, "messageKey": "errors.timeout"},
    "io_error": {"retryable": True, "messageKey": "errors.io_error"},
    "storage_full": {"retryable": False, "messageKey": "errors.storage_full"},
    "cursor_expired": {"retryable": False, "messageKey": "errors.cursor_expired"},
    "unknown_event": {"retryable": False, "messageKey": "errors.unknown_event"},
    "event_hash_mismatch": {"retryable": True, "messageKey": "errors.event_hash_mismatch"},
    "job_not_found": {"retryable": False, "messageKey": "errors.job_not_found"},
    "rate_limited": {"retryable": True, "messageKey": "errors.rate_limited"},
    "cancelled": {"retryable": False, "messageKey": "errors.cancelled"},
    "internal_error": {"retryable": False, "messageKey": "errors.internal_error"},
    # Local-only codes (not on the wire):
    "schema_mismatch": {"retryable": False, "messageKey": "errors.schema_mismatch"},
    "crc_mismatch": {"retryable": True, "messageKey": "errors.crc_mismatch"},
    "connection_lost": {"retryable": True, "messageKey": "errors.connection_lost"},
    "not_connected": {"retryable": False, "messageKey": "errors.not_connected"},
    "file_missing": {"retryable": False, "messageKey": "errors.file_missing"},
    "file_corrupt": {"retryable": False, "messageKey": "errors.file_corrupt"},
    "unsupported_operation": {"retryable": False, "messageKey": "errors.unsupported_operation"},
    "live_not_ready": {"retryable": False, "messageKey": "errors.live_not_ready"},
    "recording_active": {"retryable": False, "messageKey": "errors.recording_active"},
    "replay_state": {"retryable": False, "messageKey": "errors.replay_state"},
    "qt_unavailable": {"retryable": False, "messageKey": "errors.qt_unavailable"},
}


def load_error_catalog(protocol_dir: Path | None = None) -> dict[str, Any] | None:
    """Load the frozen catalogue when the shipped protocol data is present."""
    if protocol_dir is None:
        return None
    path = Path(protocol_dir) / "errors" / "ERROR_CATALOG.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {item["code"]: item for item in payload.get("errors", [])}
    except (OSError, ValueError, KeyError):
        return None


class BackendError(Exception):
    """Structured error: stable code + translation key + technical detail."""

    def __init__(self, code: str, detail: dict[str, Any] | None = None,
                 message_key: str | None = None, retryable: bool | None = None,
                 technical: str | None = None) -> None:
        if code not in ERROR_CODES:
            detail = dict(detail or {})
            detail.setdefault("originalCode", code)
            code = "internal_error"
        meta = ERROR_CODES[code]
        self.code = code
        self.message_key = message_key or meta["messageKey"]
        self.retryable = bool(meta["retryable"] if retryable is None else retryable)
        self.detail = dict(detail or {})
        if technical:
            self.detail.setdefault("technical", technical)
        super().__init__(f"{code}: {self.message_key} {self.detail if self.detail else ''}".strip())

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "messageKey": self.message_key,
                "retryable": self.retryable, "detail": self.detail}

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"BackendError({self.code!r}, {self.detail!r})"


def make_error(code: str, **detail: Any) -> BackendError:
    return BackendError(code, detail=detail)
