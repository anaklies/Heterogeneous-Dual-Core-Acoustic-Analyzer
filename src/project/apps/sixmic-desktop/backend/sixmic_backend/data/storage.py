"""SQLite WAL storage for indexes/config/jobs/events (never per-sample rows)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from ..errors import BackendError

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY, kind TEXT NOT NULL, state TEXT NOT NULL,
    payload TEXT NOT NULL, updated_ns INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY, state TEXT NOT NULL, payload TEXT NOT NULL,
    directory TEXT, updated_ns INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS recordings (
    recording_id TEXT PRIMARY KEY, payload TEXT NOT NULL, directory TEXT,
    updated_ns INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_jobs_updated ON jobs(updated_ns DESC);
CREATE INDEX IF NOT EXISTS idx_events_updated ON events(updated_ns DESC);
CREATE INDEX IF NOT EXISTS idx_recordings_updated ON recordings(updated_ns DESC);
"""


def _now_ns() -> int:
    # updated_ns is persisted and used for ORDER BY across restarts; the
    # monotonic clock resets on boot, so only the wall clock is meaningful here.
    return time.time_ns()


class Storage:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.recovered = False
        self.recovery_note: str | None = None
        self._db_lock = threading.RLock()
        self._connection = self._open()

    # -- connection --------------------------------------------------------
    def _open(self) -> sqlite3.Connection:
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect_and_initialize()
            return connection
        except (sqlite3.DatabaseError, BackendError) as exc:
            self.recovered = True
            self.recovery_note = str(exc)[:300]
            if connection is not None:
                try:
                    connection.close()
                except sqlite3.Error:
                    pass
                connection = None
            self._quarantine_corrupt_database()
            connection = self._connect_and_initialize(quarantine=False)
            return connection

    def _connect_and_initialize(self, quarantine: bool = True) -> sqlite3.Connection:
        # Backend jobs/events may be persisted from transport threads.
        connection = sqlite3.connect(str(self.path), timeout=5.0,
                                     check_same_thread=False)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.executescript(SCHEMA)
            version = connection.execute(
                "SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if version is None:
                connection.execute("INSERT INTO meta(key,value) VALUES('schema_version',?)",
                                   (str(SCHEMA_VERSION),))
                connection.commit()
            elif int(version[0]) != SCHEMA_VERSION:
                raise BackendError("file_corrupt", {"reason": "storage-schema-version",
                                                    "found": version[0]})
            return connection
        except BaseException:
            try:
                connection.close()
            except sqlite3.Error:
                pass
            raise

    def _quarantine_corrupt_database(self) -> None:
        stamp = int(time.time())
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(self.path) + suffix)
            if not candidate.exists():
                continue
            target = Path(str(self.path) + f".corrupt-{stamp}{suffix}")
            for attempt in range(5):
                try:
                    candidate.replace(target)
                    break
                except OSError:
                    time.sleep(0.05 * (attempt + 1))

    def _execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> Any:
        try:
            with self._db_lock:
                cursor = self._connection.execute(sql, parameters)
                self._connection.commit()
                return cursor
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if "disk" in message or "full" in message:
                raise BackendError("storage_full", {"reason": "sqlite", "detail": str(exc)}) from exc
            raise BackendError("io_error", {"reason": "sqlite", "detail": str(exc)}) from exc
        except sqlite3.DatabaseError as exc:
            raise BackendError("file_corrupt", {"reason": "sqlite", "detail": str(exc)}) from exc

    # -- jobs --------------------------------------------------------------
    def save_job(self, job: dict[str, Any]) -> None:
        self._execute(
            "INSERT INTO jobs(job_id,kind,state,payload,updated_ns) VALUES(?,?,?,?,?) "
            "ON CONFLICT(job_id) DO UPDATE SET kind=excluded.kind,state=excluded.state,"
            "payload=excluded.payload,updated_ns=excluded.updated_ns",
            (str(job["jobId"]), str(job.get("kind", "")), str(job.get("state", "")),
             json.dumps(job, ensure_ascii=False), _now_ns()))

    def list_jobs(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._execute("SELECT payload FROM jobs ORDER BY updated_ns DESC LIMIT ?",
                             (int(limit),)).fetchall()
        return [json.loads(row[0]) for row in rows]

    # -- events ------------------------------------------------------------
    def save_event(self, event: dict[str, Any], *, state: str = "known",
                   directory: str | None = None) -> None:
        self._execute(
            "INSERT INTO events(event_id,state,payload,directory,updated_ns) VALUES(?,?,?,?,?) "
            "ON CONFLICT(event_id) DO UPDATE SET state=excluded.state,payload=excluded.payload,"
            "directory=excluded.directory,updated_ns=excluded.updated_ns",
            (str(event["eventId"]), state, json.dumps(event, ensure_ascii=False),
             directory, _now_ns()))

    def list_events(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self._execute("SELECT payload,state,directory FROM events "
                            "ORDER BY updated_ns DESC LIMIT ?", (int(limit),)).fetchall()
        return [{"event": json.loads(row[0]), "state": row[1], "directory": row[2]}
                for row in rows]

    def get_event(self, event_id: int | str) -> dict[str, Any] | None:
        row = self._execute("SELECT payload,state,directory FROM events WHERE event_id=?",
                            (str(event_id),)).fetchone()
        if row is None:
            return None
        return {"event": json.loads(row[0]), "state": row[1], "directory": row[2]}

    # -- recordings --------------------------------------------------------
    def save_recording(self, manifest: dict[str, Any], directory: str | None = None) -> None:
        self._execute(
            "INSERT INTO recordings(recording_id,payload,directory,updated_ns) VALUES(?,?,?,?) "
            "ON CONFLICT(recording_id) DO UPDATE SET payload=excluded.payload,"
            "directory=excluded.directory,updated_ns=excluded.updated_ns",
            (str(manifest["recordingId"]), json.dumps(manifest, ensure_ascii=False),
             directory, _now_ns()))

    def list_recordings(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._execute("SELECT payload,directory FROM recordings "
                             "ORDER BY updated_ns DESC LIMIT ?", (int(limit),)).fetchall()
        return [{"manifest": json.loads(row[0]), "directory": row[1]} for row in rows]

    def set_setting(self, key: str, value: Any) -> None:
        self._execute("INSERT INTO meta(key,value) VALUES(?,?) "
                      "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (str(key), json.dumps(value, ensure_ascii=False)))

    def get_setting(self, key: str) -> Any:
        row = self._execute("SELECT value FROM meta WHERE key=?", (str(key),)).fetchone()
        return None if row is None else json.loads(row[0])

    # -- lifecycle ---------------------------------------------------------
    def checkpoint(self) -> None:
        try:
            self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.DatabaseError:
            pass

    def close(self) -> None:
        connection = getattr(self, "_connection", None)
        if connection is None:
            return
        try:
            self.checkpoint()
        except Exception:
            pass
        try:
            connection.close()
        except Exception:
            pass
        self._connection = None

    def stats(self) -> dict[str, Any]:
        counts = {}
        for table in ("jobs", "events", "recordings"):
            row = self._execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            counts[table] = int(row[0])
        return {"path": str(self.path), "recovered": self.recovered,
                "recoveryNote": self.recovery_note, **counts}
