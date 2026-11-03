"""Create a deterministic test-fixture recording for UI screenshots/tests.

The recording manifest is explicitly sourceKind="test-fixture"; it is never
labelled as measured/board data. Used only by UI capture and frontend tests.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

APP_ROOT = Path(r"C:\Users\sunxi\Desktop\sixmic3D\apps\sixmic-desktop")
if str(APP_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(APP_ROOT / "backend"))

from sixmic_backend.data.recording import Recorder  # noqa: E402
from sixmic_backend.protocol.pcm import PcmRecord  # noqa: E402

SAMPLE_RATE = 48009.775390625
CHANNEL_GAIN = [0.42, 0.30, 0.22, 0.16, 0.11, 0.07]
CHANNEL_FREQ = [220.0, 330.0, 440.0, 550.0, 660.0, 880.0]
SECONDS = 4.0


def build(target: Path) -> dict:
    recorder = Recorder(
        target, recording_id="demo-fixture-recording", device_id="sixmic-demo-fixture",
        connection_epoch=3, session_id="demo-session",
        source_kind="test-fixture", real_sample_rate_hz=SAMPLE_RATE,
        max_segment_bytes=1024 * 1024, max_total_bytes=64 * 1024 * 1024)
    recorder.start()
    total_records = int(SECONDS * SAMPLE_RATE)
    gap_at = total_records // 2
    first_index = 9007199254740993
    batch: list = []

    def flush(batch: list) -> None:
        if not batch:
            return
        recorder.append_audio(b"".join(record.to_bytes() for record in batch),
                              first_sample_index=batch[0].sample_index)

    index = first_index
    for ordinal in range(total_records):
        if ordinal == gap_at:
            flush(batch)
            batch = []
            recorder.append_gap({"reason": "queue_overflow",
                                 "firstMissingSampleIndex": str(index),
                                 "lastMissingSampleIndex": str(index + 29),
                                 "droppedRecords": "30"})
            index += 30
        values = []
        for channel in range(6):
            t = ordinal / SAMPLE_RATE
            base = math.sin(2 * math.pi * CHANNEL_FREQ[channel] * t)
            envelope = 0.65 + 0.35 * math.sin(2 * math.pi * 0.35 * t + channel)
            tone = CHANNEL_GAIN[channel] * envelope * base
            noise = 0.008 * math.sin(2 * math.pi * (1700 + 210 * channel) * t + channel * 1.7)
            values.append(int(max(-1.0, min(1.0, tone + noise)) * 8388607))
        batch.append(PcmRecord(tuple(values), index))
        index += 1
        if len(batch) >= 150:
            flush(batch)
            batch = []
    flush(batch)
    recorder.stop()
    manifest = recorder.manifest.to_dict()
    return {"directory": str(target), "manifest": str(target / "manifest.json"),
            "records": manifest["records"], "durationSeconds": SECONDS,
            "sampleRateHz": SAMPLE_RATE, "sourceKind": "test-fixture"}


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        APP_ROOT / "tests" / "frontend" / "fixtures" / "demo-recording")
    if (target / "manifest.json").is_file():
        print("DEMO_EXISTS", target)
    else:
        info = build(target)
        print("DEMO_RECORDING_CREATED", info)
