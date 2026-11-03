"""Deterministic sixmic-analysis v1 test server (SIMULATED; not a device).

Purpose: contract/integration tests for the PC backend without a board.
All data is marked test-fixture/simulated. This module is never imported by
product runtime paths and never claims pl-live.
"""
from __future__ import annotations

import hashlib
import json
import socket
import struct
import threading
import time
from pathlib import Path
from typing import Any

from ..constants import (
    CANDIDATE_SAMPLE_RATE_BITS, FLAG_FIRST_CHUNK, FLAG_GAP_BEFORE, FLAG_LAST_CHUNK,
    FLAG_SAMPLE_INDEX_VALID, MSG_BYE, MSG_EVENT_FILE_CHUNK, MSG_HEARTBEAT,
    MSG_HELLO_ACK, MSG_PCM_RECORD32, MSG_RESULT_WORDS32, MSG_SERVICE_SNAPSHOT,
    MSG_STREAM_GAP, MSG_STREAM_SCHEMA, PROTOCOL_NAME, PROTOCOL_VERSION,
    SERVICE_HEADER_MAGIC,
)
from ..errors import BackendError
from ..protocol.control import build_event, build_response, u64
from ..protocol.event_file import build_event_container
from ..protocol.framing import build_frame, crc32
from ..protocol.jsonline import LineDecoder, encode_line
from ..protocol.messages import (
    ServiceHeader, build_event_schema, build_pcm_schema, build_result_schema,
    build_service_schema, build_stream_gap,
)
from ..protocol.pcm import encode_record

TEST_TOKEN = "t0ken-test-fixture-000000000001"
BIG_INDEX = 9007199254740993


def _result_words(frame: int = 1234, config: int = 10,
                  first_index: int = BIG_INDEX) -> tuple[int, ...]:
    speed_bits = struct.unpack("<I", struct.pack("<f", 343.0))[0]
    return (3, 0x82000002, frame, config, 1, 0, 0, 211285,
            first_index & 0xFFFFFFFF, first_index >> 32, 0, 0x3F, 0, 0, 0,
            0, 0, 2355, 0x4A3C, 101325, speed_bits, 0x0F, (25 << 16) | 0xFFF6,
            0xFFFF, 0x7FFF, (1 << 16) | 0xFFF0, 7, 9, 0x00010002, 0, 0,
            CANDIDATE_SAMPLE_RATE_BITS)


def _pcm_chunk(first_index: int, count: int = 3) -> bytes:
    patterns = [(-8388608, 8388607, -1, 0, 1, -2),
                (8388607, -8388608, 0, -1, -2, 1),
                (1, 2, 3, 4, 5, 6),
                (-1, -2, -3, -4, -5, -6)]
    return b"".join(encode_record(patterns[index % len(patterns)],
                                  first_index + index) for index in range(count))


