"""Access to the frozen golden wire samples used as a cross-implementation oracle."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..errors import BackendError
from ..paths import protocol_dir


class GoldenSuite:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root else protocol_dir()
        if self.root is None:
            raise BackendError("file_missing", {"reason": "protocol-directory-not-found"})
        manifest_path = self.root / "golden" / "GOLDEN_MANIFEST.json"
        try:
            self.manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BackendError("file_missing", {"reason": "golden-manifest",
                                                "path": str(manifest_path)}) from exc

    def entries(self) -> list[str]:
        return sorted(key for key in self.manifest if key != "_meta")

    def path_of(self, name: str) -> Path:
        if name not in self.manifest:
            raise BackendError("file_missing", {"reason": "golden-entry", "name": name})
        return self.root / "golden" / name

    def read(self, name: str) -> bytes:
        return self.path_of(name).read_bytes()

    def read_jsonl(self, name: str) -> dict[str, Any]:
        text = self.read(name).decode("utf-8").rstrip("\n")
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise BackendError("schema_mismatch", {"reason": "golden-not-object", "name": name})
        return payload

    def verify(self) -> dict[str, Any]:
        """Recompute every sample hash; used by BackendCheck --self-test."""
        checked = 0
        failures: list[dict[str, str]] = []
        for name in self.entries():
            entry = self.manifest[name]
            data = self.read(name)
            digest = hashlib.sha256(data).hexdigest()
            checked += 1
            if digest != entry.get("sha256") or len(data) != entry.get("bytes"):
                failures.append({"name": name, "expected": entry.get("sha256"),
                                 "actual": digest})
        return {"checked": checked, "failures": failures,
                "protocol": self.manifest.get("_meta", {}).get("protocol"),
                "protocolVersion": self.manifest.get("_meta", {}).get("protocolVersion")}
