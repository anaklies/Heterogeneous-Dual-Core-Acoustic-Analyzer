"""Record -> close -> reopen -> replay: arrays, time base, units, hashes agree."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from sixmic_backend.constants import CANDIDATE_SAMPLE_RATE_FLOAT32_HZ, CANDIDATE_SAMPLE_RATE_HZ
from sixmic_backend.data.recording import Recorder, load_recording
from sixmic_backend.data.replay import ReplaySession
from sixmic_backend.errors import BackendError
from sixmic_backend.model.audio import read_24bit_wav, verify_manifest_files
from sixmic_backend.model.dto import RecordingManifest
from sixmic_backend.protocol.event_file import parse_event_container
from sixmic_backend.protocol.event_file import build_event_container
from sixmic_backend.protocol.pcm import PcmRecord, decode_records, encode_record

BIG = 9007199254740993


def _record(directory: Path) -> tuple[Recorder, list[PcmRecord]]:
    recorder = Recorder(directory, recording_id="rec-1", device_id="unit-test",
                        connection_epoch=3, session_id="sess-3",
                        source_kind="test-fixture",
                        real_sample_rate_hz=CANDIDATE_SAMPLE_RATE_HZ,
                        max_segment_bytes=2048, max_total_bytes=5 * 1024 * 1024)
    recorder.start()
    records: list[PcmRecord] = []
    # chunk offsets deliberately leave a 5-sample hole (BIG+25..BIG+29) after the
    # first chunk so the gap must surface in the manifest and replay.
    offsets = [0, 30, 55, 80]
    for position, base_index in enumerate(offsets):
        if position == 1:
            recorder.append_gap({"reason": "queue_overflow",
                                 "firstMissingSampleIndex": str(BIG + 25),
                                 "lastMissingSampleIndex": str(BIG + 29),
                                 "droppedRecords": "5"})
        chunk_records = []
        for index in range(25):
            values = tuple(((position * 25 + index + channel * 7) % 500) - 250
                           for channel in range(6))
            record = PcmRecord(values, BIG + base_index + index)
            chunk_records.append(record)
            records.append(record)
        recorder.append_audio(b"".join(record.to_bytes() for record in chunk_records),
                              first_sample_index=BIG + base_index)
    recorder.stop()
    return recorder, records


def test_record_close_reopen_replay_equality(tmp_path: Path):
    recorder, original = _record(tmp_path / "rec-1")
    manifest = recorder.manifest.to_dict()
    assert int(manifest["records"]) == len(original)
    assert manifest["gaps"][0]["droppedRecords"] == "5"
    assert manifest["realSampleRateHz"] == CANDIDATE_SAMPLE_RATE_HZ
    assert manifest["integerRateHz"] == 48010
    assert manifest["rateRoundingErrorHz"] == pytest.approx(48010 - CANDIDATE_SAMPLE_RATE_HZ)
    assert manifest["wav"]["integerRateHz"] == 48010
    assert manifest["sampleFormat"] == "int24-le-signextended-in-int32"
    assert verify_manifest_files(manifest)["ok"]
    assert hashlib.sha256((tmp_path / "rec-1" / "manifest.json").read_bytes()).hexdigest()

    replay = ReplaySession(tmp_path / "rec-1" / "manifest.json")
    replay.set_state("playing")
    collected: list[PcmRecord] = []
    while True:
        chunk = replay.next_chunk(max_records=32)
        if chunk is None:
            break
        assert chunk.source_kind == "file-replay"
        assert chunk.sample_rate_hz == CANDIDATE_SAMPLE_RATE_HZ
        collected.extend(decode_records(chunk.records))
    assert collected == original

    # arrays + time base + units agree with the WAV export
    wav_records, wav_info = read_24bit_wav(manifest["wav"]["path"])
    assert [record.samples for record in decode_records(wav_records)] == \
        [record.samples for record in original]
    assert wav_info["sampleRate"] == 48010
    assert [record.sample_index for record in original] == \
        [record.sample_index for record in collected]


def test_replay_seek_and_state(tmp_path: Path):
    recorder, original = _record(tmp_path / "rec-1")
    replay = ReplaySession(tmp_path / "rec-1" / "manifest.json")
    status = replay.seek(BIG + 40)
    assert status["position"] == BIG + 40
    replay.set_state("playing")
    chunk = replay.next_chunk(max_records=10)
    assert chunk is not None
    assert decode_records(chunk.records)[0].sample_index == BIG + 40
    replay.set_state("paused")
    assert replay.next_chunk() is None
    replay.set_state("stopped")
    assert replay.status()["position"] == 0
    with pytest.raises(BackendError):
        replay.seek(BIG + 10_000)


def test_corrupt_segment_detected_on_open(tmp_path: Path):
    recorder, _ = _record(tmp_path / "rec-1")
    segment = Path(recorder.segments[0]["path"])
    segment.write_bytes(segment.read_bytes()[:-32])
    with pytest.raises(BackendError) as info:
        ReplaySession(tmp_path / "rec-1" / "manifest.json")
    assert info.value.code == "file_corrupt"


def test_gap_not_silently_compressed(tmp_path: Path):
    recorder, _ = _record(tmp_path / "rec-1")
    manifest = load_recording(tmp_path / "rec-1")["manifest"]
    assert manifest["gaps"], "gap must remain explicit in the manifest"
    replay = ReplaySession(tmp_path / "rec-1" / "manifest.json")
    replay.set_state("playing")
    gap_chunk = None
    while True:
        chunk = replay.next_chunk(max_records=20)
        if chunk is None:
            break
        if chunk.continuity.get("gaps"):
            gap_chunk = chunk
            break
    assert gap_chunk is not None, "chunk containing the hole must be delivered"
    assert gap_chunk.gap_before is True
    assert gap_chunk.continuity["continuous"] is False
    assert gap_chunk.continuity["gaps"][0]["droppedRecords"] == "5"


def test_manifest_roundtrip_hash_and_validation(tmp_path: Path):
    from dataclasses import replace
    recorder, _ = _record(tmp_path / "rec-1")
    manifest = recorder.manifest
    assert manifest.sha256 == manifest.compute_sha256()
    assert manifest.to_dict()["sha256"] == manifest.sha256
    tampered = replace(manifest, records=manifest.records + 1)
    with pytest.raises(BackendError):
        tampered.validate()
    bad_rate = replace(manifest, integer_rate_hz=0)
    with pytest.raises(BackendError):
        bad_rate.validate()


def test_event_manifest_store(tmp_path: Path):
    from sixmic_backend.data.events import EventManager
    manager = EventManager(tmp_path / "events")
    metadata = {"eventId": "7", "deviceId": "unit", "connectionEpoch": "3",
                "sessionId": "s", "sourceKind": "test-fixture",
                "capturedFirstSampleIndex": str(BIG),
                "capturedLastSampleIndex": str(BIG + 1), "frames": 2,
                "sampleRateHz": 48009.775390625, "clipReason": 5,
                "flags": {"incomplete": False, "lostEvents": False,
                          "summaryStale": False, "envInvalid": False,
                          "poseInvalid": False},
                "file": {"state": "known"}}
    manager.ingest_known(metadata)
    container = build_event_container(
        event_id=7, flags=1, clip_reason=5, first_sample_index=BIG,
        last_sample_index=BIG + 1, sample_rate_hz=48009.775390625,
        records=b"".join(encode_record([1, 2, 3, 4, 5, 6], BIG + i).encode()
                         if False else encode_record([1, 2, 3, 4, 5, 6], BIG + i)
                         for i in range(2)))
    info = manager.store_downloaded(7, container)
    assert info["sha256"] == hashlib.sha256(container).hexdigest()
    parse_event_container(Path(info["path"]).read_bytes())
    ack = manager.ack(7, info["sha256"])
    assert ack["acked"] is True and ack["duplicate"] is False
    again = manager.ack(7, info["sha256"])
    assert again["duplicate"] is True


def test_real_sample_rate_rounding_is_recorded(tmp_path: Path):
    recorder = Recorder(tmp_path / "rec", recording_id="r", device_id="d",
                        connection_epoch=1, session_id="s",
                        source_kind="test-fixture",
                        real_sample_rate_hz=CANDIDATE_SAMPLE_RATE_FLOAT32_HZ)
    recorder.start()
    recorder.append_audio(encode_record([0] * 6, 1), first_sample_index=1)
    recorder.stop()
    manifest = recorder.manifest
    assert manifest.integer_rate_hz == 48010
    assert manifest.rate_rounding_error_hz == pytest.approx(48010 - 48009.7734375)


def _export_session(tmp_path: Path, name: str = "rec") -> tuple[object, dict]:
    """Build a real recorder and attach it to a DeviceSession-shaped exporter."""
    from sixmic_backend.session import DeviceSession

    recorder = Recorder(tmp_path / name, recording_id="rec-export", device_id="d",
                        connection_epoch=1, session_id="s",
                        source_kind="test-fixture",
                        real_sample_rate_hz=CANDIDATE_SAMPLE_RATE_HZ)
    recorder.start()
    recorder.append_audio(b"".join(encode_record([0, 1, 2, 3, 4, 5], index)
                                   for index in range(4)))
    recorder.stop()
    session = DeviceSession.__new__(DeviceSession)
    session.paths = {"exports": tmp_path / "exports"}
    session.recorder = recorder
    session.replay = None
    return session, recorder


def test_export_csv_and_manifest_contain_real_newlines(tmp_path: Path):
    """F-01: exported CSV and manifest.json must not contain literal backslash-n."""
    session, recorder = _export_session(tmp_path)
    paths = session.export_data(tmp_path / "export-out")
    csv_bytes = Path(paths["csv"]).read_bytes()
    assert b"\\n" not in csv_bytes  # literal backslash-n must be gone
    assert b"\n" in csv_bytes
    csv_lines = csv_bytes.decode("utf-8").splitlines()
    assert len(csv_lines) == 12  # header + 10 documented fields + gaps
    manifest_bytes = Path(paths["manifest"]).read_bytes()
    assert b"\\n" not in manifest_bytes
    assert b"\n" in manifest_bytes
    manifest = json.loads(Path(paths["manifest"]).read_text(encoding="utf-8"))
    assert manifest["recordingId"] == "rec-export"
    assert manifest["gaps"] == []


def test_default_export_directories_do_not_collide(tmp_path: Path):
    """F-08: two exports within the same second must not overwrite each other."""
    session, recorder = _export_session(tmp_path)
    first = session.export_data()
    second = session.export_data()
    assert Path(first["csv"]).parent != Path(second["csv"]).parent
    assert Path(first["csv"]).is_file() and Path(second["csv"]).is_file()


def test_documented_gap_between_segments_still_verifies(tmp_path: Path):
    """F-05: a manifest-documented gap is not corruption."""
    recorder = Recorder(tmp_path / "gapped", recording_id="rec-gap", device_id="d",
                        connection_epoch=1, session_id="s",
                        source_kind="test-fixture",
                        real_sample_rate_hz=CANDIDATE_SAMPLE_RATE_HZ,
                        max_segment_bytes=256 * 32)
    recorder.start()
    recorder.append_audio(b"".join(encode_record([0] * 6, index)
                                   for index in range(256)))
    recorder.append_audio(b"".join(encode_record([0] * 6, index)
                                   for index in range(1000, 1256)))
    recorder.stop()
    manifest = recorder.manifest.to_dict()
    assert len(manifest["segments"]) == 2
    assert manifest["gaps"] == [{"reason": "recording_discontinuity",
                                 "firstMissingSampleIndex": "256",
                                 "lastMissingSampleIndex": "999",
                                 "droppedRecords": "744"}]
    verification = verify_manifest_files(manifest)
    assert verification["ok"] is True
    assert all(segment["ok"] for segment in verification["segments"])
    # An undocumented hole is still reported as corruption.
    tampered = json.loads(json.dumps(manifest))
    tampered["gaps"] = []
    assert verify_manifest_files(tampered)["ok"] is False
