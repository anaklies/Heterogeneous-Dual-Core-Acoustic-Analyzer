"""Per-stream schema enforcement, sequence/gap tracking and consumer fan-out."""
from __future__ import annotations

import threading
from typing import Any, Protocol

from ..constants import (
    MSG_EVENT_FILE_CHUNK, MSG_PCM_RECORD32, MSG_RESULT_WORDS32,
    MSG_SERVICE_SNAPSHOT, MSG_STREAM_GAP, MSG_STREAM_SCHEMA,
)
from ..errors import BackendError
from ..protocol.framing import SmaHeader
from ..protocol.messages import (
    parse_service_snapshot, parse_stream_gap, unpack_result_words,
    validate_stream_schema,
)
from ..protocol.pcm import check_contiguous, decode_records


class StreamConsumer(Protocol):
    def on_schema(self, schema: dict[str, Any]) -> None: ...
    def on_payload(self, header: SmaHeader, payload: bytes,
                   schema: dict[str, Any]) -> None: ...


class StreamState:
    def __init__(self, stream_id: int, stream_type: str) -> None:
        self.stream_id = stream_id
        self.stream_type = stream_type
        self.schema: dict[str, Any] | None = None
        self.frames = 0
        self.sequence: int | None = None
        self.sequence_gaps = 0
        self.sample_gaps = 0
        self.unknown_messages = 0
        self.inconsistent_results = 0
        self.dropped_records = 0
        self.gap_events: list[dict[str, Any]] = []
        self.expected_sample_index: int | None = None
        self.last_header: SmaHeader | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"streamId": self.stream_id, "streamType": self.stream_type,
                "schemaPresent": self.schema is not None, "frames": self.frames,
                "sequence": self.sequence, "sequenceGaps": self.sequence_gaps,
                "sampleGaps": self.sample_gaps,
                "droppedRecords": self.dropped_records,
                "inconsistentResults": self.inconsistent_results,
                "unknownMessages": self.unknown_messages,
                "gapEvents": list(self.gap_events[-32:])}


class StreamDispatcher:
    """Thread-safe: called by the binary reader thread only, consumers must not block."""

    def __init__(self, *, allow_sample_streams: bool = True) -> None:
        self._states: dict[int, StreamState] = {}
        self._consumers: dict[int, list[StreamConsumer]] = {}
        self._lock = threading.RLock()
        self.allow_sample_streams = allow_sample_streams
        self.unknown_message_count = 0

    def register(self, stream_id: int, stream_type: str, consumer: StreamConsumer) -> StreamState:
        with self._lock:
            state = self._states.get(stream_id)
            if state is None:
                state = StreamState(stream_id, stream_type)
                self._states[stream_id] = state
            elif state.stream_type != stream_type:
                raise BackendError("schema_mismatch", {"reason": "stream-type-changed",
                                                       "streamId": stream_id})
            self._consumers.setdefault(stream_id, []).append(consumer)
            return state

    def state(self, stream_id: int) -> StreamState | None:
        with self._lock:
            return self._states.get(stream_id)

    def states(self) -> dict[int, StreamState]:
        with self._lock:
            return dict(self._states)

    def handle(self, header: SmaHeader, payload: bytes) -> dict[str, Any]:
        if header.message_type == MSG_STREAM_SCHEMA:
            schema = validate_stream_schema(payload)
            stream_id = int(schema["streamId"])
            if header.stream_id not in (0, stream_id):
                raise BackendError("schema_mismatch", {"reason": "schema-stream-id-mismatch"})
            with self._lock:
                state = self._states.get(stream_id)
                if state is None:
                    state = StreamState(stream_id, str(schema["streamType"]))
                    self._states[stream_id] = state
                if state.stream_type != schema["streamType"]:
                    raise BackendError("schema_mismatch", {"reason": "schema-type-changed"})
                state.schema = schema
                consumers = list(self._consumers.get(stream_id, ()))
            for consumer in consumers:
                consumer.on_schema(schema)
            return {"event": "schema", "streamId": stream_id, "schema": schema}

        if header.message_type == MSG_STREAM_GAP:
            gap = parse_stream_gap(payload)
            stream_id = int(gap.get("streamId", header.stream_id))
            with self._lock:
                state = self._states.get(stream_id)
                if state is None:
                    state = StreamState(stream_id, "unknown")
                    self._states[stream_id] = state
                state.gap_events.append(gap)
                state.dropped_records += int(gap.get("droppedRecords", "0"))
            return {"event": "gap", "streamId": stream_id, "gap": gap}

        if header.message_type not in (MSG_PCM_RECORD32, MSG_RESULT_WORDS32,
                                       MSG_SERVICE_SNAPSHOT, MSG_EVENT_FILE_CHUNK):
            self.unknown_message_count += 1
            return {"event": "unknown", "messageType": header.message_type}

        with self._lock:
            state = self._states.get(header.stream_id)
            if state is None:
                raise BackendError("schema_mismatch",
                                   {"reason": "data-before-schema",
                                    "streamId": header.stream_id})
            if state.schema is None:
                raise BackendError("schema_mismatch",
                                   {"reason": "data-before-schema",
                                    "streamId": header.stream_id})
            if state.sequence is not None:
                expected = (state.sequence + 1) & 0xFFFFFFFF
                if header.sequence != expected:
                    state.sequence_gaps += 1
            state.sequence = header.sequence
            state.frames += 1
            state.last_header = header
            consumers = list(self._consumers.get(header.stream_id, ()))
            schema = state.schema

        detail: dict[str, Any] = {"event": "payload", "streamId": header.stream_id,
                                  "messageType": header.message_type}
        if header.message_type == MSG_PCM_RECORD32:
            records = decode_records(payload)
            problems = check_contiguous(records)
            expected = state.expected_sample_index
            if expected is not None and records[0].sample_index != expected:
                state.sample_gaps += 1
            if problems:
                raise BackendError("schema_mismatch",
                                   {"reason": "pcm-sample-index-discontinuity",
                                    "discontinuities": problems[:4]})
            state.expected_sample_index = records[-1].sample_index + 1
            detail.update({"records": len(records),
                           "firstSampleIndex": records[0].sample_index,
                           "lastSampleIndex": records[-1].sample_index})
        elif header.message_type == MSG_RESULT_WORDS32:
            words = unpack_result_words(payload)
            if header.frame_id and header.frame_id != words[2]:
                state.inconsistent_results += 1
                raise BackendError("schema_mismatch",
                                   {"reason": "result-frame-header-mismatch",
                                    "headerFrame": header.frame_id, "wordFrame": words[2]})
            if header.config_version and header.config_version != words[3]:
                state.inconsistent_results += 1
                raise BackendError("schema_mismatch",
                                   {"reason": "result-config-header-mismatch"})
            detail.update({"words": words, "frameId": words[2],
                           "configVersion": words[3]})
        elif header.message_type == MSG_SERVICE_SNAPSHOT:
            service_header, body = parse_service_snapshot(payload)
            if not service_header.usable():
                raise BackendError("bad_state", {"reason": "service-header-not-usable",
                                                "magic": service_header.magic,
                                                "done": service_header.done,
                                                "error": service_header.error})
            detail.update({"serviceHeader": service_header, "body": body})
        for consumer in consumers:
            consumer.on_payload(header, payload, schema)
        return detail
