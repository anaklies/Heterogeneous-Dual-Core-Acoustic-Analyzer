"""High-level device session: connection, control lease, subscriptions, recording.

This module is UI-agnostic (no Qt import). The Qt adapter wraps it and forwards
listener callbacks as queued signals. Network and disk work happen on worker
threads, never on the GUI thread.
"""
from __future__ import annotations

import hashlib
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

from .constants import (
    DEFAULT_BINARY_PORT, DEFAULT_CONTROL_PORT, DEFAULT_MAX_BINARY_PAYLOAD,
    SERVICE_HEADER_BYTES, SOURCE_FILE_REPLAY, SOURCE_PL_LIVE,
)
from .data.config_store import ConfigStore
from .data.data_store import DataStore
from .data.events import EventManager
from .data.recording import Recorder
from .data.replay import ReplaySession
from .data.storage import Storage
from .data.stream_dispatcher import StreamConsumer, StreamDispatcher
from .diagnostics import DiagnosticRing, setup_logging
from .errors import BackendError
from .jobs import JobManager
from .model.dto import (
    AudioChunk, DeviceCapabilities, DeviceInfo, EventRecord, LiveFrame,
    ServiceResult,
)
from .model.feature_catalog import load_feature_catalog
from .paths import ensure_user_dirs, protocol_dir
from .protocol.control import parse_u64
from .protocol.event_file import parse_event_container
from .protocol.messages import (
    decode_result_words, parse_service_snapshot, unpack_result_words,
)
from .protocol.pcm import decode_records
from .transport.binary_client import BinaryClient
from .transport.control_client import ControlClient


class SessionListener:
    """Subclass/duplicate these callbacks; all are optional and exception-isolated."""

    def connection_changed(self, state: dict[str, Any]) -> None: ...
    def capabilities_changed(self, capabilities: dict[str, Any]) -> None: ...
    def operation_updated(self, job: dict[str, Any]) -> None: ...
    def frame_available(self, frame: dict[str, Any]) -> None: ...
    def audio_chunk_available(self, chunk: dict[str, Any]) -> None: ...
    def service_result_available(self, result: dict[str, Any]) -> None: ...
    def event_added(self, event: dict[str, Any]) -> None: ...
    def recording_changed(self, status: dict[str, Any]) -> None: ...
    def diagnostic_added(self, diagnostic: dict[str, Any]) -> None: ...
    def stream_gap(self, gap: dict[str, Any]) -> None: ...


class _ResultConsumer:
    def __init__(self, session: "DeviceSession") -> None:
        self.session = session
        self.source_kind = "test-fixture"

    def on_schema(self, schema: dict[str, Any]) -> None:
        self.source_kind = str(schema.get("sourceKind", "test-fixture"))

    def on_payload(self, header: Any, payload: bytes, schema: dict[str, Any]) -> None:
        words = unpack_result_words(payload)
        decoded = decode_result_words(words)
        source_kind = self.source_kind
        if source_kind == SOURCE_PL_LIVE and schema.get("simulated"):
            source_kind = "test-fixture"
        frame = LiveFrame(
            source_kind=source_kind,
            device_id=str(schema.get("deviceId", "")),
            connection_epoch=parse_u64(schema.get("connectionEpoch", "0"), "connectionEpoch"),
            session_id=self.session.session_id or "",
            frame_id=int(decoded["frameId"]), config_version=int(decoded["configVersion"]),
            sample_index=int(decoded["sampleIndex"]),
            sample_rate_hz=float(decoded["sampleRateHz"]),
            words=tuple(words), decoded=decoded,
            device_monotonic_ns=(header.device_monotonic_ns
                                 if header.device_monotonic_valid else None),
            received_monotonic_ns=time.monotonic_ns(),
            validity={"stale": False, "epoch": int(header.connection_epoch),
                      "sampleIndexValid": bool(header.sample_index_valid),
                      "deviceTimeValid": bool(header.device_monotonic_valid),
                      "consistent": True},
            quality={"overwritten": int(decoded["overwritten"]),
                     "missedWindows": int(decoded["missedWindows"]),
                     "droppedSamples": int(decoded["droppedSamples"]),
                     "failedFrames": int(decoded["failedFrames"])})
        self.session._on_live_frame(frame)


