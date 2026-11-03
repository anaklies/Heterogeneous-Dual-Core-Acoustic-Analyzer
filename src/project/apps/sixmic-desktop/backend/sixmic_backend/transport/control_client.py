"""TCP JSON-lines control client with handshake, dedup-safe requests and reconnect.

No command is replayed after reconnect: the caller (DeviceSession) re-reads
capabilities/status and re-subscribes explicitly.
"""
from __future__ import annotations

import queue
import random
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ..constants import (
    DEFAULT_CONTROL_PORT, DEFAULT_CONTROL_LEASE_SECONDS, MAX_LINE_BYTES,
)
from ..errors import BackendError
from ..protocol.control import (
    build_request, parse_u64, validate_event, validate_response,
)
from ..protocol.jsonline import LineDecoder, encode_line


@dataclass
class _Pending:
    event: threading.Event = field(default_factory=threading.Event)
    payload: dict[str, Any] | None = None
    error: BackendError | None = None


class ControlClient:
    def __init__(self, host: str, port: int = DEFAULT_CONTROL_PORT, *,
                 connect_timeout: float = 3.0, request_timeout: float = 5.0,
                 client_name: str = "SixMic3D-PC",
                 client_version: str = "0.1.0",
                 max_binary_payload: int = 1048576,
                 auto_reconnect: bool = True,
                 lease_seconds: int = DEFAULT_CONTROL_LEASE_SECONDS,
                 logger: Callable[[str, dict[str, Any]], None] | None = None) -> None:
        self.host = host
        self.port = int(port)
        self.connect_timeout = float(connect_timeout)
        self.request_timeout = float(request_timeout)
        self.client_name = client_name
        self.client_version = client_version
        self.max_binary_payload = int(max_binary_payload)
        self.auto_reconnect = bool(auto_reconnect)
        self.lease_seconds = int(lease_seconds)
        self._logger = logger or (lambda level, detail: None)
        self._socket: socket.socket | None = None
        self._reader: threading.Thread | None = None
        self._stop = threading.Event()
        self._connected = threading.Event()
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._pending: dict[str, _Pending] = {}
        self._counter = 0
        self._session_id: str | None = None
        self._connection_epoch: int | None = None
        self._hello: dict[str, Any] | None = None
        self._events: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=256)
        self._state_callbacks: list[Callable[[str, dict[str, Any]], None]] = []
        self._event_callbacks: list[Callable[[str, int, dict[str, Any]], None]] = []
        self._last_heartbeat = 0.0
        self.reconnects = 0
        self.dropped_events = 0
        self.last_error: BackendError | None = None

    # -- public ------------------------------------------------------------
    def add_state_listener(self, callback: Callable[[str, dict[str, Any]], None]) -> None:
        self._state_callbacks.append(callback)

    def add_event_listener(self, callback: Callable[[str, int, dict[str, Any]], None]) -> None:
        self._event_callbacks.append(callback)

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def connection_epoch(self) -> int | None:
        return self._connection_epoch

    @property
    def hello(self) -> dict[str, Any] | None:
        return self._hello

    def connect(self, timeout: float | None = None) -> dict[str, Any]:
        self._stop.clear()
        self._start_reader()
        wait = self.connect_timeout if timeout is None else float(timeout)
        deadline = time.monotonic() + wait + self.request_timeout
        while not self._connected.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if self._connected.wait(min(0.05, remaining)):
                break
            reader = self._reader
            if self.last_error is not None and (reader is None or not reader.is_alive()):
                # Refused/unreachable peer: the reader already recorded the real
                # reason; do not wait out the whole handshake budget.
                break
        if not self._connected.is_set():
            error = self.last_error
            self._emit_state("failed", {"reason": "handshake-timeout",
                                        "host": self.host, "port": self.port})
            self.close()
            if error is not None:
                raise error
            raise BackendError("timeout", {"reason": "control-handshake"})
        return dict(self._hello or {})

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
        self._fail_pending(BackendError("connection_lost", {"reason": "closed"}))
        reader = self._reader
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=3.0)
        self._reader = None
        self._connected.clear()

    def request(self, op: str, args: dict[str, Any] | None = None,
                timeout: float | None = None) -> dict[str, Any]:
        if not self._connected.is_set():
            raise BackendError("not_connected", {"reason": "control-client"})
        return self._transact(op, args, timeout)

    def _transact(self, op: str, args: dict[str, Any] | None = None,
                  timeout: float | None = None) -> dict[str, Any]:
        """Send one request and wait for its response (also used during handshake)."""
        request_id = self._next_request_id()
        payload = build_request(op, request_id, self._session_id, args or {})
        pending = _Pending()
        with self._lock:
            self._pending[request_id] = pending
        try:
            self._send(encode_line(payload))
        except OSError as exc:
            with self._lock:
                self._pending.pop(request_id, None)
            raise BackendError("io_error", {"reason": "send", "detail": str(exc)}) from exc
        wait = self.request_timeout if timeout is None else float(timeout)
        if not pending.event.wait(wait):
            with self._lock:
                self._pending.pop(request_id, None)
            raise BackendError("timeout", {"op": op, "requestId": request_id})
        if pending.error is not None:
            raise pending.error
        response = pending.payload or {}
        status = response.get("status")
        if status == "error":
            error = response.get("error") or {}
            raise BackendError(str(error.get("code", "internal_error")),
                               dict(error.get("detail") or {}),
                               message_key=error.get("messageKey"),
                               retryable=bool(error.get("retryable", False)))
        result = dict(response.get("result") or {})
        result["requestId"] = request_id
        result["responseStatus"] = status
        return result

    def drain_events(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                return events

    def stats(self) -> dict[str, Any]:
        return {"host": self.host, "port": self.port,
                "connected": self._connected.is_set(),
                "sessionId": self._session_id,
                "connectionEpoch": None if self._connection_epoch is None
                else str(self._connection_epoch),
                "reconnects": self.reconnects,
                "pending": len(self._pending),
                "droppedEvents": self.dropped_events,
                "lastError": None if self.last_error is None else self.last_error.to_dict()}

    # -- internals ---------------------------------------------------------
    def _next_request_id(self) -> str:
        with self._lock:
            self._counter += 1
            return f"pc-{self._counter:08d}"

    def _emit_state(self, state: str, detail: dict[str, Any]) -> None:
        for callback in list(self._state_callbacks):
            try:
                callback(state, detail)
            except Exception:  # listener errors must not kill the reader thread
                self._logger("error", {"event": "state-listener", "state": state})

    def _start_reader(self) -> None:
        if self._reader is not None and self._reader.is_alive():
            return
        self._reader = threading.Thread(target=self._reader_loop,
                                        name="sixmic-control", daemon=True)
        self._reader.start()

    def _send(self, data: bytes) -> None:
        with self._write_lock:
            sock = self._socket
            if sock is None:
                raise OSError("not connected")
            sock.sendall(data)

    def _reader_loop(self) -> None:
        backoff = 0.5
        first = True
        while not self._stop.is_set():
            sock: socket.socket | None = None
            try:
                self._emit_state("connecting", {"host": self.host, "port": self.port})
                sock = socket.create_connection((self.host, self.port),
                                                timeout=self.connect_timeout)
                sock.settimeout(1.0)
                with self._lock:
                    self._socket = sock
                self._decoder = LineDecoder(MAX_LINE_BYTES)
                self._emit_state("handshaking", {"host": self.host, "port": self.port})
                hello = self._handshake(sock)
                self._session_id = hello.get("sessionId")
                self._connection_epoch = parse_u64(hello.get("connectionEpoch"), "connectionEpoch")
                self._hello = hello
                self._connected.set()
                self._last_heartbeat = time.monotonic()
                backoff = 0.5
                self._emit_state("connected", {"sessionId": self._session_id,
                                               "connectionEpoch": str(self._connection_epoch)})
                first = False
                buffered = bytearray()
                while not self._stop.is_set():
                    try:
                        data = sock.recv(65536)
                    except socket.timeout:
                        self._maybe_heartbeat()
                        continue
                    if not data:
                        raise ConnectionError("control-peer-closed")
                    buffered.extend(data)
                    if len(buffered) > MAX_LINE_BYTES * 4:
                        raise BackendError("line_too_long", {"buffered": len(buffered)})
                    for message in self._decoder.feed(bytes(buffered)):
                        self._handle_message(message)
                    buffered.clear()
            except BackendError as exc:
                self.last_error = exc
                self._emit_state("degraded", {"error": exc.to_dict()})
            except (OSError, ConnectionError) as exc:
                if not self._stop.is_set():
                    self.last_error = BackendError("connection_lost",
                                                   {"detail": str(exc)[:200]})
            finally:
                was_connected = self._connected.is_set()
                self._connected.clear()
                with self._lock:
                    if self._socket is sock:
                        self._socket = None
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
                self._fail_pending(BackendError("connection_lost",
                                                {"reason": "control-disconnected"}))
                if was_connected:
                    self._emit_state("disconnected", {})
            if self._stop.is_set():
                break
            if not self.auto_reconnect or first:
                break
            self.reconnects += 1
            self._emit_state("reconnecting", {"attempt": self.reconnects,
                                              "backoffSeconds": backoff})
            delay = backoff * (0.8 + 0.4 * random.random())
            if self._stop.wait(delay):
                break
            backoff = min(15.0, backoff * 2)
        self._connected.clear()

    def _handshake(self, sock: socket.socket) -> dict[str, Any]:
        """Send hello and pump the socket inline (the reader thread owns it)."""
        request_id = self._next_request_id()
        pending = _Pending()
        with self._lock:
            self._pending[request_id] = pending
        payload = build_request("hello", request_id, None, {
            "clientName": self.client_name,
            "clientVersion": self.client_version,
            "maxBinaryPayloadBytes": self.max_binary_payload,
        })
        self._send(encode_line(payload))
        deadline = time.monotonic() + self.request_timeout * 2
        while not pending.event.is_set():
            if time.monotonic() > deadline:
                with self._lock:
                    self._pending.pop(request_id, None)
                raise BackendError("timeout", {"reason": "control-handshake"})
            try:
                data = sock.recv(65536)
            except socket.timeout:
                continue
            if not data:
                raise ConnectionError("control-peer-closed-during-handshake")
            for message in self._decoder.feed(data):
                self._handle_message(message)
        if pending.error is not None:
            raise pending.error
        response = pending.payload or {}
        if response.get("status") == "error":
            error = response.get("error") or {}
            raise BackendError(str(error.get("code", "internal_error")),
                               dict(error.get("detail") or {}),
                               message_key=error.get("messageKey"))
        return dict(response.get("result") or {})

    def _handle_message(self, message: dict[str, Any]) -> None:
        if message.get("type") == "response":
            request_id = str(message.get("requestId", ""))
            with self._lock:
                pending = self._pending.pop(request_id, None)
            if pending is None:
                return
            pending.payload = message
            pending.event.set()
            return
        try:
            name, event_id, data = validate_event(message)
        except BackendError as exc:
            self._logger("warning", {"event": "invalid-event", "error": exc.code})
            return
        for callback in list(self._event_callbacks):
            try:
                callback(name, event_id, data)
            except Exception:
                self._logger("error", {"event": "event-listener", "name": name})
        try:
            self._events.put_nowait(message)
        except queue.Full:
            self.dropped_events += 1

    def _maybe_heartbeat(self) -> None:
        now = time.monotonic()
        interval = max(1.0, min(self.lease_seconds / 2.0, 10.0))
        if now - self._last_heartbeat < interval:
            return
        self._last_heartbeat = now
        request_id = self._next_request_id()
        try:
            self._send(encode_line(build_request("heartbeat", request_id,
                                                 self._session_id, {})))
        except OSError:
            return

    def _fail_pending(self, error: BackendError) -> None:
        with self._lock:
            pending_items = list(self._pending.values())
            self._pending.clear()
        for pending in pending_items:
            pending.error = error
            pending.event.set()
