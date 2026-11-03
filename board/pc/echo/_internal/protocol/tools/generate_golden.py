#!/usr/bin/env python3
"""Generate the frozen golden wire samples for sixmic-analysis v1.

Stdlib only; deterministic output. Run:
    python interfaces/pc_backend_v1/tools/generate_golden.py

The generator is intentionally independent from the product backend so that the
golden files act as a cross-implementation oracle. Do not regenerate casually:
the interface is frozen; changing a byte here is a protocol version change.
"""
from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "golden"
FROZEN_AT = "2026-10-24"

PROTOCOL = "sixmic-analysis"
VERSION = 1
MAGIC = b"SMA1"
HEADER_BYTES = 64
DEFAULT_MAX_PAYLOAD = 1048576

MSG_HELLO = 0x0001
MSG_HELLO_ACK = 0x0002
MSG_STREAM_SCHEMA = 0x0003
MSG_PCM_RECORD32 = 0x0004
MSG_RESULT_WORDS32 = 0x0005
MSG_SERVICE_SNAPSHOT = 0x0006
MSG_EVENT_FILE_CHUNK = 0x0007
MSG_STREAM_GAP = 0x0008
MSG_HEARTBEAT = 0x0009
MSG_BYE = 0x000A
MSG_ERROR = 0x000B

FLAG_CRC32_VALID = 1 << 0
FLAG_GAP_BEFORE = 1 << 1
FLAG_LAST_CHUNK = 1 << 2
FLAG_FIRST_CHUNK = 1 << 3
FLAG_DEVICE_MONOTONIC_VALID = 1 << 4
FLAG_SAMPLE_INDEX_VALID = 1 << 5

# Exact rate from the algorithm clock 49162010/1024; float32 rounds it slightly.
SAMPLE_RATE_EXACT_HZ = 48009.775390625
SAMPLE_RATE_HZ = struct.unpack("<f", struct.pack("<f", SAMPLE_RATE_EXACT_HZ))[0]
SAMPLE_RATE_BITS = struct.unpack("<I", struct.pack("<f", SAMPLE_RATE_EXACT_HZ))[0]
BIG_SAMPLE_INDEX = 9007199254740993  # 2**53 + 1: not representable in JS double


def crc32(payload: bytes) -> int:
    return zlib.crc32(payload) & 0xFFFFFFFF


def frame(message_type: int, payload: bytes = b"", *, flags: int = 0,
          stream_id: int = 0, sequence: int = 0, connection_epoch: int = 3,
          first_sample_index: int = 0, device_monotonic_ns: int = 0,
          frame_id: int = 0, config_version: int = 0) -> bytes:
    """Encode one SMA1 frame with explicit little-endian fields."""
    if payload:
        flags |= FLAG_CRC32_VALID
    header = bytearray(HEADER_BYTES)
    header[0:4] = MAGIC
    struct.pack_into("<HHHH", header, 4, VERSION, HEADER_BYTES, message_type, flags)
    struct.pack_into("<III", header, 12, len(payload), stream_id, sequence)
    struct.pack_into("<QQQ", header, 24, connection_epoch, first_sample_index, device_monotonic_ns)
    struct.pack_into("<III", header, 48, frame_id, config_version, crc32(payload))
    struct.pack_into("<I", header, 60, 0)
    return bytes(header) + payload


def pcm_record(channels, sample_index: int) -> bytes:
    """32-byte raw record: 6 x sign-extended 24-bit LE int32 + u64 sample index."""
    if len(channels) != 6:
        raise ValueError("need six channels")
    out = bytearray(32)
    for c, value in enumerate(channels):
        if not -(1 << 23) <= value < (1 << 23):
            raise ValueError("24-bit sample out of range")
        lo = value & 0xFF
        mid = (value >> 8) & 0xFF
        hi = (value >> 16) & 0xFF
        struct.pack_into("<I", out, 4 * c, lo | (mid << 8) | (hi << 16) | ((value >> 23) & 1) * 0xFF000000)
    struct.pack_into("<Q", out, 24, sample_index)
    return bytes(out)


def write(name: str, data: bytes) -> dict:
    path = GOLDEN / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def write_jsonl(name: str, obj) -> dict:
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
    return write(name, text.encode("utf-8"))


def control_request(op: str, request_id: str, args, session_id="sess-0003-01") -> dict:
    return {"protocol": PROTOCOL, "version": VERSION, "requestId": request_id,
            "sessionId": session_id, "op": op, "args": args}