class _PcmConsumer:
    def __init__(self, session: "DeviceSession") -> None:
        self.session = session
        self.source_kind = "test-fixture"
        self.sample_rate_hz = 0.0
        self.channel_count = 6
        self.last_expected: int | None = None
        self.gaps = 0

    def on_schema(self, schema: dict[str, Any]) -> None:
        self.source_kind = str(schema.get("sourceKind", "test-fixture"))
        pcm = schema.get("pcm") or {}
        self.sample_rate_hz = float(pcm.get("sampleRateHz") or 0.0)
        self.channel_count = int(pcm.get("channels") or 6)

    def on_payload(self, header: Any, payload: bytes, schema: dict[str, Any]) -> None:
        records = decode_records(payload)
        if not records:
            return
        first_index = records[0].sample_index
        previous_expected = self.last_expected
        gap_before = bool(header.gap_before)
        if previous_expected is not None and first_index != previous_expected:
            gap_before = True
            self.gaps += 1
        self.last_expected = records[-1].sample_index + 1
        gap_entries: list[dict[str, Any]] = []
        if gap_before:
            # previous_expected is the first sample index that should have arrived
            # (last delivered index + 1); the hole ends right before this chunk.
            first_missing = (previous_expected if previous_expected is not None
                             else first_index)
            last_missing = first_index - 1
            if last_missing >= first_missing:
                gap_entries.append({"reason": "sample-index-discontinuity",
                                    "firstMissingSampleIndex": str(first_missing),
                                    "lastMissingSampleIndex": str(last_missing)})
        source_kind = self.source_kind
        if source_kind == SOURCE_PL_LIVE and schema.get("simulated"):
            source_kind = "test-fixture"
        chunk = AudioChunk(
            source_kind=source_kind,
            device_id=str(schema.get("deviceId", "")),
            connection_epoch=parse_u64(schema.get("connectionEpoch", "0"), "connectionEpoch"),
            session_id=self.session.session_id or "", stream_id=header.stream_id,
            first_sample_index=first_index, sample_count=len(records),
            sample_rate_hz=self.sample_rate_hz, records=payload,
            gap_before=gap_before,
            continuity={"continuous": not gap_before,
                        "expectedFirstSampleIndex": None,
                        "gaps": gap_entries},
            device_monotonic_ns=(header.device_monotonic_ns
                                 if header.device_monotonic_valid else None))
        self.session._on_audio_chunk(chunk)


class _ServiceConsumer:
    def __init__(self, session: "DeviceSession") -> None:
        self.session = session
        self.source_kind = "test-fixture"

    def on_schema(self, schema: dict[str, Any]) -> None:
        self.source_kind = str(schema.get("sourceKind", "test-fixture"))
        self.service_id = str(schema.get("serviceId", "unknown"))

    def on_payload(self, header: Any, payload: bytes, schema: dict[str, Any]) -> None:
        service_header, body = parse_service_snapshot(payload)
        expected = {name: int(schema[name]) if schema.get(name) is not None else None
                    for name in ("session", "config", "generation")}
        if not service_header.usable(**expected):
            raise BackendError("bad_state", {"reason": "unusable-service-publication",
                                            "serviceId": schema.get("serviceId")})
        source_kind = self.source_kind
        if source_kind == SOURCE_PL_LIVE and schema.get("simulated"):
            source_kind = "test-fixture"
        result = ServiceResult(
            source_kind=source_kind,
            device_id=str(schema.get("deviceId", "")),
            connection_epoch=parse_u64(schema.get("connectionEpoch", "0"), "connectionEpoch"),
            session_id=self.session.session_id or "",
            service_id=str(schema.get("serviceId", "unknown")),
            descriptor=service_header.descriptor, slot=service_header.slot,
            session=service_header.session, config=service_header.config,
            generation=service_header.generation,
            program_version=service_header.program_version,
            source_frame=service_header.source_frame,
            sample_index=service_header.sample_index, units=None, words=body,
            validity={"done": True, "error": service_header.error,
                      "headerConsistent": True,
                      "provenanceValid": service_header.usable()},
            provenance={"kind": source_kind, "inputRecordIds": [],
                        "note": "sourceFrame is an execution frame, not an offline record id"})
        self.session._on_service_result(result)


class _EventFileConsumer:
    def __init__(self, session: "DeviceSession", event_id: int, sha256: str,
                 total_bytes: int | None = None) -> None:
        self.session = session
        self.event_id = event_id
        self.sha256 = sha256
        self.total_bytes = total_bytes
        self.buffer = bytearray()
        self.finished = False

    def on_schema(self, schema: dict[str, Any]) -> None:
        self.total_bytes = int(schema.get("totalBytes", 0) or 0) or self.total_bytes

    def on_payload(self, header: Any, payload: bytes, schema: dict[str, Any]) -> None:
        self.buffer.extend(payload)
        if header.last_chunk:
            data = bytes(self.buffer)
            if self.total_bytes is not None and self.total_bytes != len(data):
                raise BackendError("file_corrupt", {"reason": "event-download-size",
                                                    "expected": self.total_bytes,
                                                    "actual": len(data)})
            digest = hashlib.sha256(data).hexdigest()
            if digest.lower() != self.sha256.lower():
                raise BackendError("event_hash_mismatch",
                                   {"eventId": str(self.event_id),
                                    "expected": self.sha256, "actual": digest})
            info = self.session.event_manager.store_downloaded(
                self.event_id, data, expected_sha256=self.sha256)
            self.finished = True
            self.session._on_event_downloaded(info)


