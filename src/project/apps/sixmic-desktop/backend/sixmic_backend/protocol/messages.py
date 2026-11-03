"""Binary payload codecs: result words, service snapshot header, schemas, gaps."""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from typing import Any

from ..constants import (
    CANDIDATE_SAMPLE_RATE_HZ, FLAG_DEVICE_MONOTONIC_VALID, FLAG_GAP_BEFORE,
    FLAG_LAST_CHUNK, FLAG_SAMPLE_INDEX_VALID, SERVICE_HEADER_BYTES,
    SERVICE_HEADER_MAGIC, SERVICE_HEADER_WORDS, SOURCE_KINDS, SOURCE_PL_LIVE,
    RESULT_PAYLOAD_BYTES, RESULT_WORD_COUNT,
)
from ..errors import BackendError
from .control import parse_u64, u64

RESULT_WORD_NAMES: tuple[tuple[str, str, str], ...] = (
    ("protocol", "protocol", "uint32"),
    ("algorithm", "algorithm id", "uint32"),
    ("frame", "frame", "uint32"),
    ("config", "config version", "uint32"),
    ("session", "session", "uint32"),
    ("slot", "slot", "uint32"),
    ("fftBase", "word index", "uint32"),
    ("cycles", "cycles", "uint32"),
    ("sampleIndexLow", "sample index low", "uint32"),
    ("sampleIndexHigh", "sample index high", "uint32"),
    ("faults", "fault bits", "uint32"),
    ("micStatus", "status bits", "uint32"),
    ("missedWindows", "count", "uint32"),
    ("droppedSamples", "count", "uint32"),
    ("backgroundDone", "count", "uint32"),
    ("overwritten", "count", "uint32"),
    ("failedFrames", "count", "uint32"),
    ("temperatureCenti", "degC x 100 signed", "int32"),
    ("humidityRaw", "SHT raw code (not percent)", "uint32"),
    ("pressurePa", "Pa", "uint32"),
    ("soundSpeedFloat", "m/s", "float32"),
    ("sensorValid", "valid bits", "uint32"),
    ("rollPitch", "raw int16 pair", "uint32"),
    ("yaw", "raw int16", "uint32"),
    ("qxQw", "raw int16 pair", "uint32"),
    ("qzQy", "raw int16 pair", "uint32"),
    ("envSequence", "count", "uint32"),
    ("poseSequence", "count", "uint32"),
    ("sensorErrors", "raw fields", "uint32"),
    ("lostEvents", "count", "uint32"),
    ("handoffDrops", "count", "uint32"),
    ("sampleRateFloat", "Hz", "float32"),
)

STREAM_GAP_REASONS = frozenset({
    "queue_overflow", "network_drop", "spool_full", "spool_lost",
    "recording_discontinuity", "pl_dropped", "epoch_change", "unknown",
})


def _float32(bits: int) -> float:
    return struct.unpack("<f", struct.pack("<I", bits & 0xFFFFFFFF))[0]


def _signed16(low: int) -> int:
    value = low & 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def unpack_result_words(payload: bytes) -> tuple[int, ...]:
    if len(payload) != RESULT_PAYLOAD_BYTES:
        raise BackendError("bad_args", {"field": "resultPayload", "bytes": len(payload),
                                        "expected": RESULT_PAYLOAD_BYTES})
    words = struct.unpack("<32I", payload)
    if words[0] != 3:
        raise BackendError("protocol_mismatch", {"reason": "result-word-protocol",
                                                "word0": words[0]})
    return words


