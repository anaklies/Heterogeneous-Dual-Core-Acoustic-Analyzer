"""Event metadata + downloaded SMC1 files, with hash-gated idempotent ack."""
from __future__ import annotations

import hashlib
import json
import struct
import time
from pathlib import Path
from typing import Any

from ..constants import (SOURCE_KINDS, SOURCE_TEST_FIXTURE, EVENT_FLAG_INCOMPLETE,
    EVENT_FLAG_LOST_EVENTS, EVENT_FLAG_SUMMARY_STALE, EVENT_FLAG_ENV_INVALID,
    EVENT_FLAG_POSE_INVALID)
from ..errors import BackendError
from ..model.dto import EventRecord
from ..protocol.event_file import parse_event_container, write_event_container
from .storage import Storage


class EventManager:
    def __init__(self, directory: str | Path, storage: Storage | None = None) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.storage = storage
        self._known: dict[int, EventRecord] = {}
        self._acked: dict[int, dict[str, Any]] = {}
        self._downloaded: dict[int, dict[str, Any]] = {}

    # -- known event metadata (from event.list / eventAdded) ---------------
    def ingest_known(self, payload: dict[str, Any]) -> EventRecord:
        try:
            event_id = int(payload["eventId"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BackendError("bad_args", {"field": "eventId"}) from exc
        device_id = str(payload.get("deviceId", ""))
        epoch = int(payload.get("connectionEpoch", 0) or 0)
        session_id = str(payload.get("sessionId", ""))
        source_kind = str(payload.get("sourceKind", SOURCE_TEST_FIXTURE))
        if source_kind not in SOURCE_KINDS:
            raise BackendError("bad_args", {"field": "sourceKind"})
        flags_payload = payload.get("flags") or {}
        if isinstance(flags_payload, int):
            flags_payload = {name: bool(flags_payload & mask) for name,mask in (
                ("incomplete",EVENT_FLAG_INCOMPLETE),("lostEvents",EVENT_FLAG_LOST_EVENTS),
                ("summaryStale",EVENT_FLAG_SUMMARY_STALE),("envInvalid",EVENT_FLAG_ENV_INVALID),
                ("poseInvalid",EVENT_FLAG_POSE_INVALID))}
        if not isinstance(flags_payload, dict):
            raise BackendError("bad_args", {"field":"flags"})
        rate=payload.get("sampleRateHz")
        if rate is None and isinstance(payload.get("sampleRateFloat32Bits"),int):
            rate=struct.unpack('<f',struct.pack('<I',payload['sampleRateFloat32Bits']))[0]
        record = EventRecord(
            event_id=event_id, device_id=device_id, connection_epoch=epoch,
            session_id=session_id, source_kind=source_kind,
            captured_first_sample_index=int(payload.get("capturedFirstSampleIndex", payload.get("firstSampleIndex",0)) or 0),
            captured_last_sample_index=int(payload.get("capturedLastSampleIndex", payload.get("lastSampleIndex",0)) or 0),
            frames=int(payload.get("frames", payload.get("recordCount",0)) or 0),
            sample_rate_hz=float(rate or 0.0),
            clip_reason=int(payload.get("clipReason", 0) or 0),
            flags={key: bool(flags_payload.get(key, False))
                   for key in ("incomplete", "lostEvents", "summaryStale",
                               "envInvalid", "poseInvalid")},
            pre_q22=int(payload.get("preQ22", 0) or 0),
            post_q22=int(payload.get("postQ22", 0) or 0),
            delta_q22=int(payload.get("deltaQ22", 0) or 0),
            summary_age_samples=int(payload.get("summaryAgeSamples", 0) or 0),
            summary_valid=bool(payload.get("summaryValid", False)),
            bank=int(payload.get("bank", 0) or 0),
            offset_bytes=int(payload.get("offsetBytes", 0) or 0),
            file=dict(payload.get("file") or ({"state":"available","totalBytes":payload["totalBytes"],"sha256":payload.get("sha256","")} if "totalBytes" in payload else {"state":"missing"})),
            ack=dict(payload.get("ack") or {"acked": bool(payload.get("acked",False)), "duplicate": False}),
            created_monotonic_ns=time.monotonic_ns(),
            created_unix_ms=int(payload['createdUnixMs']) if payload.get('createdUnixMs') else None)
        if self._known.get(event_id) is None:
            saved=self.directory/f"event-{event_id:020d}"/"event.smc"
            record.file['receivedUnixMs']=str(saved.stat().st_mtime_ns//1000000 if saved.is_file() else time.time_ns()//1000000)
            manifest=saved.with_name('manifest.json')
            if saved.is_file() and manifest.is_file():
                try:
                    meta=json.loads(manifest.read_text(encoding='utf8'))
                    expected=record.file.get('sha256')
                    if expected and expected==meta.get('sha256') and hashlib.sha256(saved.read_bytes()).hexdigest()==expected:
                        record.file.update(state='verified',path=str(saved));record.manifest_path=str(manifest)
                        record.file['receivedUnixMs']=str(meta.get('receivedUnixMs') or record.file['receivedUnixMs'])
                        record.file['wavFiles']=meta.get('wavFiles',[])
                        if record.created_unix_ms is None and meta.get('createdUnixMs'):record.created_unix_ms=int(meta['createdUnixMs'])
                except (OSError,ValueError):pass
            self._known[event_id] = record
            if self.storage is not None:
                self.storage.save_event(record.to_dict(), state="known")
        return self._known[event_id]

    def list(self) -> list[dict[str, Any]]:
        return [record.to_dict() for record in
                sorted(self._known.values(), key=lambda item: item.event_id)]

    def get(self, event_id: int) -> EventRecord:
        record = self._known.get(int(event_id))
        if record is None:
            raise BackendError("unknown_event", {"eventId": str(event_id)})
        return record

    # -- downloaded event files -------------------------------------------
    def store_downloaded(self, event_id: int, container: bytes,
                         *, expected_sha256: str | None = None) -> dict[str, Any]:
        container_info = parse_event_container(container)
        if container_info.header.event_id!=int(event_id):raise BackendError('file_corrupt',{'reason':'event-id-mismatch'})
        actual = container_info.sha256
        if expected_sha256 and actual.lower() != expected_sha256.lower():
            raise BackendError("event_hash_mismatch",
                               {"eventId": str(event_id), "expected": expected_sha256,
                                "actual": actual})
        directory = self.directory / f"event-{int(event_id):020d}"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "event.smc"
        path.write_bytes(container)
        record = self._known.get(int(event_id))
        received_ms=int((record.file if record else {}).get('receivedUnixMs') or time.time_ns()//1000000)
        created_ms=record.created_unix_ms if record else None
        from .event_audio import write_event_audio
        try:audio=write_event_audio(container_info,self.directory/'录音',created_ms or received_ms,received_time=not bool(created_ms))
        except (OSError,ValueError) as exc:raise BackendError('io_error',{'reason':'event-wav-generation-failed','path':str(path),'detail':str(exc)}) from exc
        (Path(audio['folder'])/'原始数据.smc').write_bytes(container)
        manifest = {
            "format": "smc-event-manifest-v1",
            "eventId": str(event_id),
            "sha256": actual,
            "bytes": len(container),
            "createdUnixMs":str(created_ms) if created_ms else None,
            "receivedUnixMs":str(received_ms),"wavFiles":audio['wavFiles'],"audio":audio,
            "recordCount": container_info.header.record_count,
            "firstSampleIndex": str(container_info.header.first_sample_index),
            "lastSampleIndex": str(container_info.header.last_sample_index),
            "realSampleRateHz": container_info.header.sample_rate_hz,
            "flags": {"incomplete": container_info.header.incomplete,
                      "lostEvents": container_info.header.lost_events,
                      "summaryStale": container_info.header.summary_stale,
                      "envInvalid": container_info.header.env_invalid,
                      "poseInvalid": container_info.header.pose_invalid},
            "provenance": {"sourceKind": record.source_kind if record else "unknown",
                           "note": "device event file; flags preserved from container"},
            "note": "device clip reason raw field; never mapped to a sound class",
        }
        manifest_path = directory / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
        record = self._known.get(int(event_id))
        if record is not None:
            record.file = {"state": "verified", "totalBytes": str(len(container)),
                           "sha256": actual, "path": str(path),"receivedUnixMs":str(received_ms),"wavFiles":audio['wavFiles']}
            record.manifest_path = str(manifest_path)
        if self.storage is not None:
            self.storage.save_event(manifest, state="stored", directory=str(directory))
        self._downloaded[int(event_id)] = {"path": str(path), "sha256": actual,
                                           "manifestPath": str(manifest_path),"wavFiles":audio['wavFiles']}
        return {"eventId": str(event_id), "sha256": actual, "bytes": len(container),
                "path": str(path), "manifestPath": str(manifest_path),"wavFiles":audio['wavFiles']}

    def ack(self, event_id: int, sha256: str) -> dict[str, Any]:
        """Idempotent ack; only allowed after a verified stored file."""
        event_id = int(event_id)
        downloaded = self._downloaded.get(event_id)
        if downloaded is None:
            raise BackendError("bad_state", {"reason": "ack-before-store",
                                            "eventId": str(event_id)})
        if downloaded["sha256"].lower() != str(sha256).lower():
            raise BackendError("event_hash_mismatch",
                               {"eventId": str(event_id)})
        previous = self._acked.get(event_id)
        if previous is not None:
            return {"acked": True, "duplicate": True,
                    "ackedMonotonicNs": previous["ackedMonotonicNs"]}
        stamp = str(time.monotonic_ns())
        self._acked[event_id] = {"acked": True, "duplicate": False,
                                 "ackedMonotonicNs": stamp}
        record = self._known.get(event_id)
        if record is not None:
            record.ack = dict(self._acked[event_id])
        if self.storage is not None:
            self.storage.save_event(record.to_dict() if record else {"eventId": str(event_id)},
                                    state="acked", directory=str(self.directory))
        return dict(self._acked[event_id])

    def acked(self, event_id: int) -> bool:
        return int(event_id) in self._acked

    def status(self) -> dict[str, Any]:
        return {"known": len(self._known), "downloaded": len(self._downloaded),
                "acked": len(self._acked), "directory": str(self.directory)}


def write_event_file(directory: str | Path, event_id: int, container: bytes) -> dict[str, Any]:
    return write_event_container(Path(directory) / f"event-{event_id:020d}.smc", container)
