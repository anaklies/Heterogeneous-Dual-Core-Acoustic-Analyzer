"""Segmented raw PCM recording -> WAV + explicit-gap manifest.

Continuity is confirmed per record. Gaps are recorded, never silently spliced.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import wave
from pathlib import Path
from typing import Any

from ..constants import PCM_RECORD_BYTES, SOURCE_KINDS
from ..errors import BackendError
from ..model.audio import (
    build_recording_manifest, integer_rate_for, verify_manifest_files, write_manifest,
)
from ..protocol.pcm import decode_record

RECORDING_FORMAT = "smc-recording-v1"
DEFAULT_SEGMENT_BYTES = 64 * 1024 * 1024


def _now_ns() -> int:
    return time.monotonic_ns()


class Recorder:
    def __init__(self, directory: str | Path, *, recording_id: str, device_id: str,
                 connection_epoch: int, session_id: str, source_kind: str,
                 real_sample_rate_hz: float, max_segment_bytes: int = DEFAULT_SEGMENT_BYTES,
                 max_total_bytes: int | None = None) -> None:
        if source_kind not in SOURCE_KINDS:
            raise BackendError("bad_args", {"field": "sourceKind"})
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.recording_id = recording_id
        self.device_id = device_id
        self.connection_epoch = connection_epoch
        self.session_id = session_id
        self.source_kind = source_kind
        self.real_sample_rate_hz = float(real_sample_rate_hz)
        self.max_segment_bytes = max(PCM_RECORD_BYTES * 256, int(max_segment_bytes))
        self.max_total_bytes = max_total_bytes
        self.state = "idle"
        self.started_ns = 0
        self.stopped_ns = 0
        self.records = 0
        self.bytes = 0
        self.segments: list[dict[str, Any]] = []
        self.gaps: list[dict[str, Any]] = []
        self.expected_sample_index: int | None = None
        self.first_sample_index: int | None = None
        self.last_sample_index: int | None = None
        self.flags: dict[str, bool] = {}
        self.notes: list[str] = []
        self._writer: Any = None
        self._hash: Any = None
        self._segment_index = 0
        self._segment_bytes = 0
        self._segment_first: int | None = None
        self._segment_last: int | None = None
        self._segment_records = 0
        self.error: BackendError | None = None
        self._lock = threading.RLock()

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> dict[str, Any]:
        with self._lock:
            if self.state != "idle":
                raise BackendError("recording_active", {"state": self.state})
            self.state = "recording"
            self.started_ns = _now_ns()
            self._open_segment()
            return self.status()

    def append_audio(self, records: bytes, *, first_sample_index: int | None = None,
                     gap_before: bool = False,
                     gap_reason: str = "recording_discontinuity") -> dict[str, Any]:
        with self._lock:
            return self._append_audio_locked(records, first_sample_index=first_sample_index,
                                             gap_before=gap_before, gap_reason=gap_reason)

    def _append_audio_locked(self, records: bytes, *,
                             first_sample_index: int | None,
                             gap_before: bool, gap_reason: str) -> dict[str, Any]:
        if self.state != "recording":
            raise BackendError("recording_active", {"state": self.state})
        if not records or len(records) % PCM_RECORD_BYTES:
            raise BackendError("bad_args", {"field": "records", "reason": "not-32-byte-records"})
        count = len(records) // PCM_RECORD_BYTES
        first = (decode_record(records[:PCM_RECORD_BYTES]).sample_index
                 if first_sample_index is None else int(first_sample_index))
        last = decode_record(records[-PCM_RECORD_BYTES:]).sample_index
        if last - first + 1 != count:
            raise BackendError("schema_mismatch", {"reason": "record-span-mismatch"})
        if self.expected_sample_index is not None and first != self.expected_sample_index:
            already = any(
                str(gap.get("firstMissingSampleIndex")) == str(self.expected_sample_index)
                and str(gap.get("lastMissingSampleIndex")) == str(first - 1)
                for gap in self.gaps)
            if not already:
                self.gaps.append({
                    "reason": gap_reason,
                    "firstMissingSampleIndex": str(self.expected_sample_index),
                    "lastMissingSampleIndex": str(first - 1),
                    "droppedRecords": str(max(0, first - self.expected_sample_index))})
        if self.first_sample_index is None:
            self.first_sample_index = first
        try:
            self._open_segment()
            self._write(records)
        except OSError as exc:
            self.error = BackendError("storage_full", {"reason": "disk", "detail": str(exc)})
            self.state = "failed"
            raise self.error from exc
        self.expected_sample_index = last + 1
        self.last_sample_index = last
        self.records += count
        self.bytes += len(records)
        if self.max_total_bytes is not None and self.bytes > self.max_total_bytes:
            self.notes.append("recording exceeded configured maxBytes; stopped")
            self.stop()
        return {"records": count, "firstSampleIndex": str(first),
                "lastSampleIndex": str(last)}

    def append_gap(self, gap: dict[str, Any]) -> None:
        self.gaps.append(dict(gap))

    def stop(self) -> dict[str, Any]:
        with self._lock:
            return self._stop_locked()

    def _stop_locked(self) -> dict[str, Any]:
        if self.state == "stopped":
            return self.status()
        if self.state == "idle":
            raise BackendError("recording_active", {"state": "idle"})
        self._close_segment()
        self.stopped_ns = _now_ns()
        self.state = "stopped" if self.state == "recording" else self.state
        manifest = build_recording_manifest(
            recording_id=self.recording_id, device_id=self.device_id,
            connection_epoch=self.connection_epoch, session_id=self.session_id,
            source_kind=self.source_kind, started_ns=self.started_ns,
            stopped_ns=self.stopped_ns, real_sample_rate_hz=self.real_sample_rate_hz,
            records=self.records, first_sample_index=self.first_sample_index or 0,
            last_sample_index=self.last_sample_index or 0,
            segments=list(self.segments), gaps=list(self.gaps), flags=dict(self.flags),
            algorithm_versions={"resultProtocol": 3, "servicePrograms": {}},
            notes=list(self.notes))
        wav_info = self._export_wav()
        manifest.wav = wav_info
        manifest.sha256 = manifest.compute_sha256()
        manifest.validate()
        self.manifest = manifest
        self.manifest_path = write_manifest(self.directory / "manifest.json", manifest)
        self.verification = verify_manifest_files(manifest.to_dict())
        return self.status()

    # -- internals ---------------------------------------------------------
    def _open_segment(self) -> None:
        if self._writer is not None and self._segment_bytes < self.max_segment_bytes:
            return
        self._close_segment()
        path = self.directory / f"segment-{self._segment_index:04d}.rec32"
        self._writer = path.open("wb")
        self._hash = hashlib.sha256()
        self._segment_index += 1
        self._segment_bytes = 0
        self._segment_first = None
        self._segment_last = None
        self._segment_records = 0
        self._current_path = path

    def _write(self, records: bytes) -> None:
        assert self._writer is not None
        self._writer.write(records)
        self._hash.update(records)
        if self._segment_first is None:
            self._segment_first = decode_record(records[:PCM_RECORD_BYTES]).sample_index
        self._segment_last = decode_record(records[-PCM_RECORD_BYTES:]).sample_index
        self._segment_bytes += len(records)
        self._segment_records += len(records) // PCM_RECORD_BYTES
        if self._segment_bytes >= self.max_segment_bytes:
            self._close_segment()

    def _close_segment(self) -> None:
        if self._writer is None:
            return
        self._writer.flush()
        os.fsync(self._writer.fileno())
        self._writer.close()
        self.segments.append({"path": str(self._current_path),
                              "bytes": self._segment_bytes,
                              "sha256": self._hash.hexdigest(),
                              "firstRecord": self._segment_first,
                              "lastRecord": self._segment_last,
                              "recordCount": self._segment_records})
        self._writer = None
        self._hash = None

    def _export_wav(self) -> dict[str, Any] | None:
        if not self.segments:
            return None
        integer, error = integer_rate_for(self.real_sample_rate_hz)
        path = self.directory / "audio-6ch-24bit.wav"
        total_written = 0
        with wave.open(str(path), "wb") as stream:
            stream.setparams((6, 3, integer, 0, "NONE", "not compressed"))
            for segment in self.segments:
                data = Path(segment["path"]).read_bytes()
                payload = bytearray((len(data) // PCM_RECORD_BYTES) * 18)
                position = 0
                for offset in range(0, len(data), PCM_RECORD_BYTES):
                    record = decode_record(data[offset:offset + PCM_RECORD_BYTES])
                    for value in record.samples:
                        pattern = value & 0xFFFFFF
                        payload[position] = pattern & 0xFF
                        payload[position + 1] = (pattern >> 8) & 0xFF
                        payload[position + 2] = (pattern >> 16) & 0xFF
                        position += 3
                stream.writeframes(bytes(payload))
                total_written += len(payload) // 18
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return {"path": str(path), "sha256": digest, "integerRateHz": integer,
                "realSampleRateHz": self.real_sample_rate_hz,
                "rateRoundingErrorHz": error, "channelCount": 6,
                "bitsPerSample": 24, "frames": total_written,
                "note": "capture-order concatenation; gaps listed in manifest.gaps, never resampled"}

    # -- status ------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        return {"recordingId": self.recording_id, "state": self.state,
                "records": self.records, "bytes": self.bytes,
                "gaps": len(self.gaps), "segments": len(self.segments),
                "sourceKind": self.source_kind,
                "realSampleRateHz": self.real_sample_rate_hz,
                "startedMonotonicNs": str(self.started_ns),
                "firstSampleIndex": None if self.first_sample_index is None
                else str(self.first_sample_index),
                "lastSampleIndex": None if self.last_sample_index is None
                else str(self.last_sample_index),
                "error": None if self.error is None else self.error.to_dict()}


def load_recording(directory: str | Path) -> dict[str, Any]:
    directory = Path(directory)
    manifest_path = directory / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackendError("file_corrupt", {"reason": "recording-manifest",
                                            "path": str(manifest_path)}) from exc
    if manifest.get("format") != RECORDING_FORMAT:
        raise BackendError("file_corrupt", {"reason": "recording-format"})
    verification = verify_manifest_files(manifest)
    return {"manifest": manifest, "verification": verification,
            "directory": str(directory)}
