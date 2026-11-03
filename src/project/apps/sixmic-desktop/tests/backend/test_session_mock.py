"""End-to-end session against the deterministic fixture gateway (SIMULATED)."""
from __future__ import annotations

import hashlib
import time

import pytest

from sixmic_backend.errors import BackendError
from sixmic_backend.protocol.pcm import decode_records

BIG = 9007199254740993


def _wait(predicate, timeout=5.0, interval=0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_fixture_capabilities_are_honest(device_session_factory):
    session, server = device_session_factory()
    hello = session.connect()
    assert hello["connectionEpoch"] == "3"
    caps = session.refresh_capabilities()["device"]
    assert caps["livePcm"] == "not_ready"
    assert caps["liveResults"] == "not_ready"
    assert caps["profileUpload"] == "not_ready"
    assert caps["protocol3"] is True
    assert "no physical board" in " ".join(caps["missing"]).lower() or \
           "physical board link" in " ".join(caps["missing"]).lower()


def test_subscribe_receives_fixture_frames_and_audio(device_session_factory):
    session, server = device_session_factory(result_frames=2, pcm_chunks=2)
    session.connect()
    session.subscribe(("resultWords", "pcmRecord32"))
    assert _wait(lambda: session.frame_count >= 1 and session.audio_chunk_count >= 1)
    frame = session.last_frame
    assert frame is not None and frame.source_kind == "test-fixture"
    assert frame.sample_index == BIG
    assert frame.to_dict()["sampleIndex"] == str(BIG)
    assert frame.sample_rate_hz == pytest.approx(48009.7734375, abs=1e-6)
    chunk = session._first_audio_chunk
    assert chunk is not None and chunk.source_kind == "test-fixture"
    assert decode_records(chunk.records)[0].sample_index == BIG
    assert chunk.sample_rate_hz == pytest.approx(48009.775390625, abs=1e-9)
    # The latest audio buffer stays addressable for bounded display extraction.
    handle = session.latest_audio_handle()
    assert handle is not None
    view = session.read_buffer(handle, 0, 32)  # uint8 elements => 32 bytes = 1 record
    assert len(view) == 32
    assert decode_records(view)[0].sample_index == session.last_audio.first_sample_index


def test_single_controller_conflict(device_session_factory, user_dirs, protocol_root):
    from sixmic_backend.session import DeviceSession
    session, server = device_session_factory()
    session.connect()
    session.claim_control()
    other = DeviceSession(host="127.0.0.1", control_port=server.control_port,
                          binary_port=server.binary_port,
                          protocol_root=protocol_root, user_dirs=user_dirs,
                          auto_reconnect=False)
    try:
        other.connect()
        with pytest.raises(BackendError) as info:
            other.claim_control()
        assert info.value.code == "control_conflict"
        assert "holder" in info.value.detail
    finally:
        other.close()
    session.release_control()


def test_job_accepted_is_not_completed_and_deduped(device_session_factory):
    session, server = device_session_factory()
    session.connect()
    session.claim_control()
    first = session.start_job("p2OneShot", {"clientTaskKey": "key-1"})
    assert first["responseStatus"] == "accepted"
    duplicate = session.start_job("p2OneShot", {"clientTaskKey": "key-1"})
    assert duplicate["jobId"] == first["jobId"] and duplicate["duplicate"] is True
    job = session.jobs.get(first["jobId"])
    assert job.state in ("accepted", "running", "completed")
    assert _wait(lambda: session.refresh_job(first["jobId"])["state"] == "completed")
    with pytest.raises(BackendError) as info:
        session.cancel_job(first["jobId"])
    assert info.value.code == "bad_state"


def test_control_required_for_jobs(device_session_factory):
    session, server = device_session_factory()
    session.connect()
    with pytest.raises(BackendError) as info:
        session.start_job("p1Carousel")
    assert info.value.code == "control_not_held"


def test_recording_requires_pcm_subscription(device_session_factory):
    session, server = device_session_factory()
    session.connect()
    with pytest.raises(BackendError) as info:
        session.start_recording("rec-x")
    assert info.value.code == "bad_state"


def test_recording_and_manifest(device_session_factory):
    session, server = device_session_factory(result_frames=1, pcm_chunks=2)
    session.connect()
    session.claim_control()
    session.subscribe(("resultWords", "pcmRecord32"))
    assert _wait(lambda: session.audio_chunk_count >= 2)
    session.start_recording("rec-fixture")
    assert _wait(lambda: session.recorder is not None and session.recorder.records >= 3)
    status = session.stop_recording()
    assert status["state"] == "stopped" and status["records"] >= 3
    manifest = session.recorder.manifest.to_dict()
    assert manifest["sourceKind"] == "test-fixture"
    assert manifest["realSampleRateHz"] == pytest.approx(48009.775390625)
    assert manifest["integerRateHz"] == 48010
    assert abs(manifest["rateRoundingErrorHz"] - (48010 - 48009.775390625)) < 1e-9
    assert manifest["wav"]["channelCount"] == 6
    from sixmic_backend.model.audio import verify_manifest_files
    assert verify_manifest_files(manifest)["ok"] is True
    assert len(session.storage.list_recordings()) >= 1


def test_event_list_download_and_idempotent_ack(device_session_factory):
    session, server = device_session_factory()
    session.connect()
    events = session.list_events()
    assert events and events[0]["eventId"] == "7"
    downloaded = session.download_event(7)
    assert len(downloaded["sha256"]) == 64
    manifest = __import__("json").loads(
        __import__("pathlib").Path(downloaded["path"]).parent
        .joinpath("manifest.json").read_text(encoding="utf-8"))
    assert manifest["recordCount"] == 2
    assert hashlib.sha256(
        __import__("pathlib").Path(downloaded["path"]).read_bytes()).hexdigest() == \
        downloaded["sha256"]
    again = session.event_manager.ack(7, downloaded["sha256"])
    assert again["duplicate"] is True


def test_stream_gap_is_explicit(device_session_factory):
    session, server = device_session_factory(result_frames=1, pcm_chunks=1,
                                             faults=("gap",))
    session.connect()
    session.subscribe(("resultWords", "pcmRecord32"))
    assert _wait(lambda: session.dispatcher is not None and
                 any(state.gap_events for state in session.dispatcher.states().values()))
    states = session.dispatcher.states()
    assert any(state.dropped_records >= 1 for state in states.values())


def test_live_mode_never_falls_back_to_fixture_values(device_session_factory):
    session, server = device_session_factory()
    session.connect()
    session.subscribe(("resultWords",))
    assert _wait(lambda: session.frame_count >= 1)
    frame = session.last_frame
    assert frame is not None
    # The fixture markers must not be upgraded to pl-live by the backend.
    assert frame.source_kind == "test-fixture"
    assert session.capabilities.live_pcm != "available"


def test_pcm_consumer_reports_forward_missing_range():
    """F-04: chunk discontinuity metadata must describe a forward missing range."""
    import types

    from sixmic_backend.protocol.pcm import PcmRecord, encode_records
    from sixmic_backend.session import _PcmConsumer

    chunks: list = []

    class Sink:
        session_id = "s"

        def _on_audio_chunk(self, chunk):
            chunks.append(chunk)

    consumer = _PcmConsumer(Sink())
    consumer.on_schema({"sourceKind": "test-fixture", "deviceId": "d",
                        "connectionEpoch": "0",
                        "pcm": {"sampleRateHz": 48000.0, "channels": 6}})
    header = types.SimpleNamespace(stream_id=2, gap_before=False,
                                   device_monotonic_ns=0,
                                   device_monotonic_valid=False)
    consumer.on_payload(header, encode_records(
        [PcmRecord((0,) * 6, index) for index in range(4)]), {})
    consumer.on_payload(header, encode_records(
        [PcmRecord((0,) * 6, index) for index in range(8, 12)]), {})
    gap = chunks[1].continuity["gaps"][0]
    assert chunks[1].gap_before is True
    assert gap["firstMissingSampleIndex"] == "4"
    assert gap["lastMissingSampleIndex"] == "7"


def test_download_event_restores_previous_live_subscription(device_session_factory):
    """F-09: an event download must not leave live result/PCM unsubscribed."""
    session, server = device_session_factory(result_frames=1, pcm_chunks=2)
    session.connect()
    session.subscribe(("resultWords", "pcmRecord32"))
    assert _wait(lambda: session.audio_chunk_count >= 1)
    downloaded = session.download_event(7)
    assert downloaded["sha256"]
    assert session.subscription is not None
    assert session.subscription["requested"] == ["resultWords", "pcmRecord32"]
    # The restored subscription is live again: fresh PCM keeps arriving.
    before = session.audio_chunk_count
    assert _wait(lambda: session.audio_chunk_count > before)