def decode_result_words(words: tuple[int, ...]) -> dict[str, Any]:
    if len(words) != RESULT_WORD_COUNT:
        raise BackendError("bad_args", {"field": "words", "count": len(words)})
    temperature_raw = struct.unpack("<i", struct.pack("<I", words[17]))[0]
    sensor_valid = words[21]
    faults = words[10]
    humidity_raw = words[18]
    return {
        "protocol": words[0],
        "algorithmId": words[1],
        "frameId": words[2],
        "configVersion": words[3],
        "session": words[4],
        "slot": words[5],
        "fftBase": words[6],
        "cycles": words[7],
        "sampleIndex": (words[9] << 32) | words[8],
        "faults": faults,
        "micStatus": words[11],
        "missedWindows": words[12],
        "droppedSamples": words[13],
        "backgroundDone": words[14],
        "overwritten": words[15],
        "failedFrames": words[16],
        "temperatureCenti": temperature_raw,
        "temperatureC": temperature_raw / 100.0 if (sensor_valid & 0x1) else None,
        "humidityRaw": humidity_raw if humidity_raw else None,
        "pressurePa": words[19] if (sensor_valid & 0x2) and words[19] else None,
        "soundSpeedMps": _float32(words[20]) if (sensor_valid & 0x8) else None,
        "sensorValidBits": sensor_valid,
        "valid": {
            "temperature": bool(sensor_valid & 0x1),
            "pressure": bool(sensor_valid & 0x2),
            "pose": bool(sensor_valid & 0x4),
            "soundSpeedModel": bool(sensor_valid & 0x8),
        },
        "environmentMode": (sensor_valid >> 4) & 0x3,
        "poseRaw": {
            "roll": _signed16(words[22] & 0xFFFF),
            "pitch": _signed16((words[22] >> 16) & 0xFFFF),
            "yaw": _signed16(words[23] & 0xFFFF),
            "qw": _signed16(words[24] & 0xFFFF),
            "qx": _signed16((words[24] >> 16) & 0xFFFF),
            "qy": _signed16(words[25] & 0xFFFF),
            "qz": _signed16((words[25] >> 16) & 0xFFFF),
            "imuScaleStatus": "unverified",
        },
        "envSequence": words[26],
        "poseSequence": words[27],
        "sensorErrorCount": words[28] & 0xFFFF,
        "sensorFaults": (words[28] >> 16) & 0xFF,
        "lostEvents": words[29],
        "handoffDrops": words[30],
        "sampleRateHz": _float32(words[31]),
        "faultDecoded": {
            "bits": faults,
            "pipelineDetailLow": faults & 0x000FFFFF,
            "recorder": bool(faults & (1 << 20)),
            "lostEvent": bool(faults & (1 << 21)),
            "handoffDrop": bool(faults & (1 << 22)),
            "sensorAggregate": bool(faults & (1 << 23)),
            "configRejected": bool(faults & (1 << 30)),
            "epochOverflow": bool(faults & (1 << 31)),
        },
    }


def build_result_schema(*, source_kind: str, device_id: str, connection_epoch: int,
                        simulated: bool, sample_rate_hz: float) -> dict[str, Any]:
    if source_kind not in SOURCE_KINDS:
        raise BackendError("bad_args", {"field": "sourceKind"})
    word_map = [{"index": index, "name": name, "unit": unit, "encoding": encoding}
                for index, (name, unit, encoding) in enumerate(RESULT_WORD_NAMES)]
    return {
        "streamId": 0, "streamType": "resultWords32", "sourceKind": source_kind,
        "deviceId": device_id, "connectionEpoch": u64(connection_epoch),
        "encoding": "sma1", "simulated": bool(simulated),
        "units": "raw protocol-3 result words; decoded units per wordMap",
        "resultSchema": "protocol3-result-v1",
        "wordCount": RESULT_WORD_COUNT, "wordEncoding": "uint32-le",
        "snapshotConsistency": "device epoch compared before/after 32-word copy; each frame is one complete snapshot",
        "wordMap": word_map,
        "validity": {
            "deviceTime": "flag", "sampleIndex": "words 8/9",
            "faultBits": 10, "sensorValidBits": 21,
            "humidityNote": "word18 is a raw SHT code, not a percentage",
            "imuNote": "word22-25 are raw int16 codes; scale/orientation unverified",
        },
    }