class DeviceSession:
    def __init__(self, *, host: str | None = None, control_port: int | None = None,
                 binary_port: int | None = None, protocol_root: str | Path | None = None,
                 user_dirs: dict[str, Path] | None = None,
                 config_store: ConfigStore | None = None,
                 listener: SessionListener | None = None,
                 auto_reconnect: bool | None = None) -> None:
        self.paths = user_dirs or ensure_user_dirs()
        self.config_store = config_store or ConfigStore()
        values = self.config_store.load()
        self.host = host or values["host"]
        self.control_port = int(control_port or values["controlPort"])
        self.binary_port = int(binary_port or values["binaryPort"])
        self.protocol_root = Path(protocol_root) if protocol_root else protocol_dir()
        self.auto_reconnect = bool(values["autoReconnect"] if auto_reconnect is None
                                   else auto_reconnect)
        self.lease_seconds = int(values["controlLeaseSeconds"])
        self.logger = setup_logging(self.paths["logs"])
        self.diagnostics = DiagnosticRing()
        self.storage = Storage(self.paths["data"] / "backend.sqlite")
        self.jobs = JobManager(self.storage)
        self.data_store = DataStore()
        self.event_manager = EventManager(self.paths["events"], self.storage)
        self.feature_catalog = None
        try:
            self.feature_catalog = load_feature_catalog(self.protocol_root)
        except BackendError as exc:
            self._diagnostic("warning", "feature_catalog_unavailable", {"error": exc.code})
        self._listeners: list[SessionListener] = [listener] if listener else []
        self._lock = threading.RLock()
        self._subscription_lock = threading.RLock()
        self._subscription_switching=False
        self._recovery_serial=0
        self.state = "disconnected"
        self.device_info: DeviceInfo | None = None
        self.capabilities: DeviceCapabilities = DeviceCapabilities()
        self.hello: dict[str, Any] | None = None
        self.control: ControlClient | None = None
        self.binary: BinaryClient | None = None
        self.dispatcher: StreamDispatcher | None = None
        self.subscription: dict[str, Any] | None = None
        self._consumers: dict[int, Any] = {}
        self.recorder: Recorder | None = None
        self.recording_id: str | None = None
        self.replay: ReplaySession | None = None
        self.last_frame: LiveFrame | None = None
        self.last_audio: AudioChunk | None = None
        self._first_audio_chunk: AudioChunk | None = None
        self._audio_handle: str | None = None
        self.last_service: ServiceResult | None = None
        self._service_handle: str | None = None
        self.frame_count = 0
        self.audio_chunk_count = 0
        self._renew_stop = threading.Event()
        self._renew_thread: threading.Thread | None = None
        self._control_token: str | None = None
        self._task_keys: dict[str, tuple[dict[str, Any], float]] = {}
        self._intentional_disconnect = False
        self._pending_event_download: tuple[int, str, int | None] | None = None
        self._event_download_done: threading.Event | None = None

    # -- properties --------------------------------------------------------
    @property
    def session_id(self) -> str | None:
        return self.control.session_id if self.control else None

    @property
    def connection_epoch(self) -> int | None:
        return self.control.connection_epoch if self.control else None

    # -- connection --------------------------------------------------------
    def add_listener(self, listener: SessionListener) -> None:
        self._listeners.append(listener)

    def _emit(self, method: str, payload: Any) -> None:
        for listener in list(self._listeners):
            try:
                getattr(listener, method)(payload)
            except Exception:  # listeners must not break worker threads
                self._diagnostic("error", "listener_error", {"method": method})

    def _diagnostic(self, level: str, code: str, detail: dict[str, Any] | None = None) -> None:
        record = self.diagnostics.append(level, code, detail=detail)
        self._emit("diagnostic_added", record)

    def connect(self, host: str | None = None, control_port: int | None = None,
                binary_port: int | None = None) -> dict[str, Any]:
        with self._lock:
            if self.state == "connected":
                raise BackendError("bad_state", {"reason": "already-connected"})
            if host:
                self.host = host
            if control_port:
                self.control_port = int(control_port)
            if binary_port:
                self.binary_port = int(binary_port)
            if self.control is not None:
                self._intentional_disconnect=True
                self.control.close();self.control=None
                if self.binary is not None:self.binary.close();self.binary=None
                self.subscription=None;self._control_token=None
            self._intentional_disconnect = False
            self._set_state("connecting")
            self.control = ControlClient(
                self.host, self.control_port, auto_reconnect=self.auto_reconnect,
                lease_seconds=self.lease_seconds,
                logger=lambda level, detail: self._diagnostic(level, "control", detail))
            self.control.add_state_listener(self._on_control_state)
            self.control.add_event_listener(self._on_control_event)
            try:
                hello = self.control.connect()
            except BackendError as exc:
                self._set_state("failed", error=exc)
                raise
            self.hello = hello
            try:
                self.control.request("time.sync", {"unixTimeMs":str(time.time_ns()//1000000)})
            except BackendError as exc:
                # Optional extension: older firmware remains connectable.
                self._diagnostic("info","clock_sync_unavailable",{"code":exc.code})
            epoch = parse_u64(hello.get("connectionEpoch"), "connectionEpoch")
            self.capabilities = DeviceCapabilities.from_dict(
                dict((hello.get("capabilities") or {}).get("device") or {}))
            self.device_info = DeviceInfo(
                device_id=str(hello.get("deviceId", "unknown")),
                gateway_version=str(hello.get("serverVersion", "")),
                connection_epoch=epoch,
                sample_rate_hz=None,
                capabilities=self.capabilities,
                verified_on_board=False)
            self._set_state("connected")
            self._emit("capabilities_changed", self.capabilities.to_dict())
            self._start_renewer()
            self.refresh_capabilities()
            return hello

    def disconnect(self) -> None:
        self._intentional_disconnect = True
        self._stop_renewer()
        with self._lock:
            if self.recorder is not None and self.recorder.state == "recording":
                try:
                    self.stop_recording()
                except BackendError:
                    pass
            if self.binary is not None:
                self.binary.close()
                self.binary = None
            if self._service_handle is not None:
                self.data_store.release(self._service_handle)
                self._service_handle = None
            self.last_service = None
            if self.control is not None:
                self.control.close()
                self.control = None
            self.subscription = None
            self._control_token = None
            self._set_state("disconnected")

    # -- capabilities/control ---------------------------------------------
    def refresh_capabilities(self) -> dict[str, Any]:
        if self.control is None:
            raise BackendError("not_connected", {"reason": "capabilities"})
        result = self.control.request("capabilities.get", {})
        device = dict(result.get("device") or {})
        self.capabilities = DeviceCapabilities.from_dict(device)
        if self.device_info is not None:
            self.device_info.capabilities = self.capabilities
        self._emit("capabilities_changed", self.capabilities.to_dict())
        return {"device": self.capabilities.to_dict(),
                "gateway": result.get("gateway") or {}}

    def claim_control(self, lease_seconds: int | None = None) -> dict[str, Any]:
        if self.control is None:
            raise BackendError("not_connected", {"reason": "claim"})
        result = self.control.request("control.claim",
                                      {"leaseSeconds": int(lease_seconds or self.lease_seconds)})
        self._control_token = str(result.get("controlToken", ""))
        self._emit("operation_updated", {"control": "claimed",
                                         "expiresInMs": result.get("expiresInMs")})
        return result

    def release_control(self) -> dict[str, Any]:
        if self.control is None or not self._control_token:
            raise BackendError("control_not_held", {"reason": "release"})
        result = self.control.request("control.release",
                                      {"controlToken": self._control_token})
        self._control_token = None
        self._emit("operation_updated", {"control": "released"})
        return result

    def _start_renewer(self) -> None:
        self._stop_renewer()
        self._renew_stop = threading.Event()

        def loop() -> None:
            interval = max(2.0, self.lease_seconds / 2.0)
            while not self._renew_stop.wait(interval):
                token = self._control_token
                if not token or self.control is None:
                    continue
                try:
                    result = self.control.request("control.renew",
                                                  {"controlToken": token}, timeout=3.0)
                    self._emit("operation_updated",
                               {"control": "renewed",
                                "expiresInMs": result.get("expiresInMs")})
                except BackendError as exc:
                    self._diagnostic("warning", "control_renew", {"error": exc.code})

        self._renew_thread = threading.Thread(target=loop, name="sixmic-lease", daemon=True)
        self._renew_thread.start()

    def _stop_renewer(self) -> None:
        self._renew_stop.set()
        thread = self._renew_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        self._renew_thread = None

    # -- subscriptions -----------------------------------------------------
    def subscribe(self, streams: Iterable[str] = ("resultWords",)) -> dict[str, Any]:
        requested=list(dict.fromkeys(streams))
        with self._subscription_lock:
            if self.binary is not None and getattr(self.binary,'connected',False) and self.subscription is not None and self.subscription.get('sessionId')==self.session_id and self.subscription.get('requested')==requested:
                return self.subscription
            self._subscription_switching=True
            try:return self._subscribe_locked(requested)
            finally:self._subscription_switching=False

    def _subscribe_locked(self, streams: Iterable[str]) -> dict[str, Any]:
        if self.control is None:
            raise BackendError("not_connected", {"reason": "subscribe"})
        requested = list(dict.fromkeys(streams))
        if not requested:
            raise BackendError("bad_args", {"field": "streams"})
        if self.binary is not None:
            self.binary.close()
            self.binary = None
        previous=self.subscription
        if previous and previous.get('subscriptionId') and previous.get('sessionId')==self.session_id:
            try:self.control.request('unsubscribe',{'subscriptionId':previous['subscriptionId']})
            except BackendError as exc:
                if exc.code not in {'bad_args','unknown_subscription'}:raise
        if requested == ["events"] and self._pending_event_download is not None:
            event_id, _, _ = self._pending_event_download
            self.control.request("event.download", {"eventId":str(event_id),
                "offset":"0", "maxBytes":65536})
            result = {}
            opened = self.control.request("stream.open", {"eventId":str(event_id)})
        else:
            result = self.control.request("subscribe", {
                "streams": [{"type": stream} for stream in requested],
                "deliverSchema": True})
            opened = self.control.request("stream.open", {
                "subscriptionId": result.get("subscriptionId")})
        epoch = self.connection_epoch
        if epoch is None:
            raise BackendError("not_authenticated", {"reason": "epoch"})
        dispatcher = StreamDispatcher()
        self._consumers = {}
        # Control-channel stream names map onto binary STREAM_SCHEMA streamTypes.
        schema_types = {"resultWords": "resultWords32", "events": "eventFile",
                        "pcmRecord32": "pcmRecord32",
                        "serviceSnapshot": "serviceSnapshot",
                        "eventFile": "eventFile"}
        for stream in opened.get("streams", []):
            stream_id = int(stream["streamId"])
            control_type = str(stream["type"])
            schema_type = schema_types.get(control_type, control_type)
            if control_type == "resultWords":
                consumer = _ResultConsumer(self)
            elif control_type == "pcmRecord32":
                consumer = _PcmConsumer(self)
            elif control_type == "serviceSnapshot":
                consumer = _ServiceConsumer(self)
            elif control_type in ("events", "eventFile"):
                if self._pending_event_download is None:
                    continue
                event_id, sha256, total = self._pending_event_download
                consumer = _EventFileConsumer(self, event_id, sha256, total)
            else:
                continue
            dispatcher.register(stream_id, schema_type, consumer)
            self._consumers[stream_id] = consumer
        self.dispatcher = dispatcher
        self.binary = BinaryClient(
            self.host, int(opened.get("port", self.binary_port)),
            connection_epoch=epoch, token=str(opened.get("binaryToken", "")),
            max_payload_bytes=int(opened.get("maxPayloadBytes",
                                             DEFAULT_MAX_BINARY_PAYLOAD)),
            dispatcher=dispatcher, on_close=self._on_binary_closed)
        self.binary.connect()
        self.subscription = {"subscriptionId": result.get("subscriptionId"),
                             "sessionId":self.session_id,
                             "streams": opened.get("streams", []),
                             "requested": requested}
        self._emit("operation_updated", {"subscription": "opened",
                                         "streams": len(self._consumers)})
        return self.subscription

    def unsubscribe(self) -> dict[str, Any]:
        with self._subscription_lock:
            previous=self.subscription
            self._subscription_switching=True
            try:
                if self.binary is not None:self.binary.close();self.binary=None
                self.subscription=None
                if self.control is None or not previous or not previous.get('subscriptionId'):return {'unsubscribed':False}
                return self.control.request('unsubscribe',{'subscriptionId':previous['subscriptionId']})
            finally:self._subscription_switching=False

    # -- jobs --------------------------------------------------------------
    def start_job(self, kind: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.control is None:
            raise BackendError("not_connected", {"reason": "job"})
        if not self._control_token:
            raise BackendError("control_not_held", {"reason": "task.start"})
        params = dict(params or {})
        client_key = params.get("clientTaskKey")
        now = time.monotonic()
        # Client-side retry dedupe: the same clientTaskKey must not launch a second
        # device task within the protocol's duplicate window.
        if client_key:
            cached = self._task_keys.get(str(client_key))
            if cached is not None and now - cached[1] < 120.0:
                duplicate = dict(cached[0])
                duplicate["duplicate"] = True
                return duplicate
        args = {"kind": kind, "params": params, "controlToken": self._control_token}
        if client_key:
            args["clientTaskKey"] = str(client_key)
        result = self.control.request("task.start", args)
        job = self.jobs.create(kind=kind, request_id=str(result.get("requestId", "")),
                               client_task_key=client_key)
        result.setdefault("jobId", job.job_id)
        if client_key:
            self._task_keys[str(client_key)] = (dict(result), now)
            cutoff = now - 120.0
            self._task_keys = {key: value for key, value in self._task_keys.items()
                               if value[1] >= cutoff}
        return result

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        if self.control is None:
            raise BackendError("not_connected", {"reason": "job"})
        if not self._control_token:
            raise BackendError("control_not_held", {"reason": "task.cancel"})
        result = self.control.request("task.cancel",
                                      {"jobId": job_id,
                                       "controlToken": self._control_token})
        self.jobs.request_cancel(job_id)
        return result

    def refresh_job(self, job_id: str) -> dict[str, Any]:
        if self.control is None:
            raise BackendError("not_connected", {"reason": "job"})
        result = self.control.request("job.get", {"jobId": job_id})
        job = self.jobs.update_from_notification(result)
        return job.to_dict()

    # -- recording ---------------------------------------------------------
    def start_recording(self, recording_id: str | None = None) -> dict[str, Any]:
        if self.recorder is not None and self.recorder.state == "recording":
            raise BackendError("recording_active", {"reason": "already-recording"})
        if self.dispatcher is None:
            raise BackendError("bad_state", {"reason": "subscribe-pcm-first"})
        if not any(int(stream_id) == 2 for stream_id in self._consumers):
            raise BackendError("bad_state", {"reason": "pcm-stream-not-subscribed"})
        identifier = recording_id or f"rec-{int(time.time())}"
        directory = self.paths["recordings"] / identifier
        sample_rate = self.last_audio.sample_rate_hz if self.last_audio else 48009.775390625
        self.recorder = Recorder(
            directory, recording_id=identifier,
            device_id=self.device_info.device_id if self.device_info else "unknown",
            connection_epoch=self.connection_epoch or 0,
            session_id=self.session_id or "",
            source_kind=(self.last_audio.source_kind if self.last_audio
                         else "test-fixture"),
            real_sample_rate_hz=sample_rate,
            max_total_bytes=int(self.config_store.values["recordingMaxBytes"]))
        status = self.recorder.start()
        self.recording_id = identifier
        self._emit("recording_changed", status)
        return status

    def stop_recording(self) -> dict[str, Any]:
        if self.recorder is None:
            raise BackendError("bad_state", {"reason": "no-recorder"})
        status = self.recorder.stop()
        if self.recorder.manifest is not None:
            self.storage.save_recording(self.recorder.manifest.to_dict(),
                                        str(self.recorder.directory))
        self._emit("recording_changed", status)
        self.recording_id = None
        return status

    def recording_status(self) -> dict[str, Any]:
        if self.recorder is None:
            return {"recordingId": None, "state": "idle", "records": 0, "bytes": 0,
                    "gaps": 0}
        return self.recorder.status()

    def _on_audio_chunk(self, chunk: AudioChunk) -> None:
        self.last_audio = chunk
        if self._first_audio_chunk is None:
            self._first_audio_chunk = chunk
        self.audio_chunk_count += 1
        # Recording consumes the exact bytes before any display-only extraction.
        if self.recorder is not None and self.recorder.state == "recording":
            try:
                self.recorder.append_audio(chunk.records,
                                           first_sample_index=chunk.first_sample_index,
                                           gap_before=chunk.gap_before)
                self._emit("recording_changed", self.recorder.status())
            except BackendError as exc:
                self._diagnostic("error", "recording_append", exc.to_dict())
        try:
            handle_id = self.data_store.put(chunk.records, "uint8",
                                            display_only=True,
                                            source_kind=chunk.source_kind)
        except BackendError as exc:
            self._diagnostic("error", "audio_buffer", exc.to_dict())
            handle_id = None
        previous = self._audio_handle
        self._audio_handle = handle_id
        if previous is not None:
            self.data_store.release(previous)
        payload = chunk.to_dict()
        payload["records"]["handleId"] = handle_id
        payload["records"]["lifetime"] = "valid until the next audio chunk arrives"
        self._emit("audio_chunk_available", payload)

    def read_buffer(self, handle_id: str, offset_elements: int,
                    count_elements: int) -> bytes:
        """Bounded display read; original measurements stay in the recording files."""
        return self.data_store.read_slice(handle_id, int(offset_elements),
                                          int(count_elements))

    def latest_audio_handle(self) -> str | None:
        return self._audio_handle

    def _on_live_frame(self, frame: LiveFrame) -> None:
        self.last_frame = frame
        self.frame_count += 1
        self._emit("frame_available", frame.to_dict())

    def _on_service_result(self, result: ServiceResult) -> None:
        self.last_service = result
        handle = self.data_store.put(result.words, "uint32", display_only=False,
                                     source_kind=result.source_kind)
        previous = self._service_handle
        self._service_handle = handle
        if previous is not None:
            self.data_store.release(previous)
        payload = result.to_dict()
        payload["words"]["handleId"] = handle
        payload["words"]["lifetime"] = "valid until the next service snapshot"
        self._emit("service_result_available", payload)

    def _on_event_downloaded(self, info: dict[str, Any]) -> None:
        done = self._event_download_done
        if done is not None:
            done.set()
        self._emit("event_added", {"event": info, "state": "stored"})

    # -- events ------------------------------------------------------------
    def list_events(self) -> list[dict[str, Any]]:
        if self.control is None:
            raise BackendError("not_connected", {"reason": "events"})
        result = self.control.request("event.list", {})
        events = []
        for payload in result.get("events", []) or []:
            record = self.event_manager.ingest_known(payload)
            events.append(record.to_dict())
        return events

    def download_event(self, event_id: int) -> dict[str, Any]:
        if self.control is None:
            raise BackendError("not_connected", {"reason": "event-download"})
        meta = self.control.request("event.get", {"eventId": str(event_id)})
        file_info = dict(meta.get("file") or {})
        sha256 = str(file_info.get("sha256", ""))
        if not sha256:
            raise BackendError("bad_state", {"reason": "event-file-hash-missing"})
        total = int(file_info.get("totalBytes", "0"))
        self.event_manager.ingest_known(dict(meta.get("event") or {}))
        previous = self.subscription
        previous_requested = (list(previous.get("requested") or ["resultWords"])
                              if previous is not None else None)
        done = threading.Event()
        self._event_download_done = done
        self._pending_event_download = (int(event_id), sha256, total)
        try:
            self.subscribe(streams=("events",))
            # The stream reader signals this event; never busy-wait on the
            # single session worker. Overall budget stays at 10 s.
            if not done.wait(timeout=10.0):
                raise BackendError("timeout", {"reason": "event-download"})
            consumer = next((item for item in self._consumers.values()
                             if isinstance(item, _EventFileConsumer)), None)
            if consumer is None or not consumer.finished:
                raise BackendError("timeout", {"reason": "event-download"})
            info = self.event_manager._downloaded.get(int(event_id))
            if info is None:
                raise BackendError("internal_error", {"reason": "event-store"})
            ack = self.event_manager.ack(int(event_id), sha256)
            self.control.request("event.ack", {"eventId": str(event_id),
                                               "sha256": sha256})
            return {"eventId": str(event_id), "sha256": sha256,
                    "bytes": str(total), "path": info["path"],
                    "wavFiles":info.get('wavFiles',[]),
                    "ack": ack}
        finally:
            self._pending_event_download = None
            self._event_download_done = None
            try:
                self.unsubscribe()
            except BackendError:
                pass
            # The download temporarily replaced the live subscription; put the
            # caller's previous streams back so live result/PCM keeps flowing.
            if previous_requested:
                try:
                    self.subscribe(streams=previous_requested)
                except BackendError as exc:
                    self._diagnostic("warning", "resubscribe",
                                     {"error": exc.code})

    # -- replay / export ---------------------------------------------------
    def clear_events(self, device: bool = True, local: bool = False) -> dict[str, Any]:
        if self._pending_event_download is not None:
            raise BackendError('busy',{'reason':'event-download-active'})
        removed=0;failed=[];local_count=0
        if device:
            if self.control is None:raise BackendError('not_connected',{'reason':'clear-events'})
            if not self._control_token:self.claim_control()
            ids=[];cursor=None
            while True:
                args={'limit':200}
                if cursor is not None:args['cursor']=cursor
                page=self.control.request('event.list',args)
                ids.extend(str(e['eventId']) for e in page.get('events',[]))
                cursor=page.get('nextCursor')
                if cursor is None:break
            for eid in ids:
                try:
                    self.control.request('event.discard',{'eventId':eid,'controlToken':self._control_token,'reason':'user-confirmed-clear-all'})
                    removed+=1
                except BackendError as exc:failed.append({'eventId':eid,'code':exc.code})
        if local:
            root=self.paths['events'].resolve()
            for folder in root.glob('event-*'):
                suffix=folder.name[6:]
                if len(suffix)==20 and suffix.isdigit() and folder.is_dir() and not folder.is_symlink() and folder.resolve().parent==root:
                    shutil.rmtree(folder);local_count+=1
            audio=root/'录音'
            if audio.is_dir() and not audio.is_symlink() and audio.resolve().parent==root:shutil.rmtree(audio)
        self.event_manager._known.clear();self.event_manager._downloaded.clear()
        return {'deviceRemoved':removed,'localRemoved':local_count,'failed':failed,'exportsPreserved':True}

    def open_recording(self, path: str | Path) -> dict[str, Any]:
        manifest_path = Path(path)
        if manifest_path.is_dir():
            manifest_path = manifest_path / "manifest.json"
        self.replay = ReplaySession(manifest_path)
        return self.replay.info()

    def seek_playback(self, sample_index: int | None = None, *,
                      fraction: float | None = None) -> dict[str, Any]:
        if self.replay is None:
            raise BackendError("replay_state", {"reason": "no-recording-open"})
        return self.replay.seek(sample_index, fraction=fraction)

    def set_playback_state(self, state: str) -> dict[str, Any]:
        if self.replay is None:
            raise BackendError("replay_state", {"reason": "no-recording-open"})
        return self.replay.set_state(state)

    def next_playback_chunk(self, max_records: int = 150) -> AudioChunk | None:
        if self.replay is None:
            raise BackendError("replay_state", {"reason": "no-recording-open"})
        return self.replay.next_chunk(max_records)

    def export_data(self, directory: str | Path | None = None) -> dict[str, Any]:
        """Export WAV/CSV/JSON for the current recording or open replay."""
        if directory:
            target = Path(directory)
        else:
            # Keep the historical export-<epoch> prefix but never reuse a directory
            # for two exports made within the same wall-clock second.
            target = (self.paths["exports"] /
                      f"export-{int(time.time())}-{uuid.uuid4().hex[:8]}")
        target.mkdir(parents=True, exist_ok=True)
        manifest = None
        if self.recorder is not None and self.recorder.manifest is not None:
            manifest = self.recorder.manifest.to_dict()
            source_dir = self.recorder.directory
        elif self.replay is not None:
            manifest = self.replay.manifest
            source_dir = self.replay.manifest_path.parent
        else:
            raise BackendError("bad_state", {"reason": "nothing-to-export"})
        csv_path = target / "recording-summary.csv"
        lines = ["field,value"]
        for key in ("recordingId", "deviceId", "sessionId", "sourceKind",
                    "realSampleRateHz", "integerRateHz", "rateRoundingErrorHz",
                    "records", "firstSampleIndex", "lastSampleIndex"):
            lines.append(f"{key},{manifest.get(key)}")
        lines.append("gaps," + str(len(manifest.get("gaps", []))))
        csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        paths = {"csv": str(csv_path)}
        wav = manifest.get("wav") or {}
        if wav.get("path") and Path(wav["path"]).is_file():
            import shutil
            copied = target / "audio-6ch-24bit.wav"
            shutil.copyfile(wav["path"], copied)
            paths["wav"] = str(copied)
        manifest_copy = target / "manifest.json"
        import json
        manifest_copy.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
        paths["manifest"] = str(manifest_copy)
        paths["sourceDirectory"] = str(source_dir)
        return paths

    # -- diagnostics / status ---------------------------------------------
    def read_diagnostics(self, tail_lines: int = 200) -> dict[str, Any]:
        local = self.diagnostics.tail(tail_lines)
        result: dict[str, Any] = {"local": local,
                                  "localStats": self.diagnostics.stats()}
        if self.control is not None:
            try:
                result["device"] = self.control.request("diagnostics.get",
                                                        {"tailLines": int(tail_lines)})
            except BackendError as exc:
                result["deviceError"] = exc.to_dict()
        return result

    def status(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "host": self.host, "controlPort": self.control_port,
            "binaryPort": self.binary_port,
            "deviceId": self.device_info.device_id if self.device_info else None,
            "connectionEpoch": None if self.connection_epoch is None
            else str(self.connection_epoch),
            "sessionId": self.session_id,
            "controlHeld": bool(self._control_token),
            "subscription": self.subscription,
            "capabilities": self.capabilities.to_dict(),
            "frames": self.frame_count, "audioChunks": self.audio_chunk_count,
            "recording": self.recording_status(),
            "jobs": self.jobs.stats(),
            "dataStore": self.data_store.stats(),
            "storage": self.storage.stats(),
            "features": self.feature_catalog.summary() if self.feature_catalog else None,
            "replay": self.replay.status() if self.replay else None,
            "controlTransport": self.control.stats() if self.control else None,
            "binaryTransport": self.binary.stats() if self.binary else None,
            "dispatcher": {str(key): value.to_dict()
                           for key, value in (self.dispatcher.states().items()
                                              if self.dispatcher else [])},
            "userDataDir": str(self.paths["root"]),
        }

    def close(self) -> None:
        try:
            self.disconnect()
        finally:
            if self.recorder is not None and self.recorder.state == "recording":
                try:
                    self.recorder.stop()
                except BackendError:
                    pass
            self.storage.close()

    # -- callbacks from transports ----------------------------------------
    def _set_state(self, state: str, *, error: BackendError | None = None) -> None:
        self.state = state
        payload = {"state": state, "host": self.host,
                   "controlPort": self.control_port, "binaryPort": self.binary_port,
                   "error": None if error is None else error.to_dict(),
                   "monotonicNs": str(time.monotonic_ns())}
        self._emit("connection_changed", payload)

    def _on_control_state(self, state: str, detail: dict[str, Any]) -> None:
        if self._intentional_disconnect:
            return
        self._set_state(state, error=None)
        if state in ('disconnected','failed','degraded'):
            self._control_token=None;self._recovery_serial+=1
        if state == "connected" and self.subscription is not None:
            # This callback runs on the control reader. Never block that reader
            # waiting for responses which only this same reader can receive.
            self._recovery_serial+=1;ticket=self._recovery_serial
            requested=list(self.subscription.get('requested',['resultWords']));control=self.control
            def recover():
                try:
                    if self._intentional_disconnect or ticket!=self._recovery_serial or self.control is not control:return
                    self.hello=control.hello
                    self.refresh_capabilities()
                    if not self._intentional_disconnect and ticket==self._recovery_serial:self.subscribe(streams=requested)
                except BackendError as exc:self._diagnostic('warning','resubscribe',{'error':exc.code})
            threading.Thread(target=recover,name='sixmic-resubscribe',daemon=True).start()
        if state in ("disconnected", "failed") and self.binary is not None:
            try:
                self.binary.close()
            finally:
                self.binary = None

    def _on_control_event(self, name: str, event_id: int, data: dict[str, Any]) -> None:
        if name=='controlLost' or (name=='controlChanged' and data.get('held') is False):self._control_token=None
        if name == "jobUpdated":
            job = self.jobs.update_from_notification(data)
            self._emit("operation_updated", job.to_dict())
        elif name == "eventAdded":
            try:
                record = self.event_manager.ingest_known(data)
                self._emit("event_added", record.to_dict())
            except BackendError as exc:
                self._diagnostic("warning", "event_added", {"error": exc.code})
        elif name in ("deviceState", "configApplied", "recordingChanged",
                      "controlChanged"):
            self._emit("operation_updated", {"event": name, "data": data})
        elif name == "diagnosticAdded":
            self._emit("diagnostic_added", dict(data))
        elif name == "streamGap":
            self._emit("stream_gap", dict(data))

    def _on_binary_closed(self, error: BackendError | None) -> None:
        if self._intentional_disconnect or self._subscription_switching:
            return
        if error is not None:
            self._diagnostic("warning", "binary_closed", error.to_dict())
        # A closed data channel does not by itself drop the control session:
        # keep "connected" and surface the binary state so the UI can show a
        # stale-data / re-subscribe state instead of a false device disconnect.
        self._emit("operation_updated", {"binary": "closed",
                                         "error": None if error is None else error.to_dict()})
        self._emit("frame_available", {
            "sourceKind": "pl-live", "validity": {"stale": True,
                                                  "reason": "binary-closed"},
            "deviceId": self.device_info.device_id if self.device_info else None,
            "note": "stale marker only; no fabricated sample data"})
