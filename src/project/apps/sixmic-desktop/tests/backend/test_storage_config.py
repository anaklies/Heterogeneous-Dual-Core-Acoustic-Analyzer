"""SQLite WAL storage recovery/indexes and validated user configuration."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from sixmic_backend.constants import DEFAULT_BINARY_PORT, DEFAULT_CONTROL_PORT
from sixmic_backend.data.config_store import ConfigStore
from sixmic_backend.data.storage import Storage
from sixmic_backend.errors import BackendError
from sixmic_backend.model.dto import JobState


def test_jobs_and_recordings_roundtrip(tmp_path: Path):
    storage = Storage(tmp_path / "db.sqlite")
    storage.save_job({"jobId": "job-1", "kind": "p2OneShot", "state": "accepted"})
    storage.save_job({"jobId": "job-1", "kind": "p2OneShot", "state": "completed"})
    jobs = storage.list_jobs()
    assert jobs[0]["state"] == "completed"
    storage.save_recording({"recordingId": "rec-1", "records": "10"}, "/tmp/rec-1")
    recordings = storage.list_recordings()
    assert recordings[0]["manifest"]["recordingId"] == "rec-1"
    storage.set_setting("theme", "dark")
    assert storage.get_setting("theme") == "dark"
    storage.close()


def test_corrupt_database_is_quarantined_and_recovered(tmp_path: Path):
    path = tmp_path / "db.sqlite"
    path.write_bytes(b"not sqlite" * 64)
    storage = Storage(path)
    assert storage.recovered is True
    storage.save_job({"jobId": "job-2", "kind": "k", "state": "accepted"})
    assert storage.list_jobs()[0]["jobId"] == "job-2"
    storage.close()
    assert any(p.name.startswith("db.sqlite.corrupt-") for p in tmp_path.iterdir())


def test_default_config_uses_new_ports_and_never_48110(tmp_path: Path):
    store = ConfigStore(tmp_path / "config.json")
    values = store.load()
    assert values["controlPort"] == DEFAULT_CONTROL_PORT == 48120
    assert values["binaryPort"] == DEFAULT_BINARY_PORT == 48121
    values["host"] = "192.168.10.2"
    saved = store.save()
    assert saved["host"] == "192.168.10.2"
    reloaded = ConfigStore(tmp_path / "config.json").load()
    assert reloaded["binaryPort"] == 48121


@pytest.mark.parametrize("mutation", [
    {"controlPort": 48110},
    {"binaryPort": 48110},
    {"controlPort": 0},
    {"binaryPort": 70000},
    {"autoReconnect": "yes"},
    {"controlLeaseSeconds": 1},
    {"recordingMaxBytes": 1024},
    {"host": ""},
])
def test_invalid_config_rejected(tmp_path: Path, mutation):
    with pytest.raises(BackendError):
        ConfigStore.validate({**ConfigStore(DEFAULTS_PATH := tmp_path / "x.json").values,
                              **mutation})


def test_config_file_corruption_falls_back_to_defaults(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    store = ConfigStore(path)
    values = store.load()
    assert values["controlPort"] == 48120
    assert store.load_error is not None


def test_persisted_order_clock_is_wall_clock(tmp_path: Path):
    """F-06: monotonic_ns resets on restart; persisted ordering needs wall time."""
    import time as _time

    from sixmic_backend.data import storage as storage_mod

    assert abs(storage_mod._now_ns() - _time.time_ns()) < 5_000_000_000

    path = tmp_path / "db.sqlite"
    first = Storage(path)
    first.save_event({"eventId": 1, "reason": "before-restart"})
    first.close()
    _time.sleep(0.01)
    second = Storage(path)  # simulates a new process/boot
    second.save_event({"eventId": 2, "reason": "after-restart"})
    rows = second.list_events(10)
    assert [row["event"]["eventId"] for row in rows] == [2, 1]
    second.close()
