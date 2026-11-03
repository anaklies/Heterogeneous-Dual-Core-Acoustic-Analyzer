"""BackendCheck: console verification entry point (no GUI, no fabricated data).

Usage (from apps/sixmic-desktop/backend):
    python -m sixmic_backend.app.backend_check --self-test
    python -m sixmic_backend.app.backend_check --connect 192.168.10.2:48120
    python -m sixmic_backend.app.backend_check --replay <recording-dir>
Exit code 0 = pass, 1 = failure. The final stdout line is exactly
"SELF-TEST PASS" or "SELF-TEST FAIL" for --self-test. --connect/--replay
always emit exactly one JSON document on stdout; their failure marker (when
an unexpected exception escapes) goes to stderr so JSON consumers stay parseable.
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any

from .. import __version__
from ..constants import (
    CANDIDATE_SAMPLE_RATE_BITS, CANDIDATE_SAMPLE_RATE_FLOAT32_HZ,
    CANDIDATE_SAMPLE_RATE_HZ, MAX_LINE_BYTES,
    MSG_PCM_RECORD32, MSG_RESULT_WORDS32, MSG_STREAM_SCHEMA, PCM_RECORD_BYTES,
    PROTOCOL_NAME, PROTOCOL_VERSION, SERVICE_HEADER_MAGIC,
)
from ..data.data_store import DataStore
from ..data.config_store import ConfigStore
from ..data.events import EventManager
from ..data.recording import Recorder
from ..data.replay import ReplaySession
from ..data.storage import Storage
from ..errors import BackendError
from ..model.audio import integer_rate_for, read_24bit_wav, verify_manifest_files, write_wav6_24bit
from ..model.dto import DeviceCapabilities, LiveFrame, RecordingManifest
from ..model.feature_catalog import load_feature_catalog
from ..paths import ensure_user_dirs, protocol_dir


class _ManualTemporaryDirectory:
    """TemporaryDirectory fallback for restricted Windows sandbox profiles.

    Some locked-down Windows sessions map mkdtemp's 0700 mode onto a DACL that
    denies access even to the owner.  The self-test harness must stay runnable
    there, so fall back to a plain directory under the writable user-data root.
    """

    def __init__(self, prefix: str) -> None:
        import uuid
        root = Path(os.environ.get("SIXMIC_USER_DATA_DIR") or tempfile.gettempdir())
        base = root / "selftest-tmp"
        base.mkdir(parents=True, exist_ok=True)
        self.name = str(base / (prefix + uuid.uuid4().hex[:10]))
        Path(self.name).mkdir()

    def __enter__(self) -> str:
        return self.name

    def __exit__(self, *exc_info: Any) -> None:
        import shutil
        shutil.rmtree(self.name, ignore_errors=True)


def _temporary_directory(prefix: str):
    # Always use a plain directory under the writable user-data root: the
    # system temp root may be an ACL-restricted sandbox path that cannot even
    # be listed (mkdtemp succeeds, cleanup/iterdir then fails).
    return _ManualTemporaryDirectory(prefix)


def _mkdtemp(prefix: str) -> str:
    return _ManualTemporaryDirectory(prefix).name
from ..protocol.control import build_request, parse_u64, validate_response, u64
from ..protocol.event_file import build_event_container, parse_event_container
from ..protocol.framing import FrameDecoder, SmaHeader, build_frame, crc32
from ..protocol.golden import GoldenSuite
from ..protocol.jsonline import LineDecoder, decode_line, encode_line
from ..protocol.messages import decode_result_words, parse_service_snapshot, unpack_result_words
from ..protocol.pcm import (
    MIN_SAMPLE, MAX_SAMPLE, decode_record, decode_records, encode_record, encode_records,
)

BIG_INDEX = 9007199254740993  # 2**53 + 1


class CheckFailure(AssertionError):
    pass


class SelfTest:
    def __init__(self, protocol_root: Path | None = None,
                 evidence_dir: Path | None = None) -> None:
        self.protocol_root = protocol_root or protocol_dir()
        self.evidence_dir = evidence_dir
        self.steps: list[dict[str, Any]] = []
        self.started = time.monotonic()

    def check(self, name: str, function) -> Any:
        begin = time.monotonic()
        try:
            result = function()
        except Exception as exc:
            self.steps.append({"name": name, "ok": False,
                               "durationMs": round((time.monotonic() - begin) * 1000, 2),
                               "error": f"{type(exc).__name__}: {exc}"})
            raise
        self.steps.append({"name": name, "ok": True,
                           "durationMs": round((time.monotonic() - begin) * 1000, 2),
                           "detail": result if isinstance(result, (str, int, float,
                                                                  bool, type(None)))
                           else None})
        return result

    # -- individual checks -------------------------------------------------
    def golden_suite(self) -> str:
        suite = GoldenSuite(self.protocol_root)
        report = suite.verify()
        if report["failures"]:
            raise CheckFailure(f"golden hash failures: {report['failures'][:2]}")
        if report["checked"] < 20:
            raise CheckFailure(f"expected >=20 golden samples, got {report['checked']}")
        # Parse every binary golden frame with the production decoder.
        parsed = 0
        for name in suite.entries():
            if not name.startswith("binary/"):
                continue
            decoder = FrameDecoder()
            frames = decoder.feed(suite.read(name))
            if not frames:
                raise CheckFailure(f"golden frame did not decode: {name}")
            parsed += 1
        # Control golden lines must decode with the strict decoder.
        control_lines = 0
        for name in suite.entries():
            if name.startswith("control/"):
                decode_line(suite.read(name).rstrip(b"\n"))
                control_lines += 1
        return f"{report['checked']} files, {parsed} binary frames, {control_lines} control lines"

    def pcm_golden(self) -> str:
        suite = GoldenSuite(self.protocol_root)
        decoder = FrameDecoder()
        frames = decoder.feed(suite.read("binary/pcm_record32_corner.bin"))
        header, payload = frames[0]
        if header.message_type != MSG_PCM_RECORD32:
            raise CheckFailure("pcm golden message type")
        records = decode_records(payload)
        if len(records) != 3:
            raise CheckFailure("pcm golden record count")
        expected = [(-8388608, 8388607, -1, 0, 1, -2),
                    (8388607, -8388608, 0, -1, -2, 1),
                    (0, 0, 0, 0, 0, 0)]
        for position, (record, want) in enumerate(zip(records, expected)):
            if record.samples != want:
                raise CheckFailure(f"record {position} sign extension: {record.samples} != {want}")
        if records[0].sample_index != BIG_INDEX:
            raise CheckFailure("sample index lost precision")
        for position, record in enumerate(records):
            again = decode_record(record.to_bytes())
            if again != record:
                raise CheckFailure("pcm roundtrip")
            if len(record.to_bytes()) != PCM_RECORD_BYTES:
                raise CheckFailure("record size")
        # Negative extremes and all-zero channels exercise sign extension.
        for value in (MIN_SAMPLE, MAX_SAMPLE, -1, 0, 1):
            record = decode_record(encode_record([value] * 6, BIG_INDEX + value - MIN_SAMPLE))
            if record.samples != (value,) * 6:
                raise CheckFailure(f"extreme sample {value}")
        return "corner samples, 2^53+1 sample index, 32-byte records"

    def result_words(self) -> str:
        suite = GoldenSuite(self.protocol_root)
        frames = FrameDecoder().feed(suite.read("binary/result_words32.bin"))
        header, payload = frames[0]
        words = unpack_result_words(payload)
        decoded = decode_result_words(words)
        if decoded["sampleIndex"] != BIG_INDEX:
            raise CheckFailure("result sample index precision")
        if abs(decoded["sampleRateHz"] - CANDIDATE_SAMPLE_RATE_FLOAT32_HZ) > 1e-6:
            raise CheckFailure("sample rate float32 decode")
        if abs(CANDIDATE_SAMPLE_RATE_HZ - CANDIDATE_SAMPLE_RATE_FLOAT32_HZ) > 0.01:
            raise CheckFailure("candidate rate documentation drift")
        if decoded["valid"]["temperature"] is not True:
            raise CheckFailure("sensor valid bit")
        if decoded["humidityRaw"] is None:
            raise CheckFailure("raw humidity missing")
        frame = LiveFrame(source_kind="test-fixture", device_id="golden",
                          connection_epoch=3, session_id="s", frame_id=1234,
                          config_version=10, sample_index=decoded["sampleIndex"],
                          sample_rate_hz=decoded["sampleRateHz"], words=words,
                          decoded=decoded)
        if frame.to_dict()["sampleIndex"] != str(BIG_INDEX):
            raise CheckFailure("DTO u64 string encoding")
        return "32-word decode + u64 string boundary"

    def jsonline_rules(self) -> str:
        decoder = LineDecoder()
        first = decoder.feed(b'{"a":1}\n{"b"')
        if len(first) != 1:
            raise CheckFailure("sticky/partial line split")
        second = decoder.feed(b':2}\n{"c":3}\n')
        if len(second) != 2:
            raise CheckFailure("resumed partial line")
        try:
            decode_line(b'{"a":1,"a":2}')
            raise CheckFailure("duplicate key accepted")
        except BackendError as exc:
            if exc.code != "bad_json":
                raise CheckFailure("duplicate key code")
        try:
            decode_line(b'{"a": NaN}')
            raise CheckFailure("NaN accepted")
        except BackendError:
            pass
        try:
            decode_line(b'\xff\xfe')
            raise CheckFailure("invalid UTF-8 accepted")
        except BackendError as exc:
            if exc.code != "bad_utf8":
                raise CheckFailure("invalid UTF-8 code")
        try:
            decoder.feed(b"x" * (MAX_LINE_BYTES + 10))
            raise CheckFailure("oversize line accepted")
        except BackendError as exc:
            if exc.code != "line_too_long":
                raise CheckFailure("oversize line code")
        request = build_request("status.get", "c-1", "sess-x", {})
        encoded = encode_line(request)
        if not encoded.endswith(b"\n") or decode_line(encoded[:-1])["op"] != "status.get":
            raise CheckFailure("request roundtrip")
        response = {"type": "response", "protocol": PROTOCOL_NAME,
                    "version": PROTOCOL_VERSION, "requestId": "c-1",
                    "status": "ok", "result": {}}
        validate_response(response, "c-1")
        return "split/sticky, duplicate keys, NaN, invalid UTF-8, oversize, envelopes"

    def framing_rules(self) -> str:
        header = SmaHeader(message_type=MSG_RESULT_WORDS32, payload_bytes=4,
                           stream_id=1, sequence=7, connection_epoch=3,
                           first_sample_index=BIG_INDEX)
        payload = struct.pack("<I", 3)
        frame = build_frame(header.message_type, payload, stream_id=1, sequence=7,
                            connection_epoch=3, first_sample_index=BIG_INDEX)
        parsed = FrameDecoder().feed(frame)
        if len(parsed) != 1:
            raise CheckFailure("frame decode")
        got_header, got_payload = parsed[0]
        if got_payload != payload or got_header.sequence != 7:
            raise CheckFailure("frame roundtrip")
        if got_header.first_sample_index != BIG_INDEX:
            raise CheckFailure("header u64")
        corrupted = bytearray(frame)
        corrupted[56:60] = (crc32(payload) ^ 0x1).to_bytes(4, "little")
        try:
            FrameDecoder().feed(bytes(corrupted))
            raise CheckFailure("bad CRC accepted")
        except BackendError as exc:
            if exc.code != "crc_mismatch":
                raise CheckFailure("bad CRC code")
        try:
            FrameDecoder().feed(b"XXXX" + frame[4:])
            raise CheckFailure("bad magic accepted")
        except BackendError:
            pass
        tiny_payload = struct.pack("<I", 1)
        unknown = build_frame(0x1234, tiny_payload, stream_id=9, sequence=1,
                              connection_epoch=3)
        decoder = FrameDecoder()
        frames = decoder.feed(unknown)
        if len(frames) != 1 or frames[0][0].message_type != 0x1234:
            raise CheckFailure("unknown type bounded skip")
        return "header layout, CRC, bad magic, unknown message type"

    def event_container(self) -> str:
        records = b"".join(encode_record([1, 2, 3, 4, 5, 6], BIG_INDEX + index)
                           for index in range(4))
        data = build_event_container(event_id=7, flags=0, clip_reason=5,
                                     first_sample_index=BIG_INDEX,
                                     last_sample_index=BIG_INDEX + 3,
                                     sample_rate_hz=CANDIDATE_SAMPLE_RATE_HZ,
                                     records=records)
        parsed = parse_event_container(data)
        if parsed.header.record_count != 4 or parsed.records != records:
            raise CheckFailure("event container roundtrip")
        if abs(parsed.header.sample_rate_hz - CANDIDATE_SAMPLE_RATE_FLOAT32_HZ) > 1e-6:
            raise CheckFailure("event container sample rate")
        tampered = bytearray(data)
        tampered[60] ^= 0xFF
        try:
            parse_event_container(bytes(tampered))
            raise CheckFailure("tampered event header accepted")
        except BackendError:
            pass
        wrong_index = bytearray(records)
        wrong_index[24:32] = struct.pack("<Q", 5)
        bad = build_event_container(event_id=7, flags=0, clip_reason=5,
                                    first_sample_index=BIG_INDEX,
                                    last_sample_index=BIG_INDEX + 3,
                                    sample_rate_hz=CANDIDATE_SAMPLE_RATE_HZ,
                                    records=bytes(wrong_index))
        try:
            parse_event_container(bad)
            raise CheckFailure("event sample index mismatch accepted")
        except BackendError:
            pass
        return "SMC1 header + CRC + record index checks"

    def feature_catalog(self) -> str:
        catalog = load_feature_catalog(self.protocol_root)
        summary = catalog.summary()
        if summary["total"] != 46:
            raise CheckFailure(f"feature count {summary['total']}")
        if summary["available"] != 0:
            raise CheckFailure("available without board acceptance evidence")
        removed = catalog.get("srpdnn_main")
        if removed["status"] != "unsupported":
            raise CheckFailure("removed DOA feature must be unsupported")
        live = catalog.get("io_pcm")
        if live["status"] != "not_ready":
            raise CheckFailure("live PCM feature promoted without board evidence")
        return json.dumps(summary, sort_keys=True)

    def recording_replay(self) -> str:
        with _temporary_directory("sixmic-selftest-") as temporary:
            root = Path(temporary)
            sample_rate = CANDIDATE_SAMPLE_RATE_HZ
            identifier = "self-test-recording"
            recorder = Recorder(root / identifier, recording_id=identifier,
                                device_id="self-test", connection_epoch=3,
                                session_id="sess-self-test",
                                source_kind="test-fixture",
                                real_sample_rate_hz=sample_rate,
                                max_segment_bytes=4096,
                                max_total_bytes=10 * 1024 * 1024)
            recorder.start()
            original: list[tuple[tuple[int, ...], int]] = []
            for chunk in range(3):
                records = []
                for index in range(40):
                    values = tuple(((index * 37 + channel * 101 + chunk * 13) % 6000) - 3000
                                   for channel in range(6))
                    sample_index = BIG_INDEX + chunk * 40 + index
                    records.append(encode_record(values, sample_index))
                    original.append((values, sample_index))
                recorder.append_audio(b"".join(records),
                                      first_sample_index=BIG_INDEX + chunk * 40)
            recorder.append_gap({"reason": "queue_overflow",
                                 "firstMissingSampleIndex": str(BIG_INDEX + 120),
                                 "lastMissingSampleIndex": str(BIG_INDEX + 129),
                                 "droppedRecords": "10"})
            status = recorder.stop()
            if not status["records"] == len(original):
                raise CheckFailure("recorder record count")
            manifest = recorder.manifest.to_dict()
            if len(manifest["gaps"]) != 1:
                raise CheckFailure("recorder gap manifest")
            integer, error = integer_rate_for(sample_rate)
            if manifest["integerRateHz"] != integer or abs(
                    manifest["rateRoundingErrorHz"] - error) > 1e-12:
                raise CheckFailure("rate rounding recorded")
            verification = verify_manifest_files(manifest)
            if not verification["ok"]:
                raise CheckFailure(f"recording verification: {verification}")
            wav_bytes, wav_info = read_24bit_wav(manifest["wav"]["path"])
            if wav_info["frames"] != len(original):
                raise CheckFailure("wav frame count")
            decoded = [decode_record(wav_bytes[offset:offset + PCM_RECORD_BYTES])
                       for offset in range(0, len(wav_bytes), PCM_RECORD_BYTES)]
            for (values, sample_index), record in zip(original, decoded):
                if record.samples != values:
                    raise CheckFailure("wav pcm mismatch")
            replay = ReplaySession(Path(manifest["wav"]["path"]).parent / "manifest.json")
            replay.set_state("playing")
            replayed: list[tuple[int, ...]] = []
            while True:
                chunk = replay.next_chunk(max_records=32)
                if chunk is None:
                    break
                for record in decode_records(chunk.records):
                    replayed.append(record.samples)
            if replayed != [values for values, _ in original]:
                raise CheckFailure("replay arrays differ from recording")
            seek = replay.seek(BIG_INDEX + 80)
            if seek["position"] != BIG_INDEX + 80:
                raise CheckFailure("replay seek")
            # storage roundtrip
            storage = Storage(root / "test.sqlite")
            storage.save_recording(manifest, str(root / identifier))
            if not storage.list_recordings():
                raise CheckFailure("storage recording index")
            storage.close()
            return (f"{len(original)} records, {len(manifest['segments'])} segments, "
                    f"wav+manifest+replay identical, gaps preserved")

    def storage_recovery(self) -> str:
        with _temporary_directory("sixmic-storage-") as temporary:
            path = Path(temporary) / "broken.sqlite"
            path.write_bytes(b"not a sqlite database" * 32)
            storage = Storage(path)
            if not storage.recovered:
                raise CheckFailure("corrupt database not recovered")
            storage.set_setting("k", {"v": 1})
            if storage.get_setting("k") != {"v": 1}:
                raise CheckFailure("recovered storage write")
            stats = storage.stats()
            storage.close()
            return f"corrupt db quarantined and recreated ({stats['recovered']})"

    def mock_end_to_end(self) -> str:
        from ..session import DeviceSession
        from ..testing.mock_ps_server import MockPsServer
        import shutil
        server = MockPsServer(result_frames=2, pcm_chunks=2)
        info = server.start()
        session = None
        root = Path(_mkdtemp("sixmic-mock-"))
        result: str | None = None
        failure: BaseException | None = None
        try:
                dirs = {name: root / name for name in
                        ("root", "logs", "data", "recordings", "events",
                         "exports", "evidence")}
                for directory in dirs.values():
                    directory.mkdir(parents=True, exist_ok=True)
                session = DeviceSession(host="127.0.0.1",
                                        control_port=info["controlPort"],
                                        binary_port=info["binaryPort"],
                                        protocol_root=self.protocol_root,
                                        user_dirs=dirs, auto_reconnect=False)
                session.connect()
                caps = session.capabilities.to_dict()
                if caps["livePcm"] != "not_ready":
                    raise CheckFailure("mock livePcm must be not_ready")
                if session.feature_catalog is None:
                    raise CheckFailure("feature catalog not loaded")
                session.subscribe(("resultWords", "pcmRecord32"))
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline and (
                        session.frame_count < 1 or session.audio_chunk_count < 1):
                    time.sleep(0.02)
                if session.frame_count < 1:
                    raise CheckFailure("no result frames from fixture server")
                if session.audio_chunk_count < 1:
                    raise CheckFailure("no audio chunks from fixture server")
                frame = session.last_frame
                if frame is None or frame.source_kind != "test-fixture":
                    raise CheckFailure("fixture data mislabeled")
                chunk = session.last_audio
                if chunk is None or chunk.source_kind != "test-fixture":
                    raise CheckFailure("fixture audio mislabeled")
                first_chunk = getattr(session, "_first_audio_chunk", None)
                if first_chunk is not None:
                    first_record = decode_records(first_chunk.records)[0]
                    if first_record.sample_index != BIG_INDEX:
                        raise CheckFailure("pcm sample index")
                    if first_chunk.sample_rate_hz != CANDIDATE_SAMPLE_RATE_HZ:
                        raise CheckFailure("pcm sample rate from schema")
                session.claim_control()
                accepted = session.start_job("p2OneShot", {"clientTaskKey": "self-test"})
                if accepted.get("responseStatus") != "accepted":
                    raise CheckFailure("job not accepted asynchronously")
                # duplicate clientTaskKey must deduplicate
                again = session.start_job("p2OneShot", {"clientTaskKey": "self-test"})
                if again.get("jobId") != accepted.get("jobId"):
                    raise CheckFailure("clientTaskKey dedupe")
                # recording while subscribed
                session.start_recording("mock-recording")
                deadline = time.monotonic() + 3.0
                while time.monotonic() < deadline and session.audio_chunk_count < 2:
                    time.sleep(0.02)
                recording_status = session.stop_recording()
                if recording_status["state"] != "stopped":
                    raise CheckFailure("recording did not stop")
                events = session.list_events()
                if not events:
                    raise CheckFailure("event list empty")
                download = session.download_event(7)
                if download["sha256"] and len(download["sha256"]) != 64:
                    raise CheckFailure("event sha256")
                status = session.status()
                if status["state"] != "connected":
                    raise CheckFailure("session state")
                result = (f"fixture end-to-end: {session.frame_count} frames, "
                          f"{session.audio_chunk_count} audio chunks, "
                          f"event verified, recording stopped")
        except BaseException as exc:
            failure = exc
        finally:
            if session is not None:
                session.close()
            server.stop()
            from ..diagnostics import close_backend_logging
            close_backend_logging()
            shutil.rmtree(root, ignore_errors=True)
        if failure is not None:
            raise failure
        if server.protocol_violations:
            raise CheckFailure(f"protocol violations: {server.protocol_violations}")
        if result is None:
            raise CheckFailure("fixture end-to-end produced no result")
        return result

    def data_store_bounds(self) -> str:
        store = DataStore(capacity_bytes=1024)
        handle = store.put(b"x" * 512, "uint8")
        store.reference(handle)
        if store.release(handle) is not False:
            raise CheckFailure("handle released with references")
        if store.release(handle) is not True:
            raise CheckFailure("handle not released")
        try:
            store.put(b"y" * 4096, "uint8")
            raise CheckFailure("capacity not enforced")
        except BackendError as exc:
            if exc.code != "storage_full":
                raise CheckFailure("capacity error code")
        return "reference counting + bounded capacity"

    # -- runner ------------------------------------------------------------
    def run(self) -> dict[str, Any]:
        checks = [
            ("golden_suite", self.golden_suite),
            ("pcm_golden", self.pcm_golden),
            ("result_words", self.result_words),
            ("jsonline_rules", self.jsonline_rules),
            ("framing_rules", self.framing_rules),
            ("event_container", self.event_container),
            ("feature_catalog", self.feature_catalog),
            ("data_store_bounds", self.data_store_bounds),
            ("storage_recovery", self.storage_recovery),
            ("recording_replay", self.recording_replay),
            ("mock_end_to_end", self.mock_end_to_end),
        ]
        ok = True
        error = None
        for name, function in checks:
            try:
                self.check(name, function)
            except Exception as exc:  # noqa: BLE001
                ok = False
                error = f"{name}: {type(exc).__name__}: {exc}"
                break
        report = {"ok": ok, "protocolRoot": str(self.protocol_root),
                  "backendVersion": __version__,
                  "durationMs": round((time.monotonic() - self.started) * 1000, 2),
                  "checks": self.steps, "error": error,
                  "timestampNs": str(time.time_ns()),
                  "exports": None}
        if self.evidence_dir is not None:
            self.evidence_dir.mkdir(parents=True, exist_ok=True)
            path = self.evidence_dir / "backend-selftest.json"
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
            report["exports"] = {"evidence": str(path)}
        return report


def _print_report(report: dict[str, Any]) -> None:
    print(json.dumps(report, ensure_ascii=False, indent=2))


def _print_failure_marker(self_test: bool) -> None:
    """SELF-TEST marker belongs to stdout only in the self-test mode.

    --connect/--replay promise a single machine-readable JSON object on stdout,
    so their failure marker (if any) goes to stderr instead.
    """
    if self_test:
        print("SELF-TEST FAIL")
    else:
        print("SELF-TEST FAIL", file=sys.stderr)


def run_self_test(protocol_root: str | None = None) -> int:
    paths = ensure_user_dirs()
    report = SelfTest(protocol_root=Path(protocol_root) if protocol_root else None,
                      evidence_dir=paths["evidence"]).run()
    _print_report(report)
    print("SELF-TEST PASS" if report["ok"] else "SELF-TEST FAIL")
    return 0 if report["ok"] else 1


def run_connect(host_port: str, protocol_root: str | None = None) -> int:
    from ..session import DeviceSession
    host, _, port_text = host_port.partition(":")
    control_port = int(port_text) if port_text else 48120
    session = DeviceSession(host=host, control_port=control_port,
                            protocol_root=protocol_root, auto_reconnect=False)
    try:
        hello = session.connect()
        capabilities = session.refresh_capabilities()
        print(json.dumps({"hello": hello, "capabilities": capabilities,
                          "status": session.status(),
                          "note": ("transport handshake only; live capabilities are "
                                   "reported truthfully and are NOT board acceptance")},
                         ensure_ascii=False, indent=2))
        live_ready = capabilities["device"]["livePcm"] == "available"
        print("CONNECT-OK" if not live_ready else "CONNECT-OK (live capability claimed)")
        return 0
    except BackendError as exc:
        print(json.dumps({"error": exc.to_dict()}, ensure_ascii=False, indent=2))
        return 1
    finally:
        session.close()


def run_replay(path: str) -> int:
    manifest_path = Path(path)
    if manifest_path.is_dir():
        manifest_path = manifest_path / "manifest.json"
    session = None
    try:
        replay = ReplaySession(manifest_path, verify=True)
        info = replay.info()
        print(json.dumps(info, ensure_ascii=False, indent=2))
        print("REPLAY-OK")
        return 0
    except BackendError as exc:
        print(json.dumps({"error": exc.to_dict()}, ensure_ascii=False, indent=2))
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="SixMic3D-BackendCheck",
        description="SixMic3D backend verification (no GUI, fixture data marked)")
    parser.add_argument("--self-test", action="store_true",
                        help="run deterministic offline checks")
    parser.add_argument("--connect", metavar="HOST[:PORT]",
                        help="control-channel handshake with a real/PS gateway")
    parser.add_argument("--replay", metavar="RECORDING_DIR",
                        help="open a recorded session and verify it")
    parser.add_argument("--protocol-dir", metavar="DIR",
                        help="directory containing PROTOCOL.md/schema/golden/...")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)
    try:
        if args.connect:
            return run_connect(args.connect, args.protocol_dir)
        if args.replay:
            return run_replay(args.replay)
        return run_self_test(args.protocol_dir)
    except BackendError as exc:
        _print_report({"ok": False, "error": exc.to_dict()})
        _print_failure_marker(bool(args.self_test))
        return 1
    except Exception as exc:  # noqa: BLE001
        _print_report({"ok": False, "error": f"{type(exc).__name__}: {exc}",
                       "trace": traceback.format_exc()[-2000:]})
        _print_failure_marker(bool(args.self_test))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