class MockPsServer:
    """Two TCP servers (control JSON-lines + binary SMA1) with fixture data."""

    def __init__(self, *, host: str = "127.0.0.1", control_port: int = 0,
                 binary_port: int = 0, connection_epoch: int = 3,
                 result_frames: int = 3, pcm_chunks: int = 2,
                 stream_seconds: float = 1.0,
                 faults: tuple[str, ...] = ()) -> None:
        self.host = host
        self.requested_control_port = control_port
        self.requested_binary_port = binary_port
        self.connection_epoch = connection_epoch
        self.result_frames = result_frames
        self.pcm_chunks = pcm_chunks
        self.stream_seconds = float(stream_seconds)
        self.faults = set(faults)
        self.control_port = 0
        self.binary_port = 0
        self._control_socket: socket.socket | None = None
        self._binary_socket: socket.socket | None = None
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._dedupe: dict[tuple[int, str], dict[str, Any]] = {}
        self._connection_counter = 0
        self._last_session_id = ""
        self._holders: dict[str, dict[str, Any]] = {}
        self._tokens: dict[str, dict[str, Any]] = {}
        self._sequence = 0
        self._job_counter = 0
        self._acknowledged: set[int] = set()
        self._event_container: bytes | None = None
        self._event_sha: str = ""
        self.subscription_counter = 0
        self.requests_handled = 0
        self.binary_connections = 0
        self.bytes_sent = 0
        self.protocol_violations: list[str] = []
        self._event_directory: Path | None = None

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> dict[str, Any]:
        self._control_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._control_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._control_socket.bind((self.host, self.requested_control_port))
        self._control_socket.listen(4)
        self._control_socket.settimeout(0.25)
        self.control_port = self._control_socket.getsockname()[1]
        self._binary_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._binary_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._binary_socket.bind((self.host, self.requested_binary_port))
        self._binary_socket.listen(4)
        self._binary_socket.settimeout(0.25)
        self.binary_port = self._binary_socket.getsockname()[1]
        for target in (self._accept_control, self._accept_binary):
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self._threads.append(thread)
        return {"controlPort": self.control_port, "binaryPort": self.binary_port,
                "connectionEpoch": str(self.connection_epoch),
                "simulated": True, "sourceKind": "test-fixture"}

    def stop(self) -> None:
        self._stop.set()
        for sock in (self._control_socket, self._binary_socket):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        for thread in self._threads:
            thread.join(timeout=1.0)

    # -- control server ----------------------------------------------------
    def _accept_control(self) -> None:
        while not self._stop.is_set():
            try:
                client, _ = self._control_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            threading.Thread(target=self._control_handler, args=(client,), daemon=True).start()

    def _control_handler(self, client: socket.socket) -> None:
        decoder = LineDecoder()
        client.settimeout(0.5)
        buffer = bytearray()
        with self._lock:
            self._connection_counter += 1
            connection_id = self._connection_counter
        session_id = f"sess-{self.connection_epoch:04x}-{connection_id:02d}"
        try:
            while not self._stop.is_set():
                try:
                    data = client.recv(65536)
                except socket.timeout:
                    continue
                if not data:
                    return
                buffer.extend(data)
                try:
                    messages = decoder.feed(bytes(buffer))
                except BackendError as exc:
                    self._reply_error(client, None, exc)
                    return
                buffer.clear()
                for message in messages:
                    response = self._handle_control(message, session_id, connection_id)
                    response.pop("_sessionId", None)
                    response.pop("_token", None)
                    client.sendall(encode_line(response))
        except (OSError, BackendError):
            return
        finally:
            try:
                client.close()
            except OSError:
                pass

    def _reply_error(self, client: socket.socket, request_id: str | None,
                     error: BackendError) -> None:
        try:
            client.sendall(encode_line(build_response(request_id or "server-error",
                                                      "error", error=error.to_dict())))
        except OSError:
            pass

    def _handle_control(self, message: dict[str, Any], session_id: str,
                        connection_id: int) -> dict[str, Any]:
        request_id = str(message.get("requestId", ""))
        key = (connection_id, request_id)
        with self._lock:
            if key in self._dedupe:
                return json.loads(json.dumps(self._dedupe[key]))
        response = self._process_control(message, session_id)
        with self._lock:
            self._dedupe[key] = json.loads(json.dumps(response))
        self.requests_handled += 1
        return response

    def _process_control(self, message: dict[str, Any],
                         session_id: str) -> dict[str, Any]:
        request_id = str(message.get("requestId", ""))
        if message.get("protocol") != PROTOCOL_NAME:
            return build_response(request_id, "error",
                                  error={"code": "protocol_mismatch",
                                         "messageKey": "errors.protocol_mismatch",
                                         "retryable": False})
        if message.get("version") != PROTOCOL_VERSION:
            return build_response(request_id, "error",
                                  error={"code": "unsupported_version",
                                         "messageKey": "errors.unsupported_version",
                                         "retryable": False})
        op = message.get("op")
        args = message.get("args") or {}
        session = session_id
        self._last_session_id = session
        if op == "hello":
            return {"_sessionId": session,
                    **build_response(request_id, "ok", {
                        "protocol": PROTOCOL_NAME, "protocolVersion": PROTOCOL_VERSION,
                        "serverVersion": "mock-ps-gw-0.1.0",
                        "deviceId": "sixmic-mock-0001",
                        "connectionEpoch": str(self.connection_epoch),
                        "sessionId": session,
                        "limits": {"maxLineBytes": 65536,
                                   "maxBinaryPayloadBytes": 1048576,
                                   "maxPendingJobs": 64,
                                   "duplicateCacheSeconds": 120,
                                   "maxControlLeaseSeconds": 300},
                        "capabilities": self._capabilities(),
                        "config": {"activeVersion": 9, "pending": False,
                                   "shadowDirty": False},
                        "control": {"held": False}})}
        if message.get("sessionId") != session_id:
            return build_response(request_id, "error",
                                  error={"code": "unknown_session",
                                         "messageKey": "errors.unknown_session",
                                         "retryable": False})
        if op == "capabilities.get":
            return build_response(request_id, "ok", self._capabilities())
        if op == "status.get":
            return build_response(request_id, "ok", self._status())
        if op == "heartbeat":
            return build_response(request_id, "ok",
                                  {"serverMonotonicNs": str(time.monotonic_ns())})
        if op == "diagnostics.get":
            return build_response(request_id, "ok", {
                "deviceLog": ["mock gateway: no physical board connected",
                              "fixture data only"],
                "logDropped": "0", "queues": {"controlDepth": 0, "binaryDepth": 0},
                "uptimeSeconds": 1.0, "gatewayVersion": "mock-ps-gw-0.1.0",
                "faults": 0})
        if op == "control.claim":
            with self._lock:
                holder = self._holders.get("device")
                now = time.monotonic()
                if holder is not None and holder["expires"] > now:
                    return build_response(request_id, "error",
                                          error={"code": "control_conflict",
                                                 "messageKey": "errors.control_conflict",
                                                 "retryable": True,
                                                 "detail": {"holder": holder["name"]}})
                lease = min(300, max(5, int(args.get("leaseSeconds", 30))))
                token = TEST_TOKEN
                self._holders["device"] = {"name": "BackendCheck-fixture",
                                           "token": token,
                                           "expires": now + lease}
                return {"_token": token,
                        **build_response(request_id, "ok", {
                            "controlToken": token,
                            "expiresInMs": lease * 1000,
                            "owner": {"clientName": "BackendCheck-fixture",
                                      "sinceMonotonicNs": str(time.monotonic_ns())}})}
        if op == "control.renew":
            with self._lock:
                holder = self._holders.get("device")
                if holder is None or holder["expires"] <= time.monotonic():
                    return build_response(request_id, "error",
                                          error={"code": "bad_token",
                                                 "messageKey": "errors.bad_token",
                                                 "retryable": False})
                holder["expires"] = time.monotonic() + 30
                return build_response(request_id, "ok", {"expiresInMs": 30000})
        if op == "control.release":
            with self._lock:
                self._holders.pop("device", None)
            return build_response(request_id, "ok", {"released": True})
        if op == "config.read":
            return build_response(request_id, "ok", {
                "shadow": [1, 10] + [0] * 30,
                "active": [1, 9] + [0] * 30,
                "activeVersion": 9, "pending": False})
        if op == "config.write":
            return build_response(request_id, "ok", {"shadowDirty": True})
        if op == "config.commit":
            version = int(args.get("version", 0))
            job = self._new_job("config.commit", request_id)
            threading.Timer(0.05, self._complete_config, args=(version, job)).start()
            return build_response(request_id, "accepted", {"jobId": job})
        if op == "config.abort":
            return build_response(request_id, "ok", {"aborted": True})
        if op == "subscribe":
            self.subscription_counter += 1
            streams = []
            for entry in args.get("streams", []):
                stream_type = entry.get("type")
                if stream_type == "pcmRecord32" and "no_pcm" not in self.faults:
                    streams.append({"streamId": 2, "type": "pcmRecord32",
                                    "schemaSha256": "fixture"})
                elif stream_type == "resultWords":
                    streams.append({"streamId": 1, "type": "resultWords",
                                    "schemaSha256": "fixture"})
                elif stream_type == "serviceSnapshot":
                    streams.append({"streamId": 3, "type": "serviceSnapshot",
                                    "schemaSha256": "fixture"})
                elif stream_type == "events":
                    streams.append({"streamId": 5, "type": "eventFile",
                                    "schemaSha256": "fixture"})
                else:
                    return build_response(request_id, "error",
                                          error={"code": "not_ready",
                                                 "messageKey": "errors.not_ready",
                                                 "retryable": False,
                                                 "detail": {"feature": stream_type,
                                                            "missing": "fixture does not implement this stream"}})
            self._subscription = {"subscriptionId": f"sub-{self.subscription_counter}",
                                  "streams": streams}
            return build_response(request_id, "ok", self._subscription)
        if op == "stream.open":
            if args.get("eventId") is not None:
                self.subscription_counter += 1
                self._subscription = {"streams":[{"streamId":5,"type":"eventFile",
                    "schemaSha256":"fixture"}]}
            token = f"bin-{self.connection_epoch}-{self.subscription_counter}"
            with self._lock:
                self._tokens[token] = {"streams": list(self._subscription["streams"])}
            return build_response(request_id, "ok", {
                "binaryToken": token, "port": self.binary_port,
                "maxPayloadBytes": 1048576, "expiresInMs": 60000,
                "streams": list(self._subscription["streams"])})
        if op == "unsubscribe":
            return build_response(request_id, "ok", {"unsubscribed": True})
        if op == "task.start":
            job = self._new_job(str(args.get("kind", "task")), request_id)
            threading.Timer(0.05, self._complete_job, args=(job,)).start()
            return build_response(request_id, "accepted", {"jobId": job})
        if op == "task.cancel":
            return build_response(request_id, "ok", {"cancelRequested": True})
        if op == "job.get":
            return build_response(request_id, "ok", self._job_state(str(args.get("jobId"))))
        if op == "job.list":
            return build_response(request_id, "ok", {"jobs": [self._job_state(job) for job in self._jobs]})
        if op == "recording.start":
            self._recording = {"recordingId": "rec-fixture-1", "state": "recording",
                               "startedMonotonicNs": str(time.monotonic_ns())}
            return build_response(request_id, "ok", self._recording)
        if op == "recording.stop":
            self._recording = {"recordingId": "rec-fixture-1", "state": "stopped",
                               "records": "6", "bytes": "192", "gaps": 0,
                               "sha256": "0" * 64}
            return build_response(request_id, "ok", self._recording)
        if op == "recording.status":
            return build_response(request_id, "ok",
                                  getattr(self, "_recording",
                                          {"recordingId": None, "state": "idle"}))
        if op == "event.list":
            return build_response(request_id, "ok", {"events": [self._event_record()]})
        if op == "event.get":
            return build_response(request_id, "ok", {
                "event": self._event_record(),
                "file": {"totalBytes": str(len(self._event_bytes())),
                         "sha256": hashlib.sha256(self._event_bytes()).hexdigest(),
                         "chunkBytes": 65536}})
        if op == "event.download":
            return build_response(request_id, "ok", {
                "streamId": 5, "chunkBytes": 64,
                "totalBytes": str(len(self._event_bytes())),
                "sha256": hashlib.sha256(self._event_bytes()).hexdigest(),
                "offset": str(args.get("offset", "0"))})
        if op == "event.ack":
            self._acknowledged.add(int(args.get("eventId", 0)))
            return build_response(request_id, "ok",
                                  {"acked": True, "duplicate": False})
        if op in ("profile.upload", "profile.activate", "profile.deactivate"):
            return build_response(request_id, "error",
                                  error={"code": "not_ready",
                                         "messageKey": "errors.not_ready",
                                         "retryable": False,
                                         "detail": {"feature": "profileUpload",
                                                    "missing": "profile_upload.c review issue not closed"}})
        return build_response(request_id, "error",
                              error={"code": "unknown_op",
                                     "messageKey": "errors.unknown_op",
                                     "retryable": False, "detail": {"op": op}})

    # -- helpers -----------------------------------------------------------
    _jobs: dict[str, dict[str, Any]] = {}
    _job_order: list[str] = []

    def _new_job(self, kind: str, request_id: str) -> str:
        with self._lock:
            self._job_counter += 1
            job_id = f"job-{self._job_counter:06d}"
            now = str(time.monotonic_ns())
            self._jobs[job_id] = {"jobId": job_id, "kind": kind, "state": "accepted",
                                  "progress": 0.0, "createdAtMonotonicNs": now,
                                  "updatedAtMonotonicNs": now, "clientTaskKey": None,
                                  "requestId": request_id, "result": None,
                                  "error": None, "cancelRequested": False,
                                  "cancelAcknowledged": False}
            self._job_order.append(job_id)
            return job_id

    def _job_state(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            source = self._jobs.get(job_id) or {"jobId": job_id, "kind": "unknown",
                                                "state": "completed",
                                                "createdAtMonotonicNs": "0",
                                                "updatedAtMonotonicNs": "0"}
            return json.loads(json.dumps(source))

    def _complete_job(self, job_id: str) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id]["state"] = "completed"
                self._jobs[job_id]["progress"] = 1.0
                self._jobs[job_id]["updatedAtMonotonicNs"] = str(time.monotonic_ns())

    def _complete_config(self, version: int, job_id: str) -> None:
        with self._lock:
            self._config_version = version
        self._complete_job(job_id)

    def _event_bytes(self) -> bytes:
        with self._lock:
            if self._event_container is None:
                records = b"".join(encode_record([1, 2, 3, 4, 5, 6], BIG_INDEX + index)
                                   for index in range(2))
                self._event_container = build_event_container(
                    event_id=7, flags=0, clip_reason=5,
                    first_sample_index=BIG_INDEX, last_sample_index=BIG_INDEX + 1,
                    sample_rate_hz=48009.775390625, records=records)
            return self._event_container

    def _event_record(self) -> dict[str, Any]:
        data = self._event_bytes()
        return {"eventId": "7", "deviceId": "sixmic-mock-0001",
                "connectionEpoch": str(self.connection_epoch),
                "sessionId": self._last_session_id,
                "sourceKind": "test-fixture", "capturedFirstSampleIndex": str(BIG_INDEX),
                "capturedLastSampleIndex": str(BIG_INDEX + 1), "frames": 2,
                "sampleRateHz": 48009.775390625, "clipReason": 5,
                "flags": {"incomplete": False, "lostEvents": False,
                          "summaryStale": False, "envInvalid": False,
                          "poseInvalid": False},
                "preQ22": 1, "postQ22": 2, "deltaQ22": 1,
                "summaryAgeSamples": 10, "summaryValid": True,
                "bank": 0, "offsetBytes": 0,
                "file": {"state": "known",
                         "totalBytes": str(len(data)),
                         "sha256": hashlib.sha256(data).hexdigest()},
                "ack": {"acked": 7 in self._acknowledged, "duplicate": False}}

    def _capabilities(self) -> dict[str, Any]:
        return {"device": {
                    "livePcm": "not_ready", "liveResults": "not_ready",
                    "resultSnapshotProtocol": 3, "serviceSnapshots": [],
                    "eventCapture": "not_ready", "eventDownload": "available",
                    "rawRecording": "not_ready", "profileUpload": "not_ready",
                    "profileActivate": "not_ready", "taskControl": "experimental",
                    "sensorSnapshot": "not_ready", "deviceLog": "available",
                    "configCommit": "experimental", "configVersion": 9,
                    "protocol3": True,
                    "missing": ["mock server: no physical board link",
                                "PL raw ring PS consumer/lease not accepted"]},
                "gateway": {"version": "mock-ps-gw-0.1.0",
                            "controlPort": self.control_port,
                            "binaryPort": self.binary_port,
                            "simulated": True}}

    def _status(self) -> dict[str, Any]:
        return {"connectionEpoch": str(self.connection_epoch),
                "sessionId": self._last_session_id,
                "deviceState": "ready", "deviceStateReasons": ["mock fixture"],
                "control": {"held": "device" in self._holders,
                            "expiresInMs": None},
                "config": {"activeVersion": getattr(self, "_config_version", 9),
                           "shadowVersion": 10, "pending": False,
                           "lastRejectedVersion": None},
                "resultFreshness": {"frameId": 1234, "configVersion": 9,
                                    "sampleIndex": ["0", str(BIG_INDEX)],
                                    "deviceMonotonicNs": None,
                                    "receivedMonotonicNs": str(time.monotonic_ns()),
                                    "stale": False},
                "sensors": None,
                "faults": {"faultBits": 0, "sensorErrors": 0, "microphoneStatus": 0,
                           "missedWindows": 0, "droppedSamples": 0,
                           "lostEvents": 0, "handoffDrops": 0},
                "queues": {"pcmPendingBytes": "0", "pcmDroppedBytes": "0",
                           "resultDroppedFrames": "0", "eventSpoolBytes": "0",
                           "eventSpoolLimitBytes": "67108864"},
                "recording": {"recordingId": None, "state": "idle"},
                "jobs": {"pending": 0},
                "pl": {"resultWordProtocol": 3, "algorithmId": "0x82000002",
                       "capabilities": "0"}}

    # -- binary server -----------------------------------------------------
    def _accept_binary(self) -> None:
        while not self._stop.is_set():
            try:
                client, _ = self._binary_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            self.binary_connections += 1
            threading.Thread(target=self._binary_handler, args=(client,),
                             daemon=True).start()

    def _send(self, client: socket.socket, frame: bytes) -> None:
        client.sendall(frame)
        self.bytes_sent += len(frame)

    def _binary_handler(self, client: socket.socket) -> None:
        client.settimeout(1.0)
        buffer = bytearray()
        token: str | None = None
        try:
            while token is None and not self._stop.is_set():
                try:
                    data = client.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    return
                buffer.extend(data)
                if len(buffer) < 64:
                    continue
                header = {"payload": struct.unpack_from("<I", buffer, 12)[0],
                          "type": struct.unpack_from("<H", buffer, 8)[0]}
                if header["type"] != 0x0001:
                    self.protocol_violations.append("first-binary-frame-not-hello")
                    return
                total = 64 + header["payload"]
                if len(buffer) < total:
                    continue
                payload = json.loads(bytes(buffer[64:total]).decode("utf-8"))
                token = payload.get("token")
                if token not in self._tokens:
                    self.protocol_violations.append("bad-binary-token")
                    return
                buffer.clear()
                break
            streams = self._tokens[token]["streams"]
            ack = json.dumps({"accepted": True, "maxPayloadBytes": 1048576,
                              "connectionEpoch": str(self.connection_epoch),
                              "streams": streams}, separators=(",", ":")).encode()
            self._send(client, self._frame(MSG_HELLO_ACK, ack))
            if "data_before_schema" in self.faults:
                self._send(client, self._frame(MSG_RESULT_WORDS32,
                                               struct.pack("<32I", *_result_words()),
                                               stream_id=1, sequence=0))
            for stream in streams:
                if stream["streamId"] == 1:
                    schema = build_result_schema(source_kind="test-fixture",
                                                 device_id="sixmic-mock-0001",
                                                 connection_epoch=self.connection_epoch,
                                                 simulated=True,
                                                 sample_rate_hz=48009.775390625)
                    schema["streamId"] = 1
                    self._send(client, self._frame(MSG_STREAM_SCHEMA,
                                                   json.dumps(schema,
                                                              separators=(",", ":")).encode(),
                                                   stream_id=1, sequence=0))
                elif stream["streamId"] == 2:
                    schema = build_pcm_schema(stream_id=2, device_id="sixmic-mock-0001",
                                              connection_epoch=self.connection_epoch,
                                              source_kind="test-fixture", simulated=True,
                                              sample_rate_hz=48009.775390625,
                                              frame_group_records=3)
                    self._send(client, self._frame(MSG_STREAM_SCHEMA,
                                                   json.dumps(schema,
                                                              separators=(",", ":")).encode(),
                                                   stream_id=2, sequence=0))
                elif stream["streamId"] == 3:
                    schema = build_service_schema(stream_id=3,
                                                  device_id="sixmic-mock-0001",
                                                  connection_epoch=self.connection_epoch,
                                                  source_kind="test-fixture",
                                                  simulated=True, service_id="fixture-shape",
                                                  descriptor=600000, session=1,
                                                  config=9, generation=1,
                                                  payload_words=3)
                    self._send(client, self._frame(MSG_STREAM_SCHEMA,
                                                   json.dumps(schema,
                                                              separators=(",", ":")).encode(),
                                                   stream_id=3, sequence=0))
                elif stream["streamId"] == 5:
                    container = self._event_bytes()
                    schema = build_event_schema(stream_id=5, device_id="sixmic-mock-0001",
                                                connection_epoch=self.connection_epoch,
                                                source_kind="test-fixture", simulated=True,
                                                event_id=7, total_bytes=len(container),
                                                sha256=hashlib.sha256(container).hexdigest(),
                                                chunk_bytes=64)
                    self._send(client, self._frame(MSG_STREAM_SCHEMA,
                                                   json.dumps(schema,
                                                              separators=(",", ":")).encode(),
                                                   stream_id=5, sequence=0))
            for stream in streams:
                self._stream_data(client, stream["streamId"])
        except OSError:
            # Client disconnect/reset is normal, not a protocol violation.
            pass
        except (ValueError, BackendError) as exc:
            self.protocol_violations.append(f"binary-handler:{exc}")
        finally:
            try:
                client.close()
            except OSError:
                pass

    def _stream_data(self, client: socket.socket, stream_id: int) -> None:
        if stream_id == 1:
            sequence = 0
            first_index = BIG_INDEX
            for frame_index in range(self.result_frames):
                words = _result_words(frame=1234 + frame_index, config=9,
                                      first_index=first_index)
                payload = struct.pack("<32I", *words)
                if "bad_crc" in self.faults and frame_index == 1:
                    frame = bytearray(self._frame(MSG_RESULT_WORDS32, payload,
                                                  stream_id=1, sequence=sequence,
                                                  first_index=first_index))
                    frame[56:60] = b"\x00\x00\x00\x00"
                    self._send(client, bytes(frame))
                else:
                    self._send(client, self._frame(MSG_RESULT_WORDS32, payload,
                                                   stream_id=1, sequence=sequence,
                                                   first_index=first_index,
                                                   flags=FLAG_SAMPLE_INDEX_VALID))
                sequence += 1
            if "gap" in self.faults:
                gap = build_stream_gap(stream_id=1, reason="queue_overflow",
                                       dropped_records=150,
                                       first_missing=first_index + 100,
                                       last_missing=first_index + 249,
                                       detected_device_ns=None,
                                       source_kind="test-fixture")
                self._send(client, self._frame(MSG_STREAM_GAP,
                                               json.dumps(gap,
                                                          separators=(",", ":")).encode(),
                                               stream_id=1, sequence=sequence,
                                               flags=FLAG_GAP_BEFORE))
        elif stream_id == 2:
            # Stream PCM continuously for a bounded window so recording/replay
            # tests see real chunks after they start recording.
            first_index = BIG_INDEX
            sequence = 0
            chunk_count = 0
            deadline = time.monotonic() + float(self.stream_seconds)
            while time.monotonic() < deadline and not self._stop.is_set():
                payload = _pcm_chunk(first_index + chunk_count * 3, 3)
                self._send(client, self._frame(MSG_PCM_RECORD32, payload, stream_id=2,
                                               sequence=sequence,
                                               first_index=first_index + chunk_count * 3,
                                               flags=FLAG_SAMPLE_INDEX_VALID))
                sequence += 1
                chunk_count += 1
                time.sleep(0.02)
            if "gap" in self.faults:
                gap = build_stream_gap(stream_id=2, reason="queue_overflow",
                                       dropped_records=3,
                                       first_missing=first_index + 6,
                                       last_missing=first_index + 8,
                                       detected_device_ns=None,
                                       source_kind="test-fixture")
                self._send(client, self._frame(MSG_STREAM_GAP,
                                               json.dumps(gap,
                                                          separators=(",", ":")).encode(),
                                               stream_id=2, sequence=sequence))
        elif stream_id == 3:
            header = ServiceHeader(commit_sequence=42, session=1, config=9, generation=1,
                                   program_version=2, source_frame=1234,
                                   sample_index_low=BIG_INDEX & 0xFFFFFFFF,
                                   sample_index_high=BIG_INDEX >> 32, slot=0,
                                   length=3, descriptor=600000, error=0, pc=1234,
                                   done=1)
            body = struct.pack("<3I", 0x3F800000, 0x40000000, 0)
            self._send(client, self._frame(MSG_SERVICE_SNAPSHOT,
                                           struct.pack("<16I", *header.to_words()) + body,
                                           stream_id=3, sequence=0))
        elif stream_id == 5:
            container = self._event_bytes()
            offset = 0
            sequence = 0
            while offset < len(container):
                chunk = container[offset:offset + 64]
                flags = FLAG_SAMPLE_INDEX_VALID
                if offset == 0:
                    flags |= FLAG_FIRST_CHUNK
                offset += len(chunk)
                if offset >= len(container):
                    flags |= FLAG_LAST_CHUNK
                self._send(client, self._frame(MSG_EVENT_FILE_CHUNK, chunk,
                                               stream_id=5, sequence=sequence,
                                               first_index=BIG_INDEX, flags=flags))
                sequence += 1
        self._send(client, self._frame(MSG_HEARTBEAT, b""))

    # -- frame helper ------------------------------------------------------
    def _frame(self, message_type: int, payload: bytes, *, stream_id: int = 0,
               sequence: int = 0, first_index: int = 0, flags: int = 0) -> bytes:
        return build_frame(message_type, payload, stream_id=stream_id,
                           sequence=sequence, connection_epoch=self.connection_epoch,
                           first_sample_index=first_index, flags=flags)
