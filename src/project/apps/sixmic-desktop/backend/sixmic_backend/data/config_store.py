"""User configuration persistence (atomic JSON, validated, user-data directory)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..constants import DEFAULT_BINARY_PORT, DEFAULT_CONTROL_PORT, LEGACY_TAKEOVER_PORT
from ..errors import BackendError
from ..paths import user_data_dir

DEFAULTS: dict[str, Any] = {
    "schemaVersion": 1,
    "host": "192.168.10.2",
    "controlPort": DEFAULT_CONTROL_PORT,
    "binaryPort": DEFAULT_BINARY_PORT,
    "autoReconnect": True,
    "controlLeaseSeconds": 30,
    "recordingMaxBytes": 8 * 1024 * 1024 * 1024,
    "protocolDir": "",
    "lastReplayDirectory": "",
    "notes": ("Manual direct-link example only: PC 192.168.10.1/24, board 192.168.10.2/24. "
              "These are examples, not applied Windows network settings."),
}


class ConfigStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else user_data_dir() / "config.json"
        self.values: dict[str, Any] = dict(DEFAULTS)
        self.loaded_from_disk = False
        self.load_error: str | None = None

    def load(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return dict(self.values)
        except (OSError, ValueError) as exc:
            self.load_error = str(exc)[:200]
            return dict(self.values)
        if not isinstance(payload, dict):
            self.load_error = "config-not-object"
            return dict(self.values)
        candidate = dict(DEFAULTS)
        candidate.update(payload)
        try:
            self.values = self.validate(candidate)
            self.loaded_from_disk = True
        except BackendError as exc:
            self.load_error = exc.code
        return dict(self.values)

    @staticmethod
    def validate(values: dict[str, Any]) -> dict[str, Any]:
        result = dict(DEFAULTS)
        result.update({key: value for key, value in values.items() if key in DEFAULTS})
        host = result.get("host")
        if not isinstance(host, str) or not 0 < len(host) <= 255:
            raise BackendError("bad_args", {"field": "host"})
        for key in ("controlPort", "binaryPort"):
            port = result.get(key)
            if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
                raise BackendError("bad_args", {"field": key})
            if port == LEGACY_TAKEOVER_PORT:
                raise BackendError("bad_args", {"field": key,
                                                "reason": "legacy-48110-must-not-be-reused"})
        if result["controlPort"] == result["binaryPort"]:
            raise BackendError("bad_args", {"reason": "control-and-binary-port-must-differ"})
        if not isinstance(result.get("autoReconnect"), bool):
            raise BackendError("bad_args", {"field": "autoReconnect"})
        lease = result.get("controlLeaseSeconds")
        if isinstance(lease, bool) or not isinstance(lease, int) or not 5 <= lease <= 300:
            raise BackendError("bad_args", {"field": "controlLeaseSeconds"})
        max_bytes = result.get("recordingMaxBytes")
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1024 * 1024:
            raise BackendError("bad_args", {"field": "recordingMaxBytes"})
        return result

    def save(self, values: dict[str, Any] | None = None) -> dict[str, Any]:
        merged = dict(self.values)
        if values:
            merged.update(values)
        self.values = self.validate(merged)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        payload = json.dumps(self.values, ensure_ascii=False, indent=2) + "\n"
        try:
            temporary.write_text(payload, encoding="utf-8")
            os.replace(temporary, self.path)
        except OSError as exc:
            raise BackendError("storage_full", {"reason": "config-write",
                                                "detail": str(exc)}) from exc
        return dict(self.values)

    def status(self) -> dict[str, Any]:
        return {"path": str(self.path), "loadedFromDisk": self.loaded_from_disk,
                "loadError": self.load_error,
                "values": {key: value for key, value in self.values.items()
                           if key not in ("notes",)}}
