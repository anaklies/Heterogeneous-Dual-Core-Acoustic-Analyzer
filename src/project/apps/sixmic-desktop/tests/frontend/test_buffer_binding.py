"""Buffer binding contract: element widths, offsets, expiry, six-channel order.

The adapter readBuffer is a synchronous bounded call (not a requestId slot):
    readBuffer(handleId, offsetElements=0, countElements=4096) -> QByteArray
data_store converts element offsets to byte offsets by elementType width.
"""
from __future__ import annotations

import time

import pytest

from sixmic_backend.protocol.pcm import decode_records

BIG = 9007199254740993


def _wait(application, predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        application.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture()
def live_session(qapp, protocol_root, user_dirs):
    from sixmic_backend.qt.adapter import create_bridge
    from sixmic_backend.testing.mock_ps_server import MockPsServer

    server = MockPsServer(result_frames=1, pcm_chunks=2, stream_seconds=6.0)
    info = server.start()
    bridge = create_bridge(protocol_root=str(protocol_root))
    request = bridge.connectDevice("127.0.0.1", info["controlPort"], info["binaryPort"])
    assert _wait(qapp, lambda: bridge._session is not None and
                 bridge._session.state == "connected", 8.0)
    bridge.subscribe('["resultWords","pcmRecord32"]')
    session = bridge._session
    assert _wait(qapp, lambda: session.audio_chunk_count >= 1, 8.0)
    yield bridge, session, server
    try:
        bridge.shutdown()
    finally:
        server.stop()


def test_read_buffer_element_widths(live_session, qapp):
    bridge, session, server = live_session
    store = session.data_store
    import struct
    for element_type, data in (
            ("uint8", bytes(range(16))),
            ("int32", b"".join(int(i).to_bytes(4, "little", signed=True)
                               for i in range(-4, 4))),
            ("float32", struct.pack("<4f", 1.0, 2.0, 3.5, -4.25))):
        handle = store.put(data, element_type)
        try:
            width = {"uint8": 1, "int32": 4, "float32": 4}[element_type]
            count = len(data) // width
            full = bytes(bridge.readBuffer(handle, 0, count))
            assert full == data
            offset = 2
            take = max(1, count - offset)
            sliced = bytes(bridge.readBuffer(handle, offset, take))
            assert sliced == data[offset * width:(offset + take) * width]
        finally:
            store.release(handle)


def test_read_buffer_expired_handle_returns_empty(live_session, qapp):
    bridge, session, server = live_session
    first_handle = session.latest_audio_handle()
    assert first_handle is not None
    # Wait for the next audio chunk: the previous display handle must be released.
    before = session.audio_chunk_count
    assert _wait(qapp, lambda: session.audio_chunk_count > before, 6.0)
    assert session.latest_audio_handle() != first_handle
    assert bytes(bridge.readBuffer(first_handle, 0, 32)) == b""


def test_six_channel_order_and_sign_extension(live_session, qapp):
    bridge, session, server = live_session
    handle = session.latest_audio_handle()
    raw = bytes(bridge.readBuffer(handle, 0, 32 * 3))
    records = decode_records(raw)
    # The fixture's deterministic first record: min, max, -1, 0, 1, -2.
    assert records[0].samples[0] == -8388608
    assert records[0].samples[1] == 8388607
    assert records[0].samples[2] == -1
    assert records[0].samples[3] == 0
    assert records[0].samples[4] == 1
    assert records[0].samples[5] == -2
    # Records are 32 bytes: 6 x int32 sign-extended 24-bit + uint64 sample index.
    assert all(len(record.samples) == 6 for record in records)
    assert records[0].sample_index >= BIG


def test_u64_strings_are_preserved(live_session, qapp):
    bridge, session, server = live_session
    assert _wait(qapp, lambda: session.frame_count >= 1, 6.0)
    frame = session.last_frame
    payload = frame.to_dict()
    assert isinstance(payload["sampleIndex"], str)
    assert int(payload["sampleIndex"]) == BIG
    assert isinstance(payload["connectionEpoch"], str)
    assert payload["sampleIndex"] != str(float(BIG))  # no float round-trip