def build_pcm_schema(*, stream_id: int, device_id: str, connection_epoch: int,
                     source_kind: str, simulated: bool, sample_rate_hz: float,
                     frame_group_records: int | None = None) -> dict[str, Any]:
    if source_kind not in SOURCE_KINDS:
        raise BackendError("bad_args", {"field": "sourceKind"})
    if source_kind == SOURCE_PL_LIVE and simulated:
        raise BackendError("bad_state", {"reason": "simulated-data-cannot-claim-pl-live"})
    record_rate = sample_rate_hz / 6.0
    return {
        "streamId": stream_id, "streamType": "pcmRecord32", "sourceKind": source_kind,
        "deviceId": device_id, "connectionEpoch": u64(connection_epoch),
        "encoding": "sma1", "simulated": bool(simulated),
        "units": "digital full scale (24-bit PCM codes)",
        "createdMonotonicNs": "0",
        "pcm": {
            "channels": 6, "channelOrder": ["mic1", "mic2", "mic3", "mic4", "mic5", "mic6"],
            "sampleFormat": "int24-le-signextended-in-int32", "recordBytes": 32,
            "sampleIndexOffset": 24, "sampleIndexEncoding": "uint64-le-low-word-first",
            "sampleRateHz": float(sample_rate_hz),
            "sampleRateSource": "pl-result-word31-float32",
            "recordRateHz": record_rate,
            "frameGroupRecords": int(frame_group_records) if frame_group_records else None,
            "gapPolicy": "explicit STREAM_GAP; never silently splice",
        },
        "validity": {"deviceTime": "optional", "sampleIndex": "required", "gapBefore": "flag"},
    }


def build_service_schema(*, stream_id: int, device_id: str, connection_epoch: int,
                         source_kind: str, simulated: bool, service_id: str,
                         descriptor: int, session: int, config: int, generation: int,
                         payload_words: int) -> dict[str, Any]:
    if source_kind not in SOURCE_KINDS:
        raise BackendError("bad_args", {"field": "sourceKind"})
    header_map = [
        {"index": 0, "name": "magic", "encoding": "uint32"},
        {"index": 1, "name": "commitSequence", "encoding": "uint32"},
        {"index": 2, "name": "session", "encoding": "uint32"},
        {"index": 3, "name": "config", "encoding": "uint32"},
        {"index": 4, "name": "generation", "encoding": "uint32"},
        {"index": 5, "name": "programVersion", "encoding": "uint32"},
        {"index": 6, "name": "sourceFrame", "encoding": "uint32"},
        {"index": 7, "name": "sampleIndexLow", "encoding": "uint32"},
        {"index": 8, "name": "sampleIndexHigh", "encoding": "uint32"},
        {"index": 9, "name": "slot", "encoding": "uint32"},
        {"index": 10, "name": "length", "encoding": "uint32"},
        {"index": 11, "name": "descriptor", "encoding": "uint32"},
        {"index": 12, "name": "error", "encoding": "uint32"},
        {"index": 13, "name": "pc", "encoding": "uint32"},
        {"index": 14, "name": "done", "encoding": "uint32"},
        {"index": 15, "name": "reserved", "encoding": "uint32"},
    ]
    return {
        "streamId": stream_id, "streamType": "serviceSnapshot", "sourceKind": source_kind,
        "deviceId": device_id, "connectionEpoch": u64(connection_epoch),
        "encoding": "sma1", "simulated": bool(simulated),
        "serviceId": service_id, "descriptor": int(descriptor),
        "session": int(session), "config": int(config), "generation": int(generation),
        "headerWords": SERVICE_HEADER_WORDS, "headerMap": header_map,
        "payloadWords": int(payload_words),
        "validity": {"headerConsistency": "copy 16-word header before and after payload; full compare",
                     "useOnlyWhen": "magic valid, done==1, error==0, session/config/generation match"},
    }


def build_event_schema(*, stream_id: int, device_id: str, connection_epoch: int,
                       source_kind: str, simulated: bool, event_id: int,
                       total_bytes: int, sha256: str, chunk_bytes: int) -> dict[str, Any]:
    if source_kind not in SOURCE_KINDS:
        raise BackendError("bad_args", {"field": "sourceKind"})
    return {
        "streamId": stream_id, "streamType": "eventFile", "sourceKind": source_kind,
        "deviceId": device_id, "connectionEpoch": u64(connection_epoch),
        "encoding": "sma1", "simulated": bool(simulated),
        "eventId": u64(event_id), "totalBytes": u64(total_bytes),
        "sha256": sha256, "chunkBytes": int(chunk_bytes),
        "container": "SMC1 v1: 64-byte header + 32-byte raw PCM records",
        "validity": {"chunkOrder": "FIRST_CHUNK then monotonic sequence then LAST_CHUNK",
                     "hash": "sha256 over the whole container"},
    }


