"""SMA1 binary stream client: handshake, schema-first enforcement, bounded fan-out."""
from __future__ import annotations

import socket
import threading
import time
from typing import Any, Callable

from ..constants import (
    DEFAULT_BINARY_PORT, DEFAULT_MAX_BINARY_PAYLOAD, MSG_BYE, MSG_ERROR,
    MSG_HEARTBEAT, MSG_HELLO, MSG_HELLO_ACK, MSG_STREAM_SCHEMA,
)
from ..errors import BackendError
from ..protocol.framing import SmaHeader, build_frame, encode_frame
from ..protocol.messages import build_hello_payload, parse_hello_ack


class BinaryClient:
    def __init__(self, host: str, port: int = DEFAULT_BINARY_PORT, *,
                 connection_epoch: int, token: str,
                 max_payload_bytes: int = DEFAULT_MAX_BINARY_PAYLOAD,
                 dispatcher: Any = None,
                 on_close: Callable[[BackendError | None], None] | None = None,
                 connect_timeout: float = 3.0) -> None:
        self.host = host
        self.port = int(port)
        self.connection_epoch = int(connection_epoch)
        self.token = token
        self.max_payload_bytes = int(max_payload_bytes)
        self.dispatcher = dispatcher
        self.on_close = on_close
        self.connect_timeout = float(connect_timeout)
        self._socket: socket.socket | None = None
        self._reader: threading.Thread | None = None
        self._stop = threading.Event()
        self._send_lock = threading.Lock()
        self.connected = False
        self.schemas_received = 0
        self.frames = 0
        self.unknown_messages = 0
        self.last_error: BackendError | None = None
        self._ack: dict[str, Any] | None = None

    def connect(self) -> dict[str, Any]:
        sock = socket.create_connection((self.host, self.port), timeout=self.connect_timeout)
        sock.settimeout(1.0)
        self._socket = sock
        hello = build_hello_payload(connection_epoch=self.connection_epoch,
                                    token=self.token,
                                    max_payload_bytes=self.max_payload_bytes)
        payload = __import__("json").dumps(hello, separators=(",", ":")).encode("utf-8")
        frame = build_frame(MSG_HELLO, payload, connection_epoch=self.connection_epoch)
        sock.sendall(frame)
        decoder_state = bytearray()
        deadline = time.monotonic() + self.connect_timeout + 2.0
        while time.monotonic() < deadline:
            try:
                data = sock.recv(65536)
            except socket.timeout:
                continue
            if not data:
                raise BackendError("connection_lost", {"reason": "binary-hello-closed"})
            decoder_state.extend(data)
            while len(decoder_state) >= 64:
                from ..protocol.framing import FrameDecoder
                decoder = FrameDecoder(self.max_payload_bytes)
                try:
                    frames = decoder.feed(bytes(decoder_state))
                except BackendError:
                    raise
                if not frames:
                    break
                header, body = frames[0]
                consumed = 64 + header.payload_bytes
                del decoder_state[:consumed]
                if header.message_type != MSG_HELLO_ACK:
                    raise BackendError("schema_mismatch",
                                       {"reason": "expected-hello-ack",
                                        "messageType": header.message_type})
                if header.connection_epoch != self.connection_epoch:
                    raise BackendError("epoch_mismatch",
                                       {"headerEpoch": str(header.connection_epoch),
                                        "expected": str(self.connection_epoch)})
                self._ack = parse_hello_ack(body)
                negotiated = int(self._ack.get("maxPayloadBytes", self.max_payload_bytes))
                self.max_payload_bytes = min(self.max_payload_bytes, negotiated)
                self.connected = True
                self._decoder = decoder
                self._decoder.reset()
                # Bytes received after HELLO_ACK in the same segment (schemas and
                # possibly data) must not be dropped: hand them to the reader.
                self._initial_buffer = bytes(decoder_state)
                self._reader = threading.Thread(target=self._reader_loop,
                                                name="sixmic-binary", daemon=True)
                self._reader.start()
                return self._ack
        raise BackendError("timeout", {"reason": "binary-handshake"})

    def _reader_loop(self) -> None:
        from ..protocol.framing import FrameDecoder
        decoder = FrameDecoder(self.max_payload_bytes)
        error: BackendError | None = None
        initial = getattr(self, "_initial_buffer", b"")
        self._initial_buffer = b""
        try:
            if initial:
                for header, payload in decoder.feed(initial):
                    self.frames += 1
                    if self.dispatcher is not None:
                        self.dispatcher.handle(header, payload)
            while not self._stop.is_set():
                sock = self._socket
                if sock is None:
                    break
                try:
                    data = sock.recv(65536)
                except socket.timeout:
                    continue
                except OSError as exc:
                    error = BackendError("connection_lost",
                                         {"reason": "binary-recv",
                                          "detail": str(exc)[:160]})
                    break
                if not data:
                    error = BackendError("connection_lost", {"reason": "binary-peer-closed"})
                    break
                frames = decoder.feed(data)
                for header, payload in frames:
                    self.frames += 1
                    if header.connection_epoch != self.connection_epoch:
                        raise BackendError("epoch_mismatch",
                                           {"headerEpoch": str(header.connection_epoch)})
                    if header.message_type == MSG_HEARTBEAT:
                        self._send_frame(build_frame(MSG_HEARTBEAT, b"",
                                                     connection_epoch=self.connection_epoch))
                        continue
                    if header.message_type == MSG_STREAM_SCHEMA:
                        self.schemas_received += 1
                    if header.message_type == MSG_BYE:
                        error = BackendError("connection_lost", {"reason": "bye"})
                        break
                    if header.message_type == MSG_ERROR:
                        error = BackendError("io_error", {"reason": "binary-error"})
                        break
                    if self.dispatcher is None:
                        self.unknown_messages += 1
                        continue
                    try:
                        self.dispatcher.handle(header, payload)
                    except BackendError:
                        raise
                if error is not None:
                    break
        except BackendError as exc:
            error = exc
        finally:
            self.connected = False
            sock = self._socket
            self._socket = None
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
            self.last_error = error
            if self.on_close is not None:
                try:
                    self.on_close(error)
                except Exception:
                    pass

    def _send_frame(self, frame: bytes) -> None:
        with self._send_lock:
            sock = self._socket
            if sock is None:
                return
            try:
                sock.sendall(frame)
            except OSError:
                pass

    def close(self) -> None:
        self._stop.set()
        sock = self._socket
        self._socket = None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        reader = self._reader
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=2.0)
        self._reader = None
        self.connected = False

    def stats(self) -> dict[str, Any]:
        return {"host": self.host, "port": self.port, "connected": self.connected,
                "schemasReceived": self.schemas_received, "frames": self.frames,
                "unknownMessages": self.unknown_messages,
                "lastError": None if self.last_error is None else self.last_error.to_dict()}
