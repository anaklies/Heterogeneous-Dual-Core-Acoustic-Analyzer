"""Frontend display-only offline reference analysis (explicitly NOT PL-live).

Purpose: after the user opens a recorded session, this module can produce
clearly-labelled "offline-reference" views (FFT/PSD/STFT/octave/levels/coherence)
for display and report illustration. It never runs automatically, never replaces
Live data, and is always tagged sourceKind="offline-reference" in the UI.
Raw numeric export continues to use the backend recording files.

The formal acoustic measurement remains the PL (hardware) path; these are PC
offline references and must never be presented as certified or pl-live results.
"""
from __future__ import annotations

import cmath
import json
import math
import struct
from pathlib import Path
from typing import Any

PCM_RECORD_BYTES = 32
CHANNELS = 6

SOURCES = {
    "sourceKind": "offline-reference",
    "scope": "PC offline reference on recorded PCM (display/report illustration only)",
    "notCertified": True,
}


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if payload.get("format") != "smc-recording-v1":
        raise ValueError("unsupported recording format")
    return payload


def _decode_record(record: bytes) -> tuple[tuple[int, ...], int]:
    samples = []
    for channel in range(CHANNELS):
        pattern = struct.unpack_from("<I", record, channel * 4)[0]
        raw = pattern & 0xFFFFFF
        value = raw - 0x1000000 if raw & 0x800000 else raw
        samples.append(value / 8388608.0)
    index = struct.unpack_from("<Q", record, 24)[0]
    return tuple(samples), index


