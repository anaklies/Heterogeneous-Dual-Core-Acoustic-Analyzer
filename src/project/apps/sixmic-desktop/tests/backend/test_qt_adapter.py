"""Qt adapter: async slots return requestId, signals carry JSON with u64 strings."""
from __future__ import annotations

import json
import time

import pytest

pyside = pytest.importorskip("PySide6", reason="PySide6 not installed in this environment")

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402

from sixmic_backend.qt.adapter import BackendBridge, EventListModel, QT_AVAILABLE  # noqa: E402


@pytest.fixture(scope="module")
def app():
    application = QCoreApplication.instance() or QCoreApplication([])
    yield application


def _process(app, seconds: float = 0.05):
    loop = QEventLoop()
    QTimer.singleShot(int(seconds * 1000), loop.quit)
    loop.exec()


def test_bridge_properties_and_async_slots(app):
    assert QT_AVAILABLE is True
    bridge = BackendBridge()
    assert bridge.backendVersion
    request_id = bridge.connectDevice("127.0.0.1", 1, 1)
    assert request_id.startswith("ui-")
    received: list[str] = []
    bridge.requestFinished.connect(received.append)
    bridge.backendError.connect(received.append)
    deadline = time.monotonic() + 25.0
    while time.monotonic() < deadline and not received:
        _process(app, 0.02)
    assert received, "async slot must report completion/error"
    payload = json.loads(received[0])
    assert payload["requestId"] == request_id
    assert payload["op"] == "connectDevice"
    assert payload["status"] == "error"
    assert payload["error"]["code"] in ("timeout", "io_error", "connection_lost",
                                        "not_connected")
    bridge.shutdown()


def test_u64_stays_string_on_signal(app, mock_server, protocol_root, user_dirs):
    from sixmic_backend.session import DeviceSession
    fixture = mock_server(result_frames=1, pcm_chunks=1)
    bridge = BackendBridge(protocol_root=str(protocol_root))
    session = DeviceSession(host="127.0.0.1", control_port=fixture["controlPort"],
                            binary_port=fixture["binaryPort"],
                            protocol_root=protocol_root, user_dirs=user_dirs,
                            auto_reconnect=False)
    bridge.attachSession(session)
    frames: list[str] = []
    bridge.frameAvailable.connect(frames.append)
    try:
        session.connect()
        session.subscribe(("resultWords",))
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            _process(app, 0.02)
            if frames:
                break
        assert frames
        payload = json.loads(frames[0])
        assert isinstance(payload["sampleIndex"], str)
        assert payload["sampleIndex"] == "9007199254740993"
        assert payload["sourceKind"] == "test-fixture"
    finally:
        session.close()
        bridge.shutdown()


def test_event_list_model_roles_and_bounds(app):
    model = EventListModel()
    assert model.roleNames()
    for index in range(600):
        model.add({"index": index}, f"row {index}")
    assert model.rowCount() == model.MAX_ROWS


def test_qt_unavailable_is_reported(monkeypatch):
    from sixmic_backend.errors import BackendError
    from sixmic_backend.qt import adapter
    if adapter.QT_AVAILABLE:
        pytest.skip("Qt is available")
    with pytest.raises(BackendError):
        adapter.create_bridge()
