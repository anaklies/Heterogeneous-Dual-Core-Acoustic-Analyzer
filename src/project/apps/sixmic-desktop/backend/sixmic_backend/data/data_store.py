"""Owned large-buffer handles. QML never receives whole arrays inline."""
from __future__ import annotations

import hashlib
import threading
import uuid
from typing import Any

from ..errors import BackendError
from .bounds import ByteBudget

ELEMENT_WIDTHS = {"uint8": 1, "int32": 4, "uint32": 4, "float32": 4, "float64": 8}


class BufferHandle:
    def __init__(self, handle_id: str, data: bytes, element_type: str,
                 display_only: bool, source_kind: str) -> None:
        if element_type not in ELEMENT_WIDTHS:
            raise BackendError("bad_args", {"field": "elementType"})
        self.handle_id = handle_id
        self.data = data
        self.element_type = element_type
        self.width = ELEMENT_WIDTHS[element_type]
        self.display_only = display_only
        self.source_kind = source_kind
        self.refcount = 1
        self.sha256 = hashlib.sha256(data).hexdigest() if not display_only else None

    @property
    def count(self) -> int:
        return len(self.data) // self.width

    def to_ref(self) -> dict[str, Any]:
        return {"handleId": self.handle_id, "bytes": len(self.data),
                "elementType": self.element_type, "count": self.count,
                "layout": "interleaved", "alignment": self.width,
                "displayOnly": self.display_only, "sourceKind": self.source_kind,
                "sha256": self.sha256}


class DataStore:
    """Reference-counted, capacity-bounded owner of large buffers."""

    def __init__(self, capacity_bytes: int = 256 * 1024 * 1024) -> None:
        self._handles: dict[str, BufferHandle] = {}
        self._lock = threading.RLock()
        self.budget = ByteBudget(capacity_bytes, "data-store")
        self.evicted = 0
        self.rejected = 0

    def put(self, data: bytes, element_type: str = "uint8", *,
            display_only: bool = False, source_kind: str = "test-fixture") -> str:
        if not self.budget.acquire(len(data)):
            self.rejected += 1
            raise BackendError("storage_full", {"reason": "data-store-capacity",
                                                "bytes": len(data),
                                                "capacity": self.budget.capacity_bytes})
        handle_id = "buf-" + uuid.uuid4().hex[:16]
        try:
            handle = BufferHandle(handle_id, bytes(data), element_type,
                                  display_only, source_kind)
        except BaseException:
            # Validation failed after the capacity was reserved: release it so a
            # rejected put() cannot permanently shrink the budget.
            self.budget.release(len(data))
            raise
        with self._lock:
            self._handles[handle_id] = handle
        return handle_id

    def reference(self, handle_id: str) -> None:
        with self._lock:
            handle = self._handles.get(handle_id)
            if handle is None:
                raise BackendError("bad_args", {"field": "handleId", "reason": "unknown"})
            handle.refcount += 1

    def get(self, handle_id: str) -> BufferHandle:
        with self._lock:
            handle = self._handles.get(handle_id)
            if handle is None:
                raise BackendError("bad_args", {"field": "handleId", "reason": "unknown"})
            return handle

    def read_slice(self, handle_id: str, offset_elements: int, count_elements: int) -> bytes:
        handle = self.get(handle_id)
        if offset_elements < 0 or count_elements < 0:
            raise BackendError("bad_args", {"field": "slice"})
        start = offset_elements * handle.width
        end = start + count_elements * handle.width
        if end > len(handle.data):
            raise BackendError("bad_args", {"field": "slice", "reason": "out-of-range"})
        return handle.data[start:end]

    def release(self, handle_id: str) -> bool:
        with self._lock:
            handle = self._handles.get(handle_id)
            if handle is None:
                return False
            handle.refcount -= 1
            if handle.refcount <= 0:
                del self._handles[handle_id]
                self.budget.release(len(handle.data))
                return True
            return False

    def clear_unreferenced(self) -> int:
        removed = 0
        with self._lock:
            for handle_id in [key for key, handle in self._handles.items()
                              if handle.refcount <= 0]:
                handle = self._handles.pop(handle_id)
                self.budget.release(len(handle.data))
                self.evicted += 1
                removed += 1
        return removed

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"handles": len(self._handles), "evicted": self.evicted,
                    "rejected": self.rejected, **self.budget.stats()}