class OfflineReference:
    """Lazy loader + display-only computations over a recorded session."""

    def __init__(self, manifest_path: str | Path) -> None:
        self.manifest_path = Path(manifest_path)
        self.manifest = _load_manifest(self.manifest_path)
        self.directory = self.manifest_path.parent
        self.rate = float(self.manifest["realSampleRateHz"])
        self.records = int(self.manifest["records"])
        self.segments = list(self.manifest.get("segments", []))
        self._cache: dict[str, Any] = {}

    # -- data access -------------------------------------------------------
    def info(self) -> dict[str, Any]:
        return {
            **SOURCES,
            "manifestPath": str(self.manifest_path),
            "recordingId": self.manifest.get("recordingId"),
            "sourceKindOriginal": self.manifest.get("sourceKind"),
            "sampleRateHz": self.rate,
            "realSampleRateHz": self.rate,
            "integerRateHz": self.manifest.get("integerRateHz"),
            "rateRoundingErrorHz": self.manifest.get("rateRoundingErrorHz"),
            "records": self.records,
            "durationSeconds": (self.records / self.rate) if self.rate else 0.0,
            "firstSampleIndex": self.manifest.get("firstSampleIndex"),
            "lastSampleIndex": self.manifest.get("lastSampleIndex"),
            "gaps": self.manifest.get("gaps", []),
            "flags": self.manifest.get("flags", {}),
        }

    def read_samples(self, max_records: int = 65536,
                     start_record: int = 0) -> list[tuple[tuple[int, ...], int]]:
        """Read bounded records from the recorded segments (display/reference)."""
        out: list[tuple[tuple[int, ...], int]] = []
        remaining = max(0, int(max_records))
        skip = max(0, int(start_record))
        for segment in self.segments:
            if remaining <= 0:
                break
            path = Path(segment.get("path", ""))
            count = int(segment.get("recordCount") or 0)
            if not path.is_file() or count <= 0:
                continue
            if skip >= count:
                skip -= count
                continue
            take = min(remaining, count - skip)
            with path.open("rb") as stream:
                stream.seek(skip * PCM_RECORD_BYTES)
                data = stream.read(take * PCM_RECORD_BYTES)
            for offset in range(0, len(data), PCM_RECORD_BYTES):
                out.append(_decode_record(data[offset:offset + PCM_RECORD_BYTES]))
            remaining -= take
            skip = 0
        return out

    def channel_series(self, channel: int, max_records: int = 32768,
                       start_seconds: float = 0.0) -> tuple[list[float], list[tuple[int, int]]]:
        start_record = int(start_seconds * self.rate / CHANNELS)
        records = self.read_samples(max_records, start_record)
        values = [record[0][channel] for record in records]
        indexes = [record[1] for record in records]
        gaps: list[tuple[int, int]] = []
        for position in range(1, len(indexes)):
            if indexes[position] != indexes[position - 1] + 1:
                gaps.append((position - 1, position))
        return values, gaps

    # -- DSP (display-only reference) -------------------------------------
    def waveform(self, channel: int, *, seconds: float = 2.0,
                 max_points: int = 2048) -> dict[str, Any]:
        max_records = max(6, int(seconds * 6 * self.rate / CHANNELS))
        values, gaps = self.channel_series(channel, max_records * CHANNELS)
        display = _downsample(values, max_points)
        gap_ranges = []
        if gaps and values:
            scale = max(1, len(values)) / max(1, len(display))
            gap_ranges = [{"start": a / scale, "end": b / scale} for a, b in gaps]
        return {"values": display, "sampleRate": self.rate, "gaps": gap_ranges,
                "sourceKind": "offline-reference", "points": len(display)}

    def levels(self, channel: int = 0, *, seconds: float = 2.0) -> dict[str, Any]:
        records = self.read_samples(int(seconds * 6 * self.rate / CHANNELS) * CHANNELS)
        if not records:
            return {**SOURCES, "perChannel": []}
        rms = [0.0] * 6
        peak = [0.0] * 6
        clipped = [0] * 6
        for record, _ in records:
            for ch in range(6):
                value = record[ch]
                rms[ch] += value * value
                peak[ch] = max(peak[ch], abs(value))
                if abs(value) >= 0.999999:
                    clipped[ch] += 1
        count = max(1, len(records))
        per_channel = []
        for ch in range(6):
            rms_value = math.sqrt(rms[ch] / count)
            per_channel.append({
                "channel": ch + 1,
                "rmsDbFS": 20 * math.log10(max(rms_value, 1e-12)),
                "peakDbFS": 20 * math.log10(max(peak[ch], 1e-12)),
                "crestFactor": peak[ch] / max(rms_value, 1e-12),
                "clipSamples": clipped[ch],
            })
        return {**SOURCES, "perChannel": per_channel}

    def fft(self, channel: int = 0, *, nfft: int = 2048, frames: int = 4,
            seconds: float = 2.0) -> dict[str, Any]:
        values, _ = self.channel_series(channel, int(seconds * 6 * self.rate / CHANNELS) * CHANNELS)
        nfft = _power_of_two(max(64, min(nfft, 8192)))
        window = _hann(nfft)
        window_energy = sum(value * value for value in window)
        if len(values) < nfft:
            return {**SOURCES, "frequency": [], "magnitudeDbFS": [],
                    "psdDbFSHz": [], "nfft": nfft, "reason": "recording shorter than FFT window"}
        frames = max(1, min(frames, max(1, (len(values) - nfft) // max(1, nfft // 2) + 1)))
        magnitude = [0.0] * (nfft // 2 + 1)
        psd = [0.0] * (nfft // 2 + 1)
        hop = max(1, (len(values) - nfft) // frames) if frames > 1 else nfft
        for frame in range(frames):
            start = min(frame * hop, len(values) - nfft)
            block = [values[start + i] * window[i] for i in range(nfft)]
            spectrum = _fft(block)
            for bin_index in range(nfft // 2 + 1):
                value = abs(spectrum[bin_index])
                magnitude[bin_index] += value
                psd[bin_index] += (value * value)
        scale = 1.0 / frames
        freq = [bin_index * self.rate / nfft for bin_index in range(nfft // 2 + 1)]
        # One-sided amplitude of a Hann-windowed sine: A = 2*|X|/sum(w).
        magnitude_db = [20 * math.log10(max(value * scale * 2.0 / window_energy, 1e-15))
                        for value in magnitude]
        # Welch-style PSD density (FS^2 / Hz), one-sided doubling for bins 1..N/2-1.
        psd_db = [10 * math.log10(max(value * scale * 2.0 / (self.rate * window_energy), 1e-30))
                  for value in psd]
        return {**SOURCES, "frequency": freq, "magnitudeDbFS": magnitude_db,
                "psdDbFSHz": psd_db, "nfft": nfft, "window": f"hann-{nfft}",
                "frames": frames, "sampleRateHz": self.rate,
                "units": {"magnitude": "dBFS (relative)", "psd": "dBFS/Hz (relative)"}}

    def stft(self, channel: int = 0, *, nfft: int = 512, hop: int = 256,
             max_frames: int = 240, seconds: float = 4.0) -> dict[str, Any]:
        values, _ = self.channel_series(channel, int(seconds * 6 * self.rate / CHANNELS) * CHANNELS)
        nfft = _power_of_two(max(64, min(nfft, 2048)))
        hop = max(1, min(hop, nfft))
        window = _hann(nfft)
        frames: list[list[float]] = []
        position = 0
        while position + nfft <= len(values) and len(frames) < max_frames:
            block = [values[position + i] * window[i] for i in range(nfft)]
            spectrum = _fft(block)
            row = [20 * math.log10(max(abs(spectrum[bin_index]) * 2.0 / sum(window), 1e-15))
                   for bin_index in range(nfft // 2 + 1)]
            frames.append(row)
            position += hop
        if not frames:
            return {**SOURCES, "matrix": [], "reason": "recording shorter than STFT window"}
        freq = [bin_index * self.rate / nfft for bin_index in range(nfft // 2 + 1)]
        time_axis = [(index * hop + nfft / 2) / self.rate for index in range(len(frames))]
        return {**SOURCES, "matrix": frames, "frequency": freq, "timeSeconds": time_axis,
                "nfft": nfft, "hop": hop, "window": f"hann-{nfft}",
                "sampleRateHz": self.rate, "units": "dBFS (relative)"}

    def octave_bands(self, channel: int = 0, *, fraction: int = 3,
                     seconds: float = 4.0) -> dict[str, Any]:
        spectrum = self.fft(channel, nfft=4096, frames=8, seconds=seconds)
        freq = spectrum.get("frequency") or []
        psd = spectrum.get("psdDbFSHz") or []
        if not freq:
            return {**SOURCES, "bands": [], "reason": spectrum.get("reason")}
        centers = []
        if fraction == 1:
            centers = [31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
        else:
            base = 1000.0
            for index in range(-17, 14):
                center = base * (2.0 ** (index / 3.0))
                if 20 <= center <= 20000:
                    centers.append(round(center, 2))
        bands = []
        for center in centers:
            low = center * (2.0 ** (-1.0 / (2 * fraction)))
            high = center * (2.0 ** (1.0 / (2 * fraction)))
            selected = [psd[i] for i in range(len(freq)) if low <= freq[i] < high]
            if selected:
                power = sum(10 ** (value / 10.0) for value in selected)
                bands.append({"centerHz": center,
                              "levelDb": 10 * math.log10(max(power, 1e-30)),
                              "bins": len(selected)})
            else:
                bands.append({"centerHz": center, "levelDb": None, "bins": 0})
        return {**SOURCES, "bands": bands, "fraction": fraction,
                "units": "relative band energy (dB, FS-referenced; not dB SPL)",
                "certified": False}

    def pair_spectral(self, first: int = 0, second: int = 1, *,
                      nfft: int = 2048, frames: int = 8,
                      seconds: float = 2.0) -> dict[str, Any]:
        max_records = int(seconds * 6 * self.rate / CHANNELS) * CHANNELS
        records = self.read_samples(max_records)
        if len(records) < nfft:
            return {**SOURCES, "reason": "recording shorter than window"}
        nfft = _power_of_two(nfft)
        window = _hann(nfft)
        hop = max(1, (len(records) - nfft) // max(1, frames))
        sum_x = [0j] * (nfft // 2 + 1)
        sum_y = [0j] * (nfft // 2 + 1)
        accum = [0j] * (nfft // 2 + 1)
        count = 0
        for frame in range(frames):
            start = min(frame * hop, len(records) - nfft)
            x = _fft([records[start + i][0][first] * window[i] for i in range(nfft)])
            y = _fft([records[start + i][0][second] * window[i] for i in range(nfft)])
            for bin_index in range(nfft // 2 + 1):
                sum_x[bin_index] += x[bin_index]
                sum_y[bin_index] += y[bin_index]
                accum[bin_index] += x[bin_index].conjugate() * y[bin_index]
            count += 1
        count = max(1, count)
        coherence = []
        phase = []
        csd_db = []
        freq = []
        for bin_index in range(nfft // 2 + 1):
            sx = abs(sum_x[bin_index]) / count
            sy = abs(sum_y[bin_index]) / count
            cross = accum[bin_index] / count
            denom = sx * sy
            coherence.append(min(1.0, abs(cross) / denom) if denom > 1e-30 else 0.0)
            phase.append(math.degrees(cmath.phase(cross)))
            csd_db.append(20 * math.log10(max(abs(cross), 1e-30)))
            freq.append(bin_index * self.rate / nfft)
        return {**SOURCES, "frequency": freq, "coherence": coherence,
                "phaseDeg": phase, "csdDb": csd_db, "pair": [first, second],
                "units": {"coherence": "0..1", "phase": "degrees", "csd": "dB (relative)"},
                "note": "offline reference; not a source-direction claim"}

    def cepstrum(self, channel: int = 0, *, nfft: int = 2048,
                 seconds: float = 1.0) -> dict[str, Any]:
        spectrum = self.fft(channel, nfft=nfft, frames=1, seconds=seconds)
        magnitude = spectrum.get("magnitudeDbFS") or []
        if not magnitude:
            return {**SOURCES, "reason": spectrum.get("reason")}
        log_mag = [10 ** (value / 20.0) for value in magnitude]
        real = log_mag + list(reversed(log_mag[1:-1]))
        spectrum_complex = _fft(real)
        cep = [abs(value) for value in spectrum_complex[: len(real) // 2]]
        quefrency = [index / self.rate for index in range(len(cep))]
        return {**SOURCES, "quefrencySeconds": quefrency, "cepstrum": cep,
                "units": "log-magnitude cepstrum (reference)"}


def _downsample(values: list[float], max_points: int) -> list[float]:
    if len(values) <= max_points:
        return [round(value, 6) for value in values]
    stride = len(values) / max_points
    out = []
    for index in range(max_points):
        start = int(index * stride)
        end = max(start + 1, int((index + 1) * stride))
        block = values[start:end]
        if not block:
            continue
        out.append(max(block, key=abs))
    return [round(value, 6) for value in out]


def _power_of_two(value: int) -> int:
    result = 1
    while result < value:
        result <<= 1
    return result


def _hann(size: int) -> list[float]:
    return [0.5 - 0.5 * math.cos(2 * math.pi * index / max(1, size - 1))
            for index in range(size)]


def _fft(values: list[float] | list[complex]) -> list[complex]:
    """Iterative radix-2 FFT (display-only; no acoustic algorithm replacement)."""
    size = len(values)
    if size & (size - 1):
        raise ValueError("FFT size must be a power of two")
    data = [complex(value) for value in values]
    levels = size.bit_length() - 1
    for index in range(size):
        swapped = int(format(index, f"0{levels}b")[::-1], 2) if levels else 0
        if swapped > index:
            data[index], data[swapped] = data[swapped], data[index]
    length = 2
    while length <= size:
        angle = -2 * math.pi / length
        half = length // 2
        twiddle_step = cmath.exp(1j * angle)
        for start in range(0, size, length):
            twiddle = 1.0 + 0j
            for offset in range(half):
                even = data[start + offset]
                odd = data[start + offset + half] * twiddle
                data[start + offset] = even + odd
                data[start + offset + half] = even - odd
                twiddle *= twiddle_step
        length <<= 1
    return data
