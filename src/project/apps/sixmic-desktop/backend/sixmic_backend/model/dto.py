"""Stable DTOs (pc-backend-dto v1).

All 64-bit counters are Python ints here and decimal strings at JSON/QML
boundaries. Not-applicable fields are None, never 0 pretending to be valid.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..constants import (
    CAP_AVAILABLE, CAP_STATES, PCM_CHANNELS, PCM_CHANNEL_NAMES, PCM_SAMPLE_FORMAT,
    PCM_UNITS, PROTOCOL_VERSION, SOURCE_KINDS, SOURCE_TEST_FIXTURE,
)

def capability_state(value: Any, default: str = "not_ready") -> str:
    """Normalize a capability state from either protocol revision.

    The frozen v1 backend models capability states as strings
    (available/experimental/not_ready/disabled/unsupported). The
    echo-features-1 candidate gateway serializes the same capabilities as
    booleans. Accept both encodings here so a new gateway does not break the
    frozen session layer; a missing value keeps its documented default.
    """
    if isinstance(value, str) and value in CAP_STATES:
        return value
    if isinstance(value, bool):
        return CAP_AVAILABLE if value else "not_ready"
    return default
from ..errors import BackendError
from ..protocol.control import parse_u64, u64


def _json(obj: Any) -> Any:
    """Recursively convert DTO values into JSON-safe structures."""
    if isinstance(obj, dict):
        return {str(key): _json(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json(value) for value in obj]
    return obj


def _require_source_kind(source_kind: str) -> None:
    if source_kind not in SOURCE_KINDS:
        raise BackendError("bad_args", {"field": "sourceKind", "value": source_kind})


@dataclass(frozen=True)
class ErrorInfo:
    code: str
    message_key: str
    retryable: bool
    detail: dict[str, Any] = field(default_factory=dict)
    occurred_monotonic_ns: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "messageKey": self.message_key,
                "retryable": bool(self.retryable), "detail": _json(self.detail),
                "occurredMonotonicNs": u64(self.occurred_monotonic_ns)}

    @classmethod
    def from_error(cls, error: Any, occurred_monotonic_ns: int = 0) -> "ErrorInfo":
        if isinstance(error, ErrorInfo):
            return error
        return cls(str(error.get("code", "internal_error")),
                   str(error.get("messageKey", "errors.internal_error")),
                   bool(error.get("retryable", False)),
                   dict(error.get("detail") or {}), occurred_monotonic_ns)


@dataclass
class DeviceCapabilities:
    live_pcm: str = "not_ready"
    live_results: str = "not_ready"
    result_snapshot_protocol: int = 3
    service_snapshots: list[str] = field(default_factory=list)
    event_capture: str = "not_ready"
    event_download: str = "not_ready"
    raw_recording: str = "not_ready"
    profile_upload: str = "not_ready"
    profile_activate: str = "not_ready"
    task_control: str = "not_ready"
    sensor_snapshot: str = "not_ready"
    device_log: str = "available"
    config_commit: str = "not_ready"
    config_version: int = 0
    protocol3: bool = False
    missing: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for name in ("live_pcm", "live_results", "event_capture", "event_download",
                     "raw_recording", "profile_upload", "profile_activate",
                     "task_control", "sensor_snapshot", "device_log", "config_commit"):
            value = getattr(self, name)
            if value not in CAP_STATES:
                raise BackendError("bad_args", {"field": name, "value": value})
        if self.live_pcm == CAP_AVAILABLE and "PL raw ring PS consumer/lease not accepted" in \
                " ".join(self.missing):
            raise BackendError("bad_state", {"reason": "livePcm-availability-contradiction"})

    def to_dict(self) -> dict[str, Any]:
        return {
            "livePcm": self.live_pcm, "liveResults": self.live_results,
            "resultSnapshotProtocol": self.result_snapshot_protocol,
            "serviceSnapshots": list(self.service_snapshots),
            "eventCapture": self.event_capture, "eventDownload": self.event_download,
            "rawRecording": self.raw_recording, "profileUpload": self.profile_upload,
            "profileActivate": self.profile_activate, "taskControl": self.task_control,
            "sensorSnapshot": self.sensor_snapshot, "deviceLog": self.device_log,
            "configCommit": self.config_commit, "configVersion": self.config_version,
            "protocol3": bool(self.protocol3), "missing": list(self.missing),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeviceCapabilities":
        return cls(
            live_pcm=capability_state(data.get("livePcm"), "not_ready"),
            live_results=capability_state(data.get("liveResults"), "not_ready"),
            result_snapshot_protocol=int(data.get("resultSnapshotProtocol", 3)),
            service_snapshots=list(data.get("serviceSnapshots") or []),
            event_capture=capability_state(data.get("eventCapture"), "not_ready"),
            event_download=capability_state(data.get("eventDownload"), "not_ready"),
            raw_recording=capability_state(data.get("rawRecording"), "not_ready"),
            profile_upload=capability_state(data.get("profileUpload"), "not_ready"),
            profile_activate=capability_state(data.get("profileActivate"), "not_ready"),
            task_control=capability_state(data.get("taskControl"), "not_ready"),
            sensor_snapshot=capability_state(data.get("sensorSnapshot"), "not_ready"),
            device_log=capability_state(data.get("deviceLog"), "available"),
            config_commit=capability_state(data.get("configCommit"), "not_ready"),
            config_version=int(data.get("configVersion", 0)),
            protocol3=bool(data.get("protocol3", False)),
            missing=list(data.get("missing") or []),
        )


@dataclass
class DeviceInfo:
    device_id: str
    firmware_id: int | None = None
    hardware_protocol_version: int = 3
    gateway_version: str = ""
    network_protocol_version: int = PROTOCOL_VERSION
    connection_epoch: int = 0
    sample_rate_hz: float | None = None
    board_base_address: str | None = None
    capabilities: DeviceCapabilities = field(default_factory=DeviceCapabilities)
    verified_on_board: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"deviceId": self.device_id,
                "firmwareId": self.firmware_id,
                "hardwareProtocolVersion": self.hardware_protocol_version,
                "gatewayVersion": self.gateway_version,
                "networkProtocolVersion": self.network_protocol_version,
                "connectionEpoch": u64(self.connection_epoch),
                "sampleRateHz": self.sample_rate_hz,
                "boardBaseAddress": self.board_base_address,
                "capabilities": self.capabilities.to_dict(),
                "verifiedOnBoard": bool(self.verified_on_board)}


@dataclass
class ConnectionState:
    state: str = "disconnected"
    host: str = ""
    control_port: int = 48120
    binary_port: int = 48121
    device_id: str | None = None
    connection_epoch: int | None = None
    session_id: str | None = None
    control_held: bool = False
    control_expires_in_ms: int | None = None
    reconnect_attempt: int = 0
    last_error: ErrorInfo | None = None
    changed_monotonic_ns: int = 0

    STATES = ("disconnected", "connecting", "handshaking", "connected",
              "degraded", "reconnecting", "failed")

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state, "host": self.host,
                "controlPort": self.control_port, "binaryPort": self.binary_port,
                "deviceId": self.device_id,
                "connectionEpoch": None if self.connection_epoch is None else u64(self.connection_epoch),
                "sessionId": self.session_id, "controlHeld": self.control_held,
                "controlExpiresInMs": self.control_expires_in_ms,
                "reconnectAttempt": self.reconnect_attempt,
                "lastError": None if self.last_error is None else self.last_error.to_dict(),
                "changedMonotonicNs": u64(self.changed_monotonic_ns)}


@dataclass
class BufferRef:
    handle_id: str
    bytes: int
    element_type: str
    count: int
    layout: str = "interleaved"
    alignment: int = 1
    display_only: bool = False
    source_kind: str = SOURCE_TEST_FIXTURE
    sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"handleId": self.handle_id, "bytes": u64(self.bytes),
                "elementType": self.element_type, "count": self.count,
                "layout": self.layout, "alignment": self.alignment,
                "displayOnly": bool(self.display_only),
                "sourceKind": self.source_kind, "sha256": self.sha256}


@dataclass
class SensorSnapshot:
    temperature_c: float | None = None
    humidity_raw: int | None = None
    pressure_pa: int | None = None
    sound_speed_mps: float | None = None
    valid: dict[str, bool] = field(default_factory=dict)
    environment_mode: int | None = None
    pose_raw: dict[str, Any] | None = None
    sensor_errors: int = 0
    sensor_faults: int = 0
    env_sequence: int = 0
    pose_sequence: int = 0
    device_monotonic_ns: int | None = None
    imu_scale_status: str = "unverified"

    def to_dict(self) -> dict[str, Any]:
        return {"temperatureC": self.temperature_c,
                "humidityRaw": self.humidity_raw,
                "pressurePa": self.pressure_pa,
                "soundSpeedMps": self.sound_speed_mps,
                "valid": dict(self.valid), "environmentMode": self.environment_mode,
                "poseRaw": _json(self.pose_raw),
                "sensorErrors": self.sensor_errors, "sensorFaults": self.sensor_faults,
                "envSequence": self.env_sequence, "poseSequence": self.pose_sequence,
                "deviceMonotonicNs": None if self.device_monotonic_ns is None
                else u64(self.device_monotonic_ns),
                "imuScaleStatus": self.imu_scale_status}


@dataclass
class LiveFrame:
    source_kind: str
    device_id: str
    connection_epoch: int
    session_id: str
    frame_id: int
    config_version: int
    sample_index: int
    sample_rate_hz: float
    words: tuple[int, ...]
    decoded: dict[str, Any]
    device_monotonic_ns: int | None = None
    received_monotonic_ns: int = 0
    validity: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_source_kind(self.source_kind)
        if len(self.words) != 32:
            raise BackendError("bad_args", {"field": "words"})

    def to_dict(self) -> dict[str, Any]:
        return {"sourceKind": self.source_kind, "deviceId": self.device_id,
                "connectionEpoch": u64(self.connection_epoch),
                "sessionId": self.session_id, "frameId": self.frame_id,
                "configVersion": self.config_version,
                "sampleIndex": u64(self.sample_index),
                "sampleRateHz": self.sample_rate_hz,
                "deviceMonotonicNs": None if self.device_monotonic_ns is None
                else u64(self.device_monotonic_ns),
                "receivedMonotonicNs": u64(self.received_monotonic_ns),
                "algorithmId": self.decoded.get("algorithmId"),
                "faults": self.decoded.get("faults"),
                "words": list(self.words), "decoded": _json(self.decoded),
                "validity": _json(self.validity), "quality": _json(self.quality)}


@dataclass
class AudioChunk:
    source_kind: str
    device_id: str
    connection_epoch: int
    session_id: str
    stream_id: int
    first_sample_index: int
    sample_count: int
    sample_rate_hz: float
    records: bytes
    gap_before: bool = False
    continuity: dict[str, Any] = field(default_factory=dict)
    device_monotonic_ns: int | None = None
    display_only: bool = False

    def __post_init__(self) -> None:
        _require_source_kind(self.source_kind)
        if len(self.records) != self.sample_count * 32:
            raise BackendError("bad_args", {"field": "records",
                                            "reason": "record-count-mismatch"})

    def to_dict(self) -> dict[str, Any]:
        return {"sourceKind": self.source_kind, "deviceId": self.device_id,
                "connectionEpoch": u64(self.connection_epoch),
                "sessionId": self.session_id, "streamId": self.stream_id,
                "firstSampleIndex": u64(self.first_sample_index),
                "sampleCount": self.sample_count, "channels": PCM_CHANNELS,
                "channelOrder": list(PCM_CHANNEL_NAMES),
                "sampleFormat": PCM_SAMPLE_FORMAT,
                "sampleRateHz": self.sample_rate_hz, "units": PCM_UNITS,
                "records": {"handleId": f"audio-{self.first_sample_index:x}",
                            "bytes": len(self.records),
                            "elementType": "uint8", "count": len(self.records),
                            "layout": "interleaved", "alignment": 32,
                            "displayOnly": bool(self.display_only),
                            "sourceKind": self.source_kind, "sha256": None},
                "gapBefore": bool(self.gap_before),
                "continuity": _json(self.continuity),
                "deviceMonotonicNs": None if self.device_monotonic_ns is None
                else u64(self.device_monotonic_ns)}


@dataclass
class SpectrumFrame:
    source_kind: str
    device_id: str
    connection_epoch: int
    session_id: str
    frame_id: int
    config_version: int
    sample_index: int
    service_id: str
    spectrum_kind: str
    fft_size: int
    bin_count: int
    window: str
    scaling: str
    first_bin_hz: float
    bin_width_hz: float
    sample_rate_hz: float
    units: str
    values: bytes
    value_element: str = "float32"
    validity: dict[str, Any] = field(default_factory=dict)
    display_only: bool = False
    algorithm_version: str | None = None

    def __post_init__(self) -> None:
        _require_source_kind(self.source_kind)
        width = {"float32": 4, "float64": 8, "int32": 4, "uint32": 4}.get(self.value_element)
        if width is None:
            raise BackendError("bad_args", {"field": "valueElement"})
        if len(self.values) != self.bin_count * width:
            raise BackendError("bad_args", {"field": "values", "reason": "bin-count-mismatch"})

    def to_dict(self) -> dict[str, Any]:
        return {"sourceKind": self.source_kind, "deviceId": self.device_id,
                "connectionEpoch": u64(self.connection_epoch),
                "sessionId": self.session_id, "frameId": self.frame_id,
                "configVersion": self.config_version,
                "sampleIndex": u64(self.sample_index), "serviceId": self.service_id,
                "spectrumKind": self.spectrum_kind, "fftSize": self.fft_size,
                "binCount": self.bin_count, "window": self.window,
                "scaling": self.scaling,
                "frequencyAxis": {"firstBinHz": self.first_bin_hz,
                                  "binWidthHz": self.bin_width_hz,
                                  "sampleRateHz": self.sample_rate_hz},
                "units": self.units,
                "values": {"handleId": "spectrum", "bytes": len(self.values),
                           "elementType": self.value_element, "count": self.bin_count,
                           "layout": "interleaved", "alignment": 4,
                           "displayOnly": bool(self.display_only),
                           "sourceKind": self.source_kind, "sha256": None},
                "validity": _json(self.validity),
                "displayOnly": bool(self.display_only),
                "algorithmVersion": self.algorithm_version}


@dataclass
class ServiceResult:
    source_kind: str
    device_id: str
    connection_epoch: int
    session_id: str
    service_id: str
    descriptor: int
    slot: int
    session: int
    config: int
    generation: int
    program_version: int
    source_frame: int
    sample_index: int | None
    units: str | None
    words: bytes
    decoded: dict[str, Any] | None = None
    validity: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_source_kind(self.source_kind)
        if len(self.words) % 4:
            raise BackendError("bad_args", {"field": "words", "reason": "not-u32-words"})

    def to_dict(self) -> dict[str, Any]:
        return {"sourceKind": self.source_kind, "deviceId": self.device_id,
                "connectionEpoch": u64(self.connection_epoch),
                "sessionId": self.session_id, "serviceId": self.service_id,
                "descriptor": self.descriptor, "slot": self.slot,
                "session": self.session, "config": self.config,
                "generation": self.generation,
                "programVersion": self.program_version,
                "sourceFrame": self.source_frame,
                "sampleIndex": None if self.sample_index is None else u64(self.sample_index),
                "units": self.units,
                "words": {"handleId": "service", "bytes": len(self.words),
                          "elementType": "uint32", "count": len(self.words) // 4,
                          "layout": "interleaved", "alignment": 4,
                          "displayOnly": False, "sourceKind": self.source_kind,
                          "sha256": None},
                "decoded": _json(self.decoded), "validity": _json(self.validity),
                "provenance": _json(self.provenance)}


@dataclass
class EventRecord:
    event_id: int
    device_id: str
    connection_epoch: int
    session_id: str
    source_kind: str
    captured_first_sample_index: int = 0
    captured_last_sample_index: int = 0
    frames: int = 0
    sample_rate_hz: float = 0.0
    clip_reason: int = 0
    flags: dict[str, bool] = field(default_factory=dict)
    pre_q22: int = 0
    post_q22: int = 0
    delta_q22: int = 0
    summary_age_samples: int = 0
    summary_valid: bool = False
    bank: int = 0
    offset_bytes: int = 0
    file: dict[str, Any] = field(default_factory=lambda: {"state": "missing"})
    ack: dict[str, Any] = field(default_factory=lambda: {"acked": False,
                                                          "duplicate": False})
    manifest_path: str | None = None
    created_monotonic_ns: int = 0
    created_unix_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        _require_source_kind(self.source_kind)
        return {**({"createdUnixMs":u64(self.created_unix_ms)} if self.created_unix_ms is not None else {}), "eventId": u64(self.event_id), "deviceId": self.device_id,
                "connectionEpoch": u64(self.connection_epoch),
                "sessionId": self.session_id, "sourceKind": self.source_kind,
                "capturedFirstSampleIndex": u64(self.captured_first_sample_index),
                "capturedLastSampleIndex": u64(self.captured_last_sample_index),
                "frames": self.frames, "sampleRateHz": self.sample_rate_hz,
                "clipReason": self.clip_reason, "flags": dict(self.flags),
                "preQ22": self.pre_q22, "postQ22": self.post_q22,
                "deltaQ22": self.delta_q22,
                "summaryAgeSamples": self.summary_age_samples,
                "summaryValid": bool(self.summary_valid),
                "bank": self.bank, "offsetBytes": self.offset_bytes,
                "file": _json(self.file), "ack": _json(self.ack),
                "manifestPath": self.manifest_path,
                "createdMonotonicNs": u64(self.created_monotonic_ns)}


@dataclass
class JobState:
    job_id: str
    kind: str
    state: str = "accepted"
    progress: float | None = None
    created_monotonic_ns: int = 0
    updated_monotonic_ns: int = 0
    client_task_key: str | None = None
    request_id: str = ""
    result: dict[str, Any] | None = None
    error: ErrorInfo | None = None
    cancel_requested: bool = False
    cancel_acknowledged: bool = False

    TERMINAL = ("completed", "failed", "canceled")
    STATES = ("accepted", "running", "cancel_requested", "completed", "failed", "canceled")

    def __post_init__(self) -> None:
        if self.state not in self.STATES:
            raise BackendError("bad_args", {"field": "jobState", "value": self.state})

    @property
    def terminal(self) -> bool:
        return self.state in self.TERMINAL

    def to_dict(self) -> dict[str, Any]:
        return {"jobId": self.job_id, "kind": self.kind, "state": self.state,
                "progress": self.progress,
                "createdAtMonotonicNs": u64(self.created_monotonic_ns),
                "updatedAtMonotonicNs": u64(self.updated_monotonic_ns),
                "clientTaskKey": self.client_task_key,
                "requestId": self.request_id, "result": _json(self.result),
                "error": None if self.error is None else self.error.to_dict(),
                "cancelRequested": bool(self.cancel_requested),
                "cancelAcknowledged": bool(self.cancel_acknowledged)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobState":
        error = data.get("error")
        return cls(job_id=str(data.get("jobId", "")),
                   kind=str(data.get("kind", "unknown")),
                   state=str(data.get("state", "accepted")),
                   progress=data.get("progress"),
                   created_monotonic_ns=parse_u64(data.get("createdAtMonotonicNs", "0"),
                                                  "createdAtMonotonicNs"),
                   updated_monotonic_ns=parse_u64(data.get("updatedAtMonotonicNs", "0"),
                                                  "updatedAtMonotonicNs"),
                   client_task_key=data.get("clientTaskKey"),
                   request_id=str(data.get("requestId", "")),
                   result=data.get("result"),
                   error=None if error is None else ErrorInfo.from_error(error),
                   cancel_requested=bool(data.get("cancelRequested", False)),
                   cancel_acknowledged=bool(data.get("cancelAcknowledged", False)))


@dataclass
class RecordingManifest:
    recording_id: str
    device_id: str
    connection_epoch: int
    session_id: str
    source_kind: str
    started_monotonic_ns: int
    stopped_monotonic_ns: int
    real_sample_rate_hz: float
    integer_rate_hz: int
    rate_rounding_error_hz: float
    records: int
    first_sample_index: int
    last_sample_index: int
    segments: list[dict[str, Any]] = field(default_factory=list)
    wav: dict[str, Any] | None = None
    gaps: list[dict[str, Any]] = field(default_factory=list)
    flags: dict[str, bool] = field(default_factory=dict)
    algorithm_versions: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    sha256: str = ""

    FORMAT = "smc-recording-v1"

    def _body(self) -> dict[str, Any]:
        return {"format": self.FORMAT, "recordingId": self.recording_id,
                "deviceId": self.device_id,
                "connectionEpoch": u64(self.connection_epoch),
                "sessionId": self.session_id, "sourceKind": self.source_kind,
                "startedMonotonicNs": u64(self.started_monotonic_ns),
                "stoppedMonotonicNs": u64(self.stopped_monotonic_ns),
                "channels": PCM_CHANNELS, "sampleFormat": PCM_SAMPLE_FORMAT,
                "units": PCM_UNITS,
                "realSampleRateHz": self.real_sample_rate_hz,
                "integerRateHz": self.integer_rate_hz,
                "rateRoundingErrorHz": self.rate_rounding_error_hz,
                "records": u64(self.records),
                "firstSampleIndex": u64(self.first_sample_index),
                "lastSampleIndex": u64(self.last_sample_index),
                "segments": _json(self.segments), "wav": _json(self.wav),
                "gaps": _json(self.gaps), "flags": dict(self.flags),
                "algorithmVersions": _json(self.algorithm_versions),
                "notes": list(self.notes)}

    def compute_sha256(self) -> str:
        import hashlib
        import json
        body = self._body()
        canonical = json.dumps(body, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        _require_source_kind(self.source_kind)
        body = self._body()
        body["sha256"] = self.sha256 or self.compute_sha256()
        return body

    def validate(self) -> None:
        if self.records < 0 or self.last_sample_index < self.first_sample_index and self.records:
            raise BackendError("file_corrupt", {"reason": "manifest-sample-range"})
        expected = self.records
        total = sum(int(segment.get("recordCount", 0)) for segment in self.segments)
        if expected and total != expected:
            raise BackendError("file_corrupt", {"reason": "manifest-segment-count",
                                                "records": expected, "segments": total})
        if self.integer_rate_hz <= 0 or not 0 < self.real_sample_rate_hz < 1e7:
            raise BackendError("file_corrupt", {"reason": "manifest-sample-rate"})
        if self.wav is not None:
            if int(self.wav.get("channelCount", 0)) != PCM_CHANNELS:
                raise BackendError("file_corrupt", {"reason": "manifest-wav-channels"})
            wav_rate = self.wav.get("integerRateHz", self.wav.get("sampleRate"))
            if wav_rate is None or int(wav_rate) != self.integer_rate_hz:
                raise BackendError("file_corrupt", {"reason": "manifest-wav-rate",
                                                    "wavRate": wav_rate,
                                                    "manifestRate": self.integer_rate_hz})
        if self.sha256 and self.sha256 != self.compute_sha256():
            raise BackendError("file_corrupt", {"reason": "manifest-hash"})