def validate_stream_schema(payload: bytes, *, require_source_kind: bool = True) -> dict[str, Any]:
    try:
        schema = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise BackendError("schema_mismatch", {"reason": "schema-not-json"}) from exc
    if not isinstance(schema, dict):
        raise BackendError("schema_mismatch", {"reason": "schema-not-object"})
    required = ("streamId", "streamType", "sourceKind", "deviceId", "encoding")
    for key in required:
        if key not in schema:
            raise BackendError("schema_mismatch", {"reason": "schema-missing-field", "field": key})
    if require_source_kind and schema["sourceKind"] not in SOURCE_KINDS:
        raise BackendError("schema_mismatch", {"reason": "schema-source-kind",
                                                "sourceKind": schema["sourceKind"]})
    if schema.get("simulated") and schema["sourceKind"] == SOURCE_PL_LIVE:
        raise BackendError("schema_mismatch",
                           {"reason": "simulated-data-claimed-as-pl-live"})
    stream_type = schema["streamType"]
    if stream_type == "pcmRecord32":
        pcm = schema.get("pcm")
        if not isinstance(pcm, dict) or pcm.get("recordBytes") != 32 or pcm.get("channels") != 6:
            raise BackendError("schema_mismatch", {"reason": "pcm-schema-fields"})
        rate = pcm.get("sampleRateHz")
        if not isinstance(rate, (int, float)) or not 0 < rate < 400000:
            raise BackendError("schema_mismatch", {"reason": "pcm-sample-rate"})
    elif stream_type == "resultWords32":
        if schema.get("wordCount") != RESULT_WORD_COUNT or not isinstance(schema.get("wordMap"), list):
            raise BackendError("schema_mismatch", {"reason": "result-words-schema"})
    elif stream_type == "serviceSnapshot":
        if schema.get("headerWords") != SERVICE_HEADER_WORDS:
            raise BackendError("schema_mismatch", {"reason": "service-header-schema"})
    elif stream_type == "eventFile":
        for key in ("eventId", "totalBytes", "sha256", "chunkBytes"):
            if key not in schema:
                raise BackendError("schema_mismatch",
                                   {"reason": "event-schema-missing", "field": key})
        parse_u64(schema["eventId"], "eventId")
    else:
        raise BackendError("schema_mismatch", {"reason": "unknown-stream-type",
                                                "streamType": stream_type})
    return schema


def build_hello_payload(*, connection_epoch: int, token: str, max_payload_bytes: int) -> dict[str, Any]:
    return {"protocol": "sixmic-analysis", "version": 1,
            "connectionEpoch": u64(connection_epoch), "token": token,
            "maxPayloadBytes": int(max_payload_bytes)}


def parse_hello_response(payload: bytes) -> dict[str, Any]:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise BackendError("schema_mismatch", {"reason": "hello-response-not-json"}) from exc
    if not isinstance(data, dict):
        raise BackendError("schema_mismatch", {"reason": "hello-response-not-object"})
    for field in ("protocol", "protocolVersion", "connectionEpoch", "sessionId"):
        if field not in data:
            raise BackendError("schema_mismatch", {"reason": "hello-missing-field", "field": field})
    parse_u64(data["connectionEpoch"], "connectionEpoch")
    return data


def parse_hello_ack(payload: bytes) -> dict[str, Any]:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise BackendError("schema_mismatch", {"reason": "hello-ack-not-json"}) from exc
    if not isinstance(data, dict) or "accepted" not in data:
        raise BackendError("schema_mismatch", {"reason": "hello-ack-fields"})
    if not data["accepted"]:
        raise BackendError("bad_state", {"reason": "binary-hello-rejected",
                                         "detail": data.get("reason")})
    parse_u64(data["connectionEpoch"], "connectionEpoch")
    return data


def build_stream_gap(*, stream_id: int, reason: str, dropped_records: int,
                     first_missing: int | None, last_missing: int | None,
                     detected_device_ns: int | None, source_kind: str) -> dict[str, Any]:
    if reason not in STREAM_GAP_REASONS:
        raise BackendError("bad_args", {"field": "reason", "value": reason})
    return {"streamId": int(stream_id), "reason": reason,
            "droppedRecords": u64(dropped_records),
            "firstMissingSampleIndex": None if first_missing is None else u64(first_missing),
            "lastMissingSampleIndex": None if last_missing is None else u64(last_missing),
            "detectedDeviceMonotonicNs": None if detected_device_ns is None else u64(detected_device_ns),
            "sourceKind": source_kind}


