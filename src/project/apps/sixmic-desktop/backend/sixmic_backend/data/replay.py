"""File replay from real recordings, producing the same DTOs as live data."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..constants import PCM_RECORD_BYTES, SOURCE_FILE_REPLAY
from ..errors import BackendError
from ..model.audio import load_manifest
from ..model.dto import AudioChunk
from ..protocol.pcm import decode_record


class ReplaySession:
    def __init__(self, manifest_path: str | Path, *, verify: bool = True) -> None:
        self.manifest_path = Path(manifest_path)
        self.manifest = load_manifest(self.manifest_path)
        if verify:
            self._verify_files()
        self.segments = [dict(segment) for segment in self.manifest.get("segments", [])]
        self.real_rate = float(self.manifest["realSampleRateHz"])
        self.state = "stopped"
        self._position = 0
        self._segment_cursor = 0
        self._record_cursor = 0
        self._started_monotonic_ns = 0
        self._played_records = 0
        self._gap_map = self._build_gap_map()

    def _verify_files(self) -> None:
        from ..model.audio import verify_manifest_files
        verification = verify_manifest_files(self.manifest)
        if not verification["ok"]:
            raise BackendError("file_corrupt", {"reason": "replay-verification",
                                                "detail": verification["segments"][:3]})

    def _build_gap_map(self) -> dict[int, dict[str, Any]]:
        """Map the first sample index that follows each known gap -> gap record."""
        gaps: dict[int, dict[str, Any]] = {}
        for gap in self.manifest.get("gaps", []):
            try:
                last_missing = gap.get("lastMissingSampleIndex")
                first_missing = gap.get("firstMissingSampleIndex")
                if last_missing is None and first_missing is None:
                    continue
                end = int(last_missing) if last_missing is not None else int(first_missing) - 1
            except (TypeError, ValueError):
                continue
            gaps[end + 1] = dict(gap)
        return gaps

    # -- state -------------------------------------------------------------
    def set_state(self, state: str) -> dict[str, Any]:
        if state not in ("playing", "paused", "stopped"):
            raise BackendError("bad_args", {"field": "state"})
        if state == "playing" and self.state != "playing":
            self._started_monotonic_ns = time.monotonic_ns()
        if state == "stopped":
            self._position = 0
            self._segment_cursor = 0
            self._record_cursor = 0
            self._played_records = 0
        self.state = state
        return self.status()

    def seek(self, sample_index: int | None = None, *, fraction: float | None = None) -> dict[str, Any]:
        target = None
        if sample_index is not None:
            target = int(sample_index)
        elif fraction is not None:
            if not 0.0 <= fraction <= 1.0:
                raise BackendError("bad_args", {"field": "fraction"})
            first = int(self.manifest["firstSampleIndex"])
            records = int(self.manifest["records"])
            target = first + int(fraction * records)
        if target is None or not self.segments:
            raise BackendError("bad_args", {"field": "seek"})
        if not (int(self.manifest["firstSampleIndex"]) <= target
                <= int(self.manifest["lastSampleIndex"]) + 1):
            raise BackendError("bad_args", {"field": "sampleIndex", "reason": "out-of-range"})
        for index, segment in enumerate(self.segments):
            first = int(segment.get("firstRecord") or 0)
            last = int(segment.get("lastRecord", first) or first)
            count = int(segment.get("recordCount") or 0)
            if first <= target <= last:
                self._segment_cursor = index
                self._record_cursor = self._ordinal_for_sample(first, last, target)
                self._position = target
                return self.status()
        self._segment_cursor = len(self.segments) - 1
        last_segment = self.segments[-1]
        self._record_cursor = int(last_segment.get("recordCount") or 0)
        self._position = target
        return self.status()

    def _ordinal_for_sample(self, segment_first: int, segment_last: int,
                            target: int) -> int:
        """Convert a sample index to a record ordinal inside one segment (holes)."""
        missing = 0
        for gap in self.manifest.get("gaps", []):
            try:
                gap_first = int(gap["firstMissingSampleIndex"])
                gap_last = int(gap["lastMissingSampleIndex"])
            except (KeyError, TypeError, ValueError):
                continue
            low = max(gap_first, segment_first)
            high = min(gap_last, target - 1)
            if low <= high:
                missing += high - low + 1
        return max(0, target - segment_first - missing)

    def _gaps_within(self, first_index: int, last_index: int) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for gap in self.manifest.get("gaps", []):
            try:
                gap_first = int(gap["firstMissingSampleIndex"])
                gap_last = int(gap["lastMissingSampleIndex"])
            except (KeyError, TypeError, ValueError):
                continue
            if gap_last + 1 > first_index and gap_first <= last_index:
                found.append(dict(gap))
        return found

    def next_chunk(self, max_records: int = 150) -> AudioChunk | None:
        if self.state == "stopped":
            return None
        if self.state == "paused":
            return None
        if max_records < 1:
            raise BackendError("bad_args", {"field": "maxRecords"})
        chunk = bytearray()
        count = 0
        first_index: int | None = None
        while count < max_records and self._segment_cursor < len(self.segments):
            segment = self.segments[self._segment_cursor]
            path = Path(segment["path"])
            record_count = int(segment.get("recordCount") or 0)
            if self._record_cursor >= record_count:
                self._segment_cursor += 1
                self._record_cursor = 0
                continue
            available = record_count - self._record_cursor
            take = min(max_records - count, available)
            with path.open("rb") as stream:
                stream.seek(self._record_cursor * PCM_RECORD_BYTES)
                data = stream.read(take * PCM_RECORD_BYTES)
            if len(data) != take * PCM_RECORD_BYTES:
                raise BackendError("file_corrupt", {"reason": "replay-truncated-segment",
                                                    "path": str(path)})
            if first_index is None:
                first_index = decode_record(data[:PCM_RECORD_BYTES]).sample_index
            chunk.extend(data)
            count += take
            self._record_cursor += take
            self._played_records += take
        if not chunk:
            self.state = "stopped"
            return None
        self._position = first_index
        last_index = decode_record(chunk[-PCM_RECORD_BYTES:]).sample_index
        gaps_in_chunk = self._gaps_within(first_index, last_index)
        gap_before = bool(gaps_in_chunk) or first_index in self._gap_map
        self._pace(count)
        return AudioChunk(
            source_kind=SOURCE_FILE_REPLAY, device_id=str(self.manifest.get("deviceId", "")),
            connection_epoch=int(self.manifest.get("connectionEpoch", 0)),
            session_id=str(self.manifest.get("sessionId", "")),
            stream_id=0, first_sample_index=first_index, sample_count=count,
            sample_rate_hz=self.real_rate, records=bytes(chunk),
            gap_before=gap_before,
            continuity={"continuous": not gaps_in_chunk,
                        "expectedFirstSampleIndex": None,
                        "gaps": gaps_in_chunk})

    def _pace(self, records: int) -> None:
        """Real-time pacing at the true sample rate (no resampling)."""
        expected = records / 6.0 / self.real_rate
        target = self._started_monotonic_ns + int((self._played_records / 6.0
                                                   / self.real_rate) * 1e9)
        now = time.monotonic_ns()
        if target > now:
            time.sleep((target - now) / 1e9)
        del expected

    def status(self) -> dict[str, Any]:
        return {"state": self.state, "position": self._position,
                "firstSampleIndex": self.manifest.get("firstSampleIndex"),
                "lastSampleIndex": self.manifest.get("lastSampleIndex"),
                "records": self.manifest.get("records"), "playedRecords": self._played_records,
                "realSampleRateHz": self.real_rate,
                "integerRateHz": self.manifest.get("integerRateHz"),
                "rateRoundingErrorHz": self.manifest.get("rateRoundingErrorHz"),
                "sourceKind": SOURCE_FILE_REPLAY,
                "durationSeconds": (int(self.manifest.get("records", 0)) / 6.0
                                    / self.real_rate)}

    def info(self) -> dict[str, Any]:
        return {"manifestPath": str(self.manifest_path), "manifest": self.manifest,
                "status": self.status()}
