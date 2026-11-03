"""Raw recording/export helpers: six-channel 24-bit WAV and manifest arithmetic.

The real sample rate is a float (e.g. 48009.775390625 Hz). WAV/PCM playback uses
an integer rate; the rounding error is always recorded, never hidden, and no
implicit resampling happens.
"""
from __future__ import annotations

import hashlib
import json
import wave
from pathlib import Path
from typing import Any

from ..constants import CANDIDATE_SAMPLE_RATE_HZ, PCM_CHANNELS, PCM_RECORD_BYTES
from ..errors import BackendError
from ..protocol.pcm import decode_record
from .dto import RecordingManifest


def integer_rate_for(real_rate_hz: float) -> tuple[int, float]:
    integer = int(round(float(real_rate_hz)))
    return integer, integer - float(real_rate_hz)


def write_wav6_24bit(path: str | Path, records: bytes, *, real_sample_rate_hz: float,
                     integer_rate_hz: int | None = None) -> dict[str, Any]:
    """Write six-channel 24-bit PCM WAV from raw 32-byte records."""
    path = Path(path)
    if len(records) % PCM_RECORD_BYTES:
        raise BackendError("bad_args", {"field": "records", "reason": "not-32-byte-records"})
    rate = integer_rate_hz if integer_rate_hz is not None else integer_rate_for(real_sample_rate_hz)[0]
    if rate <= 0:
        raise BackendError("bad_args", {"field": "integerRateHz"})
    frame_count = len(records) // PCM_RECORD_BYTES
    payload = bytearray(frame_count * PCM_CHANNELS * 3)
    position = 0
    for offset in range(0, len(records), PCM_RECORD_BYTES):
        record = decode_record(records[offset:offset + PCM_RECORD_BYTES])
        for value in record.samples:
            pattern = value & 0xFFFFFF
            payload[position] = pattern & 0xFF
            payload[position + 1] = (pattern >> 8) & 0xFF
            payload[position + 2] = (pattern >> 16) & 0xFF
            position += 3
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setparams((PCM_CHANNELS, 3, rate, 0, "NONE", "not compressed"))
        stream.writeframes(bytes(payload))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    integer, error = integer_rate_for(real_sample_rate_hz)
    return {"path": str(path), "sha256": digest, "integerRateHz": rate,
            "realSampleRateHz": float(real_sample_rate_hz),
            "rateRoundingErrorHz": rate - float(real_sample_rate_hz),
            "channelCount": PCM_CHANNELS, "bitsPerSample": 24,
            "frames": frame_count}


def read_24bit_wav(path: str | Path) -> tuple[bytes, dict[str, Any]]:
    """Read a six-channel 24-bit WAV back into raw 32-byte records (test/export)."""
    with wave.open(str(path), "rb") as stream:
        channels = stream.getnchannels()
        width = stream.getsampwidth()
        rate = stream.getframerate()
        if channels != PCM_CHANNELS or width != 3 or stream.getcomptype() != "NONE":
            raise BackendError("file_corrupt", {"reason": "wav-not-6ch-24bit",
                                                "channels": channels, "width": width})
        count = stream.getnframes()
        raw = stream.readframes(count)
    if len(raw) != count * PCM_CHANNELS * 3:
        raise BackendError("file_corrupt", {"reason": "wav-truncated"})
    out = bytearray(count * PCM_RECORD_BYTES)
    for frame in range(count):
        base = frame * 18
        target = frame * PCM_RECORD_BYTES
        for channel in range(PCM_CHANNELS):
            b0, b1, b2 = raw[base + channel * 3: base + channel * 3 + 3]
            pattern = b0 | (b1 << 8) | (b2 << 16)
            out[target + channel * 4] = pattern & 0xFF
            out[target + channel * 4 + 1] = (pattern >> 8) & 0xFF
            out[target + channel * 4 + 2] = (pattern >> 16) & 0xFF
            # re-apply the wire sign extension of bit23 into bits 31:24
            out[target + channel * 4 + 3] = 0xFF if pattern & 0x800000 else 0x00
    return bytes(out), {"sampleRate": rate, "channels": channels,
                        "sampleWidthBits": 24, "frames": count}


