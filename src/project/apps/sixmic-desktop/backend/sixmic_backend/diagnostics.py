"""Bounded rotating logs + in-memory diagnostic ring for diagnostics.get."""
from __future__ import annotations

import collections
import logging
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


class DiagnosticRing:
    def __init__(self, capacity: int = 2000) -> None:
        self.capacity = max(16, int(capacity))
        self._records: collections.deque[dict[str, Any]] = collections.deque(
            maxlen=self.capacity)
        self._lock = threading.Lock()
        self.total = 0
        self.dropped = 0

    def append(self, level: str, code: str, message_key: str | None = None,
               detail: dict[str, Any] | None = None) -> dict[str, Any]:
        record = {"level": level, "code": code,
                  "messageKey": message_key or f"errors.{code}",
                  "detail": dict(detail or {}),
                  "monotonicNs": str(time.monotonic_ns()),
                  "wallTimeNs": str(time.time_ns())}
        with self._lock:
            if len(self._records) >= self.capacity:
                self.dropped += 1
            self._records.append(record)
            self.total += 1
        return record

    def tail(self, lines: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._records)[-max(1, min(int(lines), self.capacity)):]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"capacity": self.capacity, "depth": len(self._records),
                    "total": self.total, "dropped": self.dropped}


_LOG_LOCK = threading.Lock()
_LOGGER: logging.Logger | None = None


def setup_logging(log_dir: str | Path, *, level: int = logging.INFO,
                  max_bytes: int = 2 * 1024 * 1024, backup_count: int = 3) -> logging.Logger:
    """Idempotently configure a bounded rotating log under the user data dir."""
    global _LOGGER
    with _LOG_LOCK:
        if _LOGGER is not None:
            return _LOGGER
        directory = Path(log_dir)
        directory.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger("sixmic_backend")
        logger.setLevel(level)
        logger.propagate = False
        if not logger.handlers:
            handler = RotatingFileHandler(directory / "backend.log", maxBytes=max_bytes,
                                          backupCount=backup_count, encoding="utf-8")
            handler.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s"))
            logger.addHandler(handler)
        _LOGGER = logger
        return logger


def get_logger() -> logging.Logger:
    return _LOGGER or logging.getLogger("sixmic_backend")


def close_backend_logging() -> None:
    """Close and detach handlers (needed before deleting the log dir on Windows)."""
    global _LOGGER
    logger = logging.getLogger("sixmic_backend")
    for handler in list(logger.handlers):
        try:
            handler.flush()
            handler.close()
        except Exception:
            pass
        logger.removeHandler(handler)
    _LOGGER = None
