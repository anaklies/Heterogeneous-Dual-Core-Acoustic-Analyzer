"""QObject adapter for QML: async slots return requestId/jobId; never blocks QML.

Threading contract:
- every DeviceSession call runs on one dedicated worker thread (never the GUI thread)
- listener callbacks originate on worker threads and are forwarded as Qt signals,
  which Qt delivers queued to the GUI thread
- signals carry JSON strings / QVariantMaps whose 64-bit counters are decimal
  strings, so QML never performs double math on sample indices or epochs
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

try:  # PySide6 is required only for the Qt layer, not for the backend core.
    from PySide6.QtCore import (QAbstractListModel, QModelIndex, QObject, Property,
                                Qt, Signal, Slot)
    QT_AVAILABLE = True
    QT_IMPORT_ERROR: str | None = None
except Exception as exc:  # pragma: no cover - exercised only without PySide6
    QT_AVAILABLE = False
    QT_IMPORT_ERROR = str(exc)

    class QObject:  # type: ignore[no-redef]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    class QAbstractListModel:  # type: ignore[no-redef]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    class QModelIndex:  # type: ignore[no-redef]
        pass

    class Signal:  # type: ignore[no-redef]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    def Slot(*args: Any, **kwargs: Any):  # type: ignore[no-redef]
        def decorator(function):
            return function
        return decorator

    def Property(*args: Any, **kwargs: Any):  # type: ignore[no-redef]
        def decorator(function):
            return function
        return decorator

    class Qt:  # type: ignore[no-redef]
        DisplayRole = 0
        UserRole = 256


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False, default=str)


class _SessionListener:
    """Forwards DeviceSession callbacks into Qt signals (thread-safe emit)."""

    def __init__(self, bridge: "BackendBridge") -> None:
        self.bridge = bridge

    def connection_changed(self, state: dict[str, Any]) -> None:
        self.bridge._connection_internal.emit(_json(state))

    def capabilities_changed(self, capabilities: dict[str, Any]) -> None:
        self.bridge._capabilities_internal.emit(_json(capabilities))

    def operation_updated(self, job: dict[str, Any]) -> None:
        self.bridge._operation_internal.emit(_json(job))

    def frame_available(self, frame: dict[str, Any]) -> None:
        self.bridge._frame_internal.emit(_json(frame))

    def audio_chunk_available(self, chunk: dict[str, Any]) -> None:
        self.bridge._audio_internal.emit(_json(chunk))

    def service_result_available(self, result: dict[str, Any]) -> None:
        self.bridge._service_internal.emit(_json(result))

    def event_added(self, event: dict[str, Any]) -> None:
        self.bridge._event_internal.emit(_json(event))

    def recording_changed(self, status: dict[str, Any]) -> None:
        self.bridge._recording_internal.emit(_json(status))

    def diagnostic_added(self, diagnostic: dict[str, Any]) -> None:
        self.bridge._diagnostic_internal.emit(_json(diagnostic))

    def stream_gap(self, gap: dict[str, Any]) -> None:
        self.bridge._gap_internal.emit(_json(gap))


if QT_AVAILABLE:
    class EventListModel(QAbstractListModel):
        Roles = {Qt.DisplayRole: b"summary", Qt.UserRole + 1: b"payload"}
        MAX_ROWS = 500

        def __init__(self, parent: QObject | None = None) -> None:
            super().__init__(parent)
            self._rows: list[dict[str, Any]] = []

        def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
            return 0 if parent.isValid() else len(self._rows)

        def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
            if not index.isValid() or not 0 <= index.row() < len(self._rows):
                return None
            row = self._rows[index.row()]
            if role == Qt.UserRole + 1:
                return _json(row)
            if role == Qt.DisplayRole:
                return row.get("summary", "")
            return None

        def roleNames(self) -> dict[int, bytes]:  # noqa: N802
            return dict(self.Roles)

        def add(self, payload: dict[str, Any], summary: str) -> None:
            position = 0
            self.beginInsertRows(QModelIndex(), position, position)
            self._rows.insert(position, {"summary": summary, "payload": payload})
            if len(self._rows) > self.MAX_ROWS:
                self._rows.pop()
            self.endInsertRows()

        def clear(self) -> None:
            self.beginResetModel()
            self._rows.clear()
            self.endResetModel()


    class BackendBridge(QObject):
        # Public signals (QML): payloads are JSON strings with u64 as strings.
        connectionChanged = Signal(str)
        capabilitiesChanged = Signal(str)
        operationUpdated = Signal(str)
        frameAvailable = Signal(str)
        audioChunkAvailable = Signal(str)
        serviceResultAvailable = Signal(str)
        eventAdded = Signal(str)
        jobUpdated = Signal(str)
        recordingChanged = Signal(str)
        diagnosticAdded = Signal(str)
        streamGap = Signal(str)
        playbackChunkAvailable = Signal(str)
        requestFinished = Signal(str)
        backendError = Signal(str)
        # Internal worker-thread -> GUI-thread hops.
        _connection_internal = Signal(str)
        _capabilities_internal = Signal(str)
        _operation_internal = Signal(str)
        _frame_internal = Signal(str)
        _audio_internal = Signal(str)
        _service_internal = Signal(str)
        _event_internal = Signal(str)
        _recording_internal = Signal(str)
        _diagnostic_internal = Signal(str)
        _gap_internal = Signal(str)
        _playback_internal = Signal(str)
        _job_internal = Signal(str)
        _finished_internal = Signal(str)
        _error_internal = Signal(str)
        processEvents = Signal()

        def __init__(self, *, protocol_root: str | None = None,
                     parent: QObject | None = None) -> None:
            super().__init__(parent)
            self._executor = ThreadPoolExecutor(max_workers=1,
                                                thread_name_prefix="sixmic-session")
            self._result_executor = ThreadPoolExecutor(max_workers=1,
                                                       thread_name_prefix="sixmic-results")
            self._shutting_down=False
            self._lock = threading.Lock()
            self._session: Any = None
            self._counter = 0
            self._status_json = _json({"state": "disconnected"})
            self._event_model = EventListModel(self)
            self._diagnostic_model = EventListModel(self)
            self._protocol_root = protocol_root
            self._connection_internal.connect(self.connectionChanged)
            self._capabilities_internal.connect(self.capabilitiesChanged)
            self._operation_internal.connect(self.operationUpdated)
            self._frame_internal.connect(self.frameAvailable)
            self._audio_internal.connect(self.audioChunkAvailable)
            self._service_internal.connect(self.serviceResultAvailable)
            self._event_internal.connect(self.eventAdded)
            self._recording_internal.connect(self.recordingChanged)
            self._diagnostic_internal.connect(self.diagnosticAdded)
            self._gap_internal.connect(self.streamGap)
            self._playback_internal.connect(self.playbackChunkAvailable)
            self._job_internal.connect(self.jobUpdated)
            self._finished_internal.connect(self.requestFinished)
            self._error_internal.connect(self.backendError)
            self._event_internal.connect(self._on_event_row)
            self._diagnostic_internal.connect(self._on_diagnostic_row)
            self._operation_internal.connect(self._on_operation)
            self._connection_internal.connect(self._on_connection)
            self.processEvents.connect(self._on_process_events)

        # -- QML properties -------------------------------------------------
        def _get_status(self) -> str:
            return self._status_json

        statusJson = Property(str, _get_status, constant=False)

        def _get_qt_available(self) -> bool:
            return QT_AVAILABLE

        qtAvailable = Property(bool, _get_qt_available, constant=True)

        def _get_backend_version(self) -> str:
            from .. import __version__
            return __version__

        backendVersion = Property(str, _get_backend_version, constant=True)

        def _get_feature_catalog(self) -> str:
            """Frozen 52-row feature catalog (JSON) for the UI to group/label."""
            if getattr(self, "_feature_catalog_json", None) is None:
                try:
                    from ..model.feature_catalog import load_feature_catalog
                    catalog = load_feature_catalog(self._protocol_root)
                    self._feature_catalog_json = _json(catalog.to_dict())
                except Exception:
                    self._feature_catalog_json = _json({"features": [],
                                                        "summary": {"total": 0}})
            return self._feature_catalog_json

        featureCatalogJson = Property(str, _get_feature_catalog, constant=True)

        def _get_event_model(self) -> "EventListModel":
            return self._event_model

        eventModel = Property(QObject, _get_event_model, constant=True)

        def _get_diagnostic_model(self) -> "EventListModel":
            return self._diagnostic_model

        diagnosticModel = Property(QObject, _get_diagnostic_model, constant=True)

        # -- internal slots (GUI thread) -----------------------------------
        @Slot(str)
        def _on_event_row(self, payload: str) -> None:
            try:
                data = json.loads(payload)
            except ValueError:
                return
            event = data.get("event", data)
            summary = f"event {event.get('eventId', '?')} {data.get('state', '')}"
            self._event_model.add(data, summary)

        @Slot(str)
        def _on_diagnostic_row(self, payload: str) -> None:
            try:
                data = json.loads(payload)
            except ValueError:
                return
            self._diagnostic_model.add(data, f"{data.get('level', 'info')} {data.get('code', '')}")

        @Slot(str)
        def _on_operation(self, payload: str) -> None:
            try:
                data = json.loads(payload)
            except ValueError:
                return
            if data.get("jobId") or data.get("state") in ("accepted", "running",
                                                          "completed", "failed",
                                                          "canceled", "cancel_requested"):
                self.jobUpdated.emit(payload)

        @Slot(str)
        def _on_connection(self, payload: str) -> None:
            self._status_json = payload

        @Slot()
        def _on_process_events(self) -> None:
            return None

        # -- helpers --------------------------------------------------------
        def _next_request_id(self) -> str:
            with self._lock:
                self._counter += 1
                return f"ui-{self._counter:08d}"

        def _session_or_none(self) -> Any:
            return self._session

        def _submit(self, op: str, function, *args: Any, **kwargs: Any) -> str:
            request_id = self._next_request_id()

            def run() -> None:
                try:
                    result = function(*args, **kwargs) if function else None
                    if self._shutting_down:return
                    if result is not None:
                        self._finished_internal.emit(_json(
                            {"requestId": request_id, "op": op, "status": "ok",
                             "result": result}))
                    else:
                        self._finished_internal.emit(_json(
                            {"requestId": request_id, "op": op, "status": "accepted"}))
                except Exception as exc:  # BackendError or unexpected
                    if self._shutting_down:return
                    payload = {"requestId": request_id, "op": op, "status": "error"}
                    error = getattr(exc, "to_dict", None)
                    payload["error"] = error() if callable(error) else {
                        "code": "internal_error", "messageKey": "errors.internal_error",
                        "retryable": False, "detail": {"detail": str(exc)[:300]}}
                    self._error_internal.emit(_json(payload))

            executor = self._result_executor if op == "getFeatureResult" else self._executor
            executor.submit(run)
            return request_id

        def _ensure_session(self, host: str | None = None,
                            control_port: int | None = None,
                            binary_port: int | None = None) -> Any:
            from ..session import DeviceSession
            listener = _SessionListener(self)
            if self._session is None:
                self._session = DeviceSession(
                    host=host, control_port=control_port, binary_port=binary_port,
                    protocol_root=self._protocol_root, listener=listener,
                    auto_reconnect=True)
            return self._session

        @Slot(object)
        def attachSession(self, session: Any) -> None:  # noqa: N802 - QML/dev hook
            """Attach an already-created DeviceSession (tests/dev tools only)."""
            if self._session is not None and self._session is not session:
                try:
                    self._session.close()
                except Exception:
                    pass
            self._session = session
            session.add_listener(_SessionListener(self))

        # -- async slots ----------------------------------------------------
        @Slot(str, int, int, result=str)
        def connectDevice(self, host: str, controlPort: int = 48120,
                          binaryPort: int = 48121) -> str:  # noqa: N802
            return self._submit("connectDevice",
                                lambda: self._ensure_session(host, controlPort or None,
                                                             binaryPort or None).connect())

        @Slot(result=str)
        def disconnectDevice(self) -> str:  # noqa: N802
            session = self._session_or_none()
            if session is None:
                return self._next_request_id()
            return self._submit("disconnectDevice", session.disconnect)

        @Slot(result=str)
        def refreshCapabilities(self) -> str:  # noqa: N802
            session = self._session_or_none()
            return self._submit("refreshCapabilities",
                                session.refresh_capabilities if session else None)

        @Slot(result=str)
        def claimControl(self) -> str:  # noqa: N802
            session = self._session_or_none()
            return self._submit("claimControl", session.claim_control if session else None)

        @Slot(result=str)
        def releaseControl(self) -> str:  # noqa: N802
            session = self._session_or_none()
            return self._submit("releaseControl", session.release_control if session else None)

        @Slot(str, result=str)
        def subscribe(self, streamsJson: str) -> str:  # noqa: N802
            try:
                streams = json.loads(streamsJson or '["resultWords"]')
            except ValueError:
                streams = ["resultWords"]
            session = self._session_or_none()
            return self._submit("subscribe",
                                session.subscribe if session else None, streams)

        @Slot(result=str)
        def unsubscribe(self) -> str:  # noqa: N802
            session = self._session_or_none()
            return self._submit("unsubscribe", session.unsubscribe if session else None)

        @Slot(str, str, result=str)
        def startJob(self, kind: str, paramsJson: str = "{}") -> str:  # noqa: N802
            try:
                params = json.loads(paramsJson or "{}")
            except ValueError:
                params = {}
            session = self._session_or_none()
            return self._submit("startJob", session.start_job if session else None,
                                kind, params)

        @Slot(str, result=str)
        def cancelJob(self, jobId: str) -> str:  # noqa: N802
            session = self._session_or_none()
            return self._submit("cancelJob", session.cancel_job if session else None,
                                jobId)

        @Slot(result=str)
        def startRecording(self) -> str:  # noqa: N802
            session = self._session_or_none()
            return self._submit("startRecording", session.start_recording if session else None)

        @Slot(result=str)
        def stopRecording(self) -> str:  # noqa: N802
            session = self._session_or_none()
            return self._submit("stopRecording", session.stop_recording if session else None)

        @Slot(str, int, int, result="QVariant")
        def readBuffer(self, handleId: str, offsetElements: int = 0,
                       countElements: int = 4096):  # noqa: N802
            from PySide6.QtCore import QByteArray
            session = self._session_or_none()
            if session is None:
                return QByteArray()
            try:
                return QByteArray(session.read_buffer(handleId, offsetElements,
                                                      countElements))
            except Exception:
                return QByteArray()

        @Slot(result=str)
        def listEvents(self) -> str:  # noqa: N802
            session = self._session_or_none()
            return self._submit("listEvents", session.list_events if session else None)

        @Slot(str, result=str)
        def downloadEvent(self, eventId: str) -> str:  # noqa: N802
            session = self._session_or_none()
            return self._submit("downloadEvent", session.download_event if session else None,
                                int(eventId))

        @Slot(bool, bool, result=str)
        def clearEvents(self, device: bool, local: bool) -> str:  # noqa: N802
            session=self._session_or_none()
            return self._submit('clearEvents',session.clear_events if session else None,bool(device),bool(local))

        @Slot(int, result=str)
        def requestPlaybackChunk(self, maxRecords: int = 150) -> str:  # noqa: N802
            """Pull one replay chunk on the worker thread (Timer-driven in QML)."""
            request_id = self._next_request_id()
            session = self._session_or_none()
            limit = int(maxRecords) or 150

            def run() -> None:
                try:
                    if session is None:
                        raise RuntimeError("no session")
                    chunk = session.next_playback_chunk(limit)
                    if chunk is None:
                        self._playback_internal.emit(_json({"state": "eof",
                                                            "requestId": request_id}))
                        return
                    handle = session.data_store.put(
                        chunk.records, "uint8", display_only=True,
                        source_kind=chunk.source_kind)
                    previous = getattr(self, "_playback_handle", None)
                    self._playback_handle = handle
                    if previous is not None:
                        session.data_store.release(previous)
                    payload = chunk.to_dict()
                    payload["records"]["handleId"] = handle
                    payload["records"]["lifetime"] = "valid until the next playback chunk"
                    payload["requestId"] = request_id
                    self._playback_internal.emit(_json(payload))
                except Exception as exc:
                    payload = {"requestId": request_id, "op": "requestPlaybackChunk",
                               "status": "error",
                               "error": {"code": "replay_state",
                                         "messageKey": "errors.replay_state",
                                         "retryable": False,
                                         "detail": {"detail": str(exc)[:200]}}}
                    self._error_internal.emit(_json(payload))

            self._executor.submit(run)
            return request_id

        @Slot(str, result=str)
        def openRecording(self, path: str) -> str:  # noqa: N802
            session = self._session_or_none()
            return self._submit("openRecording", session.open_recording if session else None,
                                path)

        @Slot(str, str, result=str)
        def seekPlayback(self, sampleIndex: str, fraction: str = "") -> str:  # noqa: N802
            session = self._session_or_none()
            index = int(sampleIndex) if sampleIndex else None
            ratio = float(fraction) if fraction else None
            return self._submit("seekPlayback",
                                session.seek_playback if session else None,
                                index, ratio)

        @Slot(str, result=str)
        def setPlaybackState(self, state: str) -> str:  # noqa: N802
            session = self._session_or_none()
            return self._submit("setPlaybackState",
                                session.set_playback_state if session else None, state)

        @Slot(str, result=str)
        def exportData(self, directory: str) -> str:  # noqa: N802
            session = self._session_or_none()
            target = directory or None
            return self._submit("exportData", session.export_data if session else None,
                                target)

        @Slot(int, result=str)
        def readDiagnostics(self, tailLines: int = 200) -> str:  # noqa: N802
            session = self._session_or_none()
            return self._submit("readDiagnostics",
                                session.read_diagnostics if session else None, tailLines)

        @Slot(result=str)
        def status(self) -> str:
            session = self._session_or_none()
            if session is None:
                return _json({"state": "disconnected"})
            return _json(session.status())

        def shutdown(self) -> None:
            self._shutting_down=True
            session = self._session_or_none()
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._result_executor.shutdown(wait=False, cancel_futures=True)

else:  # pragma: no cover - only when PySide6 is missing
    class BackendBridge(QObject):  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            super().__init__()
            raise RuntimeError(f"PySide6 unavailable: {QT_IMPORT_ERROR}")

    class EventListModel(QAbstractListModel):  # type: ignore[no-redef]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__()


def create_bridge(*, protocol_root: str | None = None) -> "BackendBridge":
    if not QT_AVAILABLE:
        from ..errors import BackendError
        raise BackendError("qt_unavailable", {"detail": QT_IMPORT_ERROR})
    return BackendBridge(protocol_root=protocol_root)