def build_recording_manifest(*, recording_id: str, device_id: str, connection_epoch: int,
                             session_id: str, source_kind: str, started_ns: int,
                             stopped_ns: int, real_sample_rate_hz: float,
                             records: int, first_sample_index: int,
                             last_sample_index: int, segments: list[dict[str, Any]],
                             wav: dict[str, Any] | None = None,
                             gaps: list[dict[str, Any]] | None = None,
                             flags: dict[str, bool] | None = None,
                             algorithm_versions: dict[str, Any] | None = None,
                             notes: list[str] | None = None) -> RecordingManifest:
    integer, error = integer_rate_for(real_sample_rate_hz)
    manifest = RecordingManifest(
        recording_id=recording_id, device_id=device_id,
        connection_epoch=connection_epoch, session_id=session_id,
        source_kind=source_kind, started_monotonic_ns=started_ns,
        stopped_monotonic_ns=stopped_ns, real_sample_rate_hz=float(real_sample_rate_hz),
        integer_rate_hz=integer, rate_rounding_error_hz=error,
        records=records, first_sample_index=first_sample_index,
        last_sample_index=last_sample_index, segments=segments, wav=wav,
        gaps=list(gaps or []), flags=dict(flags or {}),
        algorithm_versions=dict(algorithm_versions or {}),
        notes=list(notes or []))
    manifest.sha256 = manifest.compute_sha256()
    manifest.validate()
    return manifest


def write_manifest(path: str | Path, manifest: RecordingManifest) -> dict[str, Any]:
    path = Path(path)
    payload = manifest.to_dict()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "manifestSha256": payload["sha256"]}


def load_manifest(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackendError("file_corrupt", {"reason": "manifest-read",
                                            "path": str(path)}) from exc
    if not isinstance(payload, dict) or payload.get("format") != RecordingManifest.FORMAT:
        raise BackendError("file_corrupt", {"reason": "manifest-format"})
    return payload


def verify_manifest_files(manifest: dict[str, Any]) -> dict[str, Any]:
    """Check recorded segment hashes and record counts against the manifest."""
    results: list[dict[str, Any]] = []
    total_records = 0
    previous_index: int | None = None
    for segment in manifest.get("segments", []):
        path = Path(segment["path"])
        if not path.is_file():
            results.append({"path": str(path), "ok": False, "reason": "missing"})
            continue
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        record_count = len(data) // PCM_RECORD_BYTES
        ok = digest == segment.get("sha256") and record_count == int(segment.get("recordCount", -1))
        first_index = None
        last_index = None
        if record_count:
            first_index = decode_record(data[:PCM_RECORD_BYTES]).sample_index
            last_index = decode_record(data[-PCM_RECORD_BYTES:]).sample_index
        if previous_index is not None and first_index is not None and first_index != previous_index + 1:
            # A discontinuity is only corruption when the manifest does not
            # document it; a recorded gap must verify as healthy.
            documented = any(
                isinstance(gap, dict)
                and str(gap.get("firstMissingSampleIndex")) == str(previous_index + 1)
                and str(gap.get("lastMissingSampleIndex")) == str(first_index - 1)
                for gap in (manifest.get("gaps") or []))
            if not documented:
                ok = False
        previous_index = last_index
        total_records += record_count
        results.append({"path": str(path), "ok": ok, "bytes": len(data),
                        "recordCount": record_count, "sha256": digest,
                        "firstSampleIndex": first_index, "lastSampleIndex": last_index})
    declared = int(manifest.get("records", 0))
    return {"ok": all(item["ok"] for item in results) and total_records == declared,
            "segments": results, "records": total_records, "declaredRecords": declared,
            "firstSampleIndex": manifest.get("firstSampleIndex"),
            "lastSampleIndex": manifest.get("lastSampleIndex")}


def candidate_rate_or(rate: float | None) -> float:
    return float(rate) if rate else CANDIDATE_SAMPLE_RATE_HZ