def control_response(request_id: str, result) -> dict:
    return {"type": "response", "protocol": PROTOCOL, "version": VERSION,
            "requestId": request_id, "status": "ok", "result": result}


def main() -> int:
    manifest: dict[str, dict] = {}
    manifest["control/hello_request.jsonl"] = write_jsonl(
        "control/hello_request.jsonl",
        {"protocol": PROTOCOL, "version": VERSION, "requestId": "golden-0001",
         "sessionId": None, "op": "hello",
         "args": {"clientName": "BackendCheck", "clientVersion": "0.1.0",
                  "maxBinaryPayloadBytes": DEFAULT_MAX_PAYLOAD}})
    manifest["control/hello_response.jsonl"] = write_jsonl(
        "control/hello_response.jsonl",
        control_response("golden-0001", {
            "protocol": PROTOCOL, "protocolVersion": VERSION, "serverVersion": "ps-gw-0.1.0",
            "deviceId": "sixmic-dev-0001", "connectionEpoch": "3", "sessionId": "sess-0003-01",
            "limits": {"maxLineBytes": 65536, "maxBinaryPayloadBytes": DEFAULT_MAX_PAYLOAD,
                       "maxPendingJobs": 64, "duplicateCacheSeconds": 120,
                       "maxControlLeaseSeconds": 300},
            "capabilities": {"device": {"livePcm": False, "liveResults": False,
                                        "resultSnapshotProtocol": 3, "serviceSnapshots": [],
                                        "eventCapture": False, "eventDownload": False,
                                        "rawRecording": False, "profileUpload": False,
                                        "profileActivate": False, "taskControl": False,
                                        "sensorSnapshot": False, "deviceLog": True,
                                        "configCommit": False, "configVersion": 0,
                                        "protocol3": False,
                                        "missing": ["no physical board link verified",
                                                    "PS gateway not integrated on hardware"]},
                             "gateway": {"version": "ps-gw-0.1.0", "controlPort": 48120,
                                         "binaryPort": 48121}},
            "config": {"activeVersion": 10, "pending": False, "shadowDirty": False},
            "control": {"held": False}}))
    manifest["control/error_not_ready.jsonl"] = write_jsonl(
        "control/error_not_ready.jsonl",
        {"type": "response", "protocol": PROTOCOL, "version": VERSION,
         "requestId": "golden-0002", "status": "error",
         "error": {"code": "not_ready", "messageKey": "errors.not_ready", "retryable": False,
                   "detail": {"feature": "livePcm",
                              "missing": "PL raw ring PS consumer/lease not accepted"}}})
    manifest["control/job_accepted_response.jsonl"] = write_jsonl(
        "control/job_accepted_response.jsonl",
        {"type": "response", "protocol": PROTOCOL, "version": VERSION,
         "requestId": "golden-0003", "status": "accepted",
         "result": {"jobId": "job-0000000007"}})
    manifest["control/job_updated_event.jsonl"] = write_jsonl(
        "control/job_updated_event.jsonl",
        {"type": "event", "protocol": PROTOCOL, "version": VERSION,
         "event": "jobUpdated", "eventId": "12",
         "data": {"jobId": "job-0000000007", "kind": "p2OneShot",
                  "state": "completed", "progress": 1.0,
                  "createdAtMonotonicNs": "1700000000000000000",
                  "updatedAtMonotonicNs": "1700000000123000000",
                  "clientTaskKey": "task-key-1", "requestId": "golden-0003",
                  "result": {"sourceFrame": 1234}, "error": None,
                  "cancelRequested": False, "cancelAcknowledged": False}})
    manifest["control/status_get_request.jsonl"] = write_jsonl(
        "control/status_get_request.jsonl", control_request("status.get", "golden-0004", {}))
    manifest["control/config_read_response.jsonl"] = write_jsonl(
        "control/config_read_response.jsonl",
        control_response("golden-0005", {
            "shadow": [1, 10, 268435456, 4194304, 268435456, 285212672, 524288, 525312,
                       1, 301989888, 16777216, 301989888, 335544320, 318767104, 0, 10,
                       0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 64, 0],
            "active": [1, 9, 268435456, 4194304, 268435456, 285212672, 524288, 525312,
                       1, 301989888, 16777216, 301989888, 335544320, 318767104, 0, 10,
                       0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 64, 0],
            "activeVersion": 9, "pending": False}))

    # --- binary frames -------------------------------------------------------
    hello_payload = json.dumps({
        "protocol": PROTOCOL, "version": VERSION, "connectionEpoch": "3",
        "token": "0123456789abcdef0123456789abcdef",
        "maxPayloadBytes": DEFAULT_MAX_PAYLOAD}, separators=(",", ":")).encode()
    manifest["binary/hello_frame.bin"] = write("binary/hello_frame.bin",
                                               frame(MSG_HELLO, hello_payload, connection_epoch=3))
    ack_payload = json.dumps({
        "accepted": True, "maxPayloadBytes": DEFAULT_MAX_PAYLOAD, "connectionEpoch": "3",
        "streams": [{"streamId": 1, "streamType": "pcmRecord32"},
                    {"streamId": 2, "streamType": "resultWords32"}]},
        separators=(",", ":")).encode()
    manifest["binary/hello_ack_frame.bin"] = write("binary/hello_ack_frame.bin",
                                                   frame(MSG_HELLO_ACK, ack_payload,
                                                         connection_epoch=3))
    schema_payload = json.dumps({
        "streamId": 1, "streamType": "pcmRecord32", "sourceKind": "test-fixture",
        "deviceId": "sixmic-dev-0001", "connectionEpoch": "3", "encoding": "sma1",
        "units": "digital full scale PCM24 codes",
        "createdMonotonicNs": "1700000000000000000", "simulated": True,
        "pcm": {"channels": 6, "channelOrder": ["mic1", "mic2", "mic3", "mic4", "mic5", "mic6"],
                "sampleFormat": "int24-le-signextended-in-int32", "recordBytes": 32,
                "sampleIndexOffset": 24,
                "sampleIndexEncoding": "uint64-le-low-word-first",
                "sampleRateHz": SAMPLE_RATE_HZ,
                "sampleRateSource": "pl-result-word31-float32",
                "sampleRateExactHz": SAMPLE_RATE_EXACT_HZ,
                "sampleRateExactSource": "algorithm clock 49162010/1024",
                "recordRateHz": 1500.3054904371644, "frameGroupRecords": 150,
                "gapPolicy": "explicit STREAM_GAP; never silently splice"},
        "validity": {"deviceTime": "optional", "sampleIndex": "required",
                     "gapBefore": "flag"}}, separators=(",", ":")).encode()
    manifest["binary/stream_schema_pcm.bin"] = write(
        "binary/stream_schema_pcm.bin",
        frame(MSG_STREAM_SCHEMA, schema_payload, stream_id=1, sequence=0,
              connection_epoch=3, frame_id=0, config_version=10))
    # Corner PCM records: negative min, negative -1, zero, positive max, sign-extended
    records = [
        pcm_record([-8388608, 8388607, -1, 0, 1, -2], BIG_SAMPLE_INDEX),
        pcm_record([8388607, -8388608, 0, -1, -2, 1], BIG_SAMPLE_INDEX + 1),
        pcm_record([0, 0, 0, 0, 0, 0], BIG_SAMPLE_INDEX + 2),
    ]
    manifest["binary/pcm_record32_corner.bin"] = write(
        "binary/pcm_record32_corner.bin",
        frame(MSG_PCM_RECORD32, b"".join(records), stream_id=1, sequence=7,
              connection_epoch=3, first_sample_index=BIG_SAMPLE_INDEX,
              device_monotonic_ns=0, frame_id=1234, config_version=10,
              flags=FLAG_SAMPLE_INDEX_VALID))
    sound_speed_bits = struct.unpack("<I", struct.pack("<f", 343.0))[0]
    result_words = [3, 0x82000002, 1234, 10, 77, 2, 0x100000, 211285,
                    (BIG_SAMPLE_INDEX & 0xFFFFFFFF), (BIG_SAMPLE_INDEX >> 32),
                    0x00000000, 0x3F, 0, 0, 5000, 0, 0, 2355, 0x4A3C, 101325,
                    sound_speed_bits, 0x0F, (25 << 16) | 0xFFF6, 0x0000FFFF,
                    (0 << 16) | 0x7FFF, (1 << 16) | 0xFFF0, 7, 9, 0x00010002, 0, 0,
                    SAMPLE_RATE_BITS]
    manifest["binary/result_words32.bin"] = write(
        "binary/result_words32.bin",
        frame(MSG_RESULT_WORDS32, struct.pack("<32I", *result_words), stream_id=2,
              sequence=5, connection_epoch=3, first_sample_index=BIG_SAMPLE_INDEX,
              device_monotonic_ns=0, frame_id=1234, config_version=10,
              flags=FLAG_SAMPLE_INDEX_VALID))
    service_header = [0x52534C54, 42, 1, 10, 3, 0x00010002, 1234,
                      (BIG_SAMPLE_INDEX & 0xFFFFFFFF), (BIG_SAMPLE_INDEX >> 32),
                      2, 3, 851968, 0, 12345, 1, 0]
    service_payload = struct.pack("<16I", *service_header) + struct.pack("<3I", 0x3F800000, 0x40000000, 0)
    manifest["binary/service_snapshot.bin"] = write(
        "binary/service_snapshot.bin",
        frame(MSG_SERVICE_SNAPSHOT, service_payload, stream_id=3, sequence=9,
              connection_epoch=3, first_sample_index=0, frame_id=1234, config_version=10))
    gap_payload = json.dumps({
        "streamId": 1, "reason": "queue_overflow", "droppedRecords": "150",
        "firstMissingSampleIndex": "1234500", "lastMissingSampleIndex": "1234649",
        "detectedDeviceMonotonicNs": None, "sourceKind": "test-fixture"},
        separators=(",", ":")).encode()
    manifest["binary/stream_gap.bin"] = write(
        "binary/stream_gap.bin",
        frame(MSG_STREAM_GAP, gap_payload, stream_id=1, sequence=8, connection_epoch=3,
              frame_id=0, config_version=10, flags=FLAG_GAP_BEFORE))
    # Event container: 64-byte SMC1 header + two records.
    event_records = b"".join([
        pcm_record([1, 2, 3, 4, 5, 6], 1000),
        pcm_record([-1, -2, -3, -4, -5, -6], 1001),
    ])
    header = bytearray(64)
    header[0:4] = b"SMC1"
    struct.pack_into("<HH", header, 4, 1, 64)
    struct.pack_into("<II", header, 8, 32, 6)
    struct.pack_into("<II", header, 16, 0, 0x00000005)
    struct.pack_into("<Q", header, 24, 7)
    struct.pack_into("<Q", header, 32, 1000)
    struct.pack_into("<Q", header, 40, 1001)
    struct.pack_into("<Q", header, 48, 2)
    struct.pack_into("<I", header, 56, SAMPLE_RATE_BITS)
    struct.pack_into("<I", header, 60, crc32(bytes(header[0:56])))
    event_file = bytes(header) + event_records
    manifest["event/event_file_sample.smc"] = write("event/event_file_sample.smc", event_file)
    manifest["binary/event_chunk_first.bin"] = write(
        "binary/event_chunk_first.bin",
        frame(MSG_EVENT_FILE_CHUNK, event_file[:64], stream_id=4, sequence=0,
              connection_epoch=3, frame_id=0, config_version=10,
              flags=FLAG_FIRST_CHUNK | FLAG_SAMPLE_INDEX_VALID))
    manifest["binary/event_chunk_last.bin"] = write(
        "binary/event_chunk_last.bin",
        frame(MSG_EVENT_FILE_CHUNK, event_file[64:], stream_id=4, sequence=1,
              connection_epoch=3, frame_id=0, config_version=10,
              flags=FLAG_LAST_CHUNK | FLAG_SAMPLE_INDEX_VALID))
    manifest["binary/heartbeat.bin"] = write(
        "binary/heartbeat.bin", frame(MSG_HEARTBEAT, b"", flags=0, stream_id=0, sequence=0,
                                      connection_epoch=3))
    manifest["binary/bye_backpressure.bin"] = write(
        "binary/bye_backpressure.bin",
        frame(MSG_BYE, json.dumps({"reason": "backpressure"}, separators=(",", ":")).encode(),
              connection_epoch=3))
    manifest["binary/error_fatal.bin"] = write(
        "binary/error_fatal.bin",
        frame(MSG_ERROR, json.dumps({"code": "bad_crc", "messageKey": "errors.bad_crc",
                                     "detail": {"streamId": 1, "sequence": 7}},
                                    separators=(",", ":")).encode(),
              connection_epoch=3))

    manifest["_meta"] = {"protocol": PROTOCOL, "protocolVersion": VERSION,
                         "frozenAt": FROZEN_AT, "generator": "generate_golden.py",
                         "sampleRateHz": SAMPLE_RATE_HZ,
                         "sampleRateExactHz": SAMPLE_RATE_EXACT_HZ,
                         "sampleRateFloat32Bits": hex(SAMPLE_RATE_BITS),
                         "bigSampleIndex": str(BIG_SAMPLE_INDEX),
                         "note": "All binary frames are little-endian. CRC32 is IEEE reflected."}
    manifest_path = GOLDEN / "GOLDEN_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("GOLDEN_GENERATED", len(manifest) - 1, "files ->", GOLDEN)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