def parse_stream_gap(payload: bytes) -> dict[str, Any]:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise BackendError("schema_mismatch", {"reason": "stream-gap-not-json"}) from exc
    if not isinstance(data, dict) or data.get("reason") not in STREAM_GAP_REASONS:
        raise BackendError("schema_mismatch", {"reason": "stream-gap-reason"})
    return data


def payload_flags(*, sample_index_valid: bool = False, device_monotonic_valid: bool = False,
                  gap_before: bool = False, first_chunk: bool = False,
                  last_chunk: bool = False) -> int:
    flags = 0
    if sample_index_valid:
        flags |= FLAG_SAMPLE_INDEX_VALID
    if device_monotonic_valid:
        flags |= FLAG_DEVICE_MONOTONIC_VALID
    if gap_before:
        flags |= FLAG_GAP_BEFORE
    if first_chunk:
        flags |= FLAG_FIRST_CHUNK
    if last_chunk:
        flags |= FLAG_LAST_CHUNK
    return flags


@dataclass(frozen=True)
class ServiceHeader:
    magic: int = SERVICE_HEADER_MAGIC
    commit_sequence: int = 0
    session: int = 0
    config: int = 0
    generation: int = 0
    program_version: int = 0
    source_frame: int = 0
    sample_index_low: int = 0
    sample_index_high: int = 0
    slot: int = 0
    length: int = 0
    descriptor: int = 0
    error: int = 0
    pc: int = 0
    done: int = 0
    reserved: int = 0

    @classmethod
    def from_words(cls, words: tuple[int, ...]) -> "ServiceHeader":
        if len(words) != SERVICE_HEADER_WORDS:
            raise BackendError("bad_args", {"field": "serviceHeaderWords"})
        return cls(*words)

    def to_words(self) -> tuple[int, ...]:
        return (self.magic, self.commit_sequence, self.session, self.config,
                self.generation, self.program_version, self.source_frame,
                self.sample_index_low, self.sample_index_high, self.slot,
                self.length, self.descriptor, self.error, self.pc, self.done,
                self.reserved)

    @property
    def sample_index(self) -> int:
        return (self.sample_index_high << 32) | self.sample_index_low

    def usable(self, *, session: int | None = None, config: int | None = None,
               generation: int | None = None) -> bool:
        if self.magic != SERVICE_HEADER_MAGIC:
            return False
        if self.done != 1 or self.error != 0:
            return False
        if session is not None and self.session != session:
            return False
        if config is not None and self.config != config:
            return False
        if generation is not None and self.generation != generation:
            return False
        return True

    def consistent_with(self, other: "ServiceHeader") -> bool:
        return self.to_words() == other.to_words()


def parse_service_snapshot(payload: bytes) -> tuple[ServiceHeader, bytes]:
    if len(payload) < SERVICE_HEADER_BYTES:
        raise BackendError("bad_args", {"field": "servicePayloadBytes", "bytes": len(payload)})
    header_words = struct.unpack_from("<16I", payload, 0)
    header = ServiceHeader.from_words(header_words)
    body = payload[SERVICE_HEADER_BYTES:]
    if len(body) % 4:
        raise BackendError("bad_args", {"field": "serviceBodyWords"})
    word_count = len(body) // 4
    if header.length > word_count:
        raise BackendError("schema_mismatch", {"reason": "service-length-exceeds-payload",
                                               "length": header.length,
                                               "words": word_count})
    return header, payload[SERVICE_HEADER_BYTES:SERVICE_HEADER_BYTES + header.length * 4]


def encode_service_snapshot(header: ServiceHeader, body: bytes) -> bytes:
    if len(body) % 4:
        raise BackendError("bad_args", {"field": "serviceBody"})
    return struct.pack("<16I", *header.to_words()) + body


def default_sample_rate() -> float:
    return CANDIDATE_SAMPLE_RATE_HZ
