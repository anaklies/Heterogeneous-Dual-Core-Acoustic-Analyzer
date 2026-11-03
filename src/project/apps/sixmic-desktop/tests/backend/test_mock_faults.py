"""Negative-path contracts using explicit fixture faults (never product data)."""
from __future__ import annotations

import time

import pytest

from sixmic_backend.errors import BackendError
from sixmic_backend.transport.binary_client import BinaryClient
from sixmic_backend.transport.control_client import ControlClient
from sixmic_backend.data.stream_dispatcher import StreamDispatcher


class _NullConsumer:
    def on_schema(self, schema):
        pass

    def on_payload(self, header, payload, schema):
        pass


def _open_binary(server):
    control = ControlClient("127.0.0.1", server.control_port, auto_reconnect=False)
    control.connect()
    control.request("subscribe", {"streams": [{"type": "resultWords"}],
                                  "deliverSchema": True})
    opened = control.request("stream.open", {})
    dispatcher = StreamDispatcher()
    dispatcher.register(1, "resultWords32", _NullConsumer())
    client = BinaryClient("127.0.0.1", opened["port"], connection_epoch=3,
                          token=opened["binaryToken"], dispatcher=dispatcher)
    client.connect()
    return control, client


def test_bad_crc_closes_binary_connection(mock_server):
    fixture = mock_server(result_frames=3, faults=("bad_crc",))
    try:
        control, client = _open_binary(fixture["server"])
    except BackendError as exc:
        # The corrupt frame may arrive in the same TCP segment as HELLO_ACK;
        # closing the connection during handshake is the correct behaviour.
        assert exc.code in ("crc_mismatch", "schema_mismatch")
        return
    try:
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and client.last_error is None:
            time.sleep(0.02)
        assert client.last_error is not None
        assert client.last_error.code == "crc_mismatch"
    finally:
        client.close()
        control.close()


def test_data_before_schema_is_rejected(mock_server):
    fixture = mock_server(faults=("data_before_schema",))
    try:
        control, client = _open_binary(fixture["server"])
    except BackendError as exc:
        assert exc.code in ("schema_mismatch", "crc_mismatch")
        return
    try:
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and client.last_error is None:
            time.sleep(0.02)
        assert client.last_error is not None
        assert client.last_error.code == "schema_mismatch"
    finally:
        client.close()
        control.close()


def test_bad_binary_token_rejected(mock_server):
    fixture = mock_server()
    control = ControlClient("127.0.0.1", fixture["controlPort"], auto_reconnect=False)
    control.connect()
    try:
        client = BinaryClient("127.0.0.1", fixture["binaryPort"], connection_epoch=3,
                              token="wrong-token")
        with pytest.raises(BackendError):
            client.connect()
        client.close()
    finally:
        control.close()


def test_wrong_epoch_rejected(mock_server):
    fixture = mock_server()
    control = ControlClient("127.0.0.1", fixture["controlPort"], auto_reconnect=False)
    control.connect()
    try:
        control.request("subscribe", {"streams": [{"type": "resultWords"}],
                                      "deliverSchema": True})
        opened = control.request("stream.open", {})
        client = BinaryClient("127.0.0.1", opened["port"], connection_epoch=999,
                              token=opened["binaryToken"])
        with pytest.raises(BackendError) as info:
            client.connect()
        assert info.value.code in ("epoch_mismatch", "bad_state",
                                   "connection_lost", "timeout")
        client.close()
    finally:
        control.close()
