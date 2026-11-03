"""The console verification entry point must be real, deterministic and green."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sixmic_backend.app import backend_check
from sixmic_backend.errors import BackendError


def test_self_test_report_is_green(protocol_root, tmp_path):
    evidence = tmp_path / "evidence"
    report = backend_check.SelfTest(protocol_root=protocol_root,
                                    evidence_dir=evidence).run()
    assert report["ok"] is True
    names = [step["name"] for step in report["checks"]]
    assert names == ["golden_suite", "pcm_golden", "result_words", "jsonline_rules",
                     "framing_rules", "event_container", "feature_catalog",
                     "data_store_bounds", "storage_recovery", "recording_replay",
                     "mock_end_to_end"]
    assert all(step["ok"] for step in report["checks"])
    assert report["error"] is None
    written = json.loads((evidence / "backend-selftest.json").read_text(encoding="utf-8"))
    assert written["ok"] is True


def test_main_prints_pass_marker_and_returns_zero(protocol_root, tmp_path,
                                                  monkeypatch, capsys):
    monkeypatch.setenv("SIXMIC_USER_DATA_DIR", str(tmp_path / "userdata"))
    code = backend_check.main(["--self-test", "--protocol-dir", str(protocol_root)])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.strip().splitlines()[-1] == "SELF-TEST PASS"


def test_replay_cli(tmp_path, capsys):
    from sixmic_backend.data.recording import Recorder
    from sixmic_backend.protocol.pcm import encode_record
    recorder = Recorder(tmp_path / "rec", recording_id="r", device_id="d",
                        connection_epoch=1, session_id="s",
                        source_kind="test-fixture",
                        real_sample_rate_hz=48009.775390625)
    recorder.start()
    recorder.append_audio(encode_record([0, 1, 2, 3, 4, 5], 1), first_sample_index=1)
    recorder.stop()
    assert backend_check.main(["--replay", str(tmp_path / "rec")]) == 0
    assert "REPLAY-OK" in capsys.readouterr().out


def test_connect_cli_reports_failure_for_closed_port(capsys):
    code = backend_check.main(["--connect", "127.0.0.1:1"])
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] in ("timeout", "io_error", "connection_lost",
                                        "not_connected")


def test_connect_cli_keeps_stdout_json_on_unexpected_exception(monkeypatch, capsys):
    """F-10: --connect stdout must stay one valid JSON document on failure."""
    import sixmic_backend.session as session_module

    class BrokenSession:
        def __init__(self, *args, **kwargs):
            raise PermissionError("user-data directory is not writable")

    monkeypatch.setattr(session_module, "DeviceSession", BrokenSession)
    code = backend_check.main(["--connect", "127.0.0.1:1"])
    captured = capsys.readouterr()
    assert code == 1
    payload = json.loads(captured.out)  # single JSON object, no trailing marker
    assert payload["ok"] is False
    assert "PermissionError" in payload["error"]
    assert "SELF-TEST FAIL" in captured.err


def test_control_client_reports_refused_connection_not_generic_timeout():
    """F-12: refused control port must surface the real transport error."""
    import time as _time

    from sixmic_backend.transport.control_client import ControlClient

    client = ControlClient("127.0.0.1", 1, auto_reconnect=False)
    started = _time.monotonic()
    try:
        with pytest.raises(BackendError) as info:
            client.connect()
    finally:
        client.close()
    elapsed = _time.monotonic() - started
    assert info.value.code in ("connection_lost", "io_error")
    assert elapsed < 3.0
