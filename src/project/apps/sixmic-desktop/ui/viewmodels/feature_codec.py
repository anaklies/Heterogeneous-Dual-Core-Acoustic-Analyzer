"""Generic echo-features-1 result decoder (protocol/display only, no DSP)."""
from __future__ import annotations

import struct
from typing import Any


def _u32_words(raw: bytes) -> list[int]:
    raw = raw[: len(raw) // 4 * 4]
    return list(struct.unpack("<" + "I" * (len(raw) // 4), raw))


def _f32(word: int) -> float:
    return struct.unpack("<f", struct.pack("<I", word & 0xFFFFFFFF))[0]


def _pcm24(word: int) -> int:
    value = word & 0xFFFFFF
    return value - 0x1000000 if value & 0x800000 else value


def _field_words(words: list[int], spec: Any) -> list[int]:
    if isinstance(spec, int):
        return words[spec:spec + 1]
    if not isinstance(spec, dict):
        return []
    offset = int(spec.get("offset", spec.get("wordOffset", 0)) or 0)
    count = int(spec.get("count", spec.get("words", 1)) or 1)
    stride = int(spec.get("stride", 1) or 1)
    return [words[offset + i * stride] for i in range(count) if offset + i * stride < len(words)]


def _render_axes(schema: dict[str, Any], meta: Any) -> dict[str, Any]:
    axes = dict(schema.get("axes") or {})
    if isinstance(meta, dict):
        if "centers_hz" in meta:
            axes["centersHz"] = list(meta["centers_hz"])
        if "bins" in meta:
            axes["bins"] = meta["bins"]
        if "frame_count" in meta:
            axes["frameCount"] = meta["frame_count"]
    return axes


def decode_feature_result(payload: dict[str, Any], raw_bytes: bytes) -> dict[str, Any]:
    """Decode raw uint32 words using server schema/layout only.

    The server layout is authoritative: actualProducerLayout > producerLayout >
    schema.layout. If none can be interpreted, return an explicit unavailable
    result with raw words preserved; never guess a hardware layout or apply DSP.
    """
    words = _u32_words(raw_bytes)
    schema = dict(payload.get("schema") or {})
    layout = (schema.get("actualProducerLayout") or schema.get("producerLayout")
              or schema.get("layout") or payload.get("layout") or {})
    meta = payload.get("schemaMeta") or (schema.get("metadata") if isinstance(schema.get("metadata"), dict) else {})
    kind = str(schema.get("kind") or "")
    encoding = str(layout.get("encoding") or schema.get("encoding") or "uint32")
    is_float = "float32" in encoding.lower()
    axes = _render_axes(schema, meta)
    base = {"available": True, "kind": kind or "tensor", "words": words[:4096],
            "totalWords": len(words), "axes": axes,
            "units": str(schema.get("units") or ""),
            "validity": str(schema.get("validity") or ""),
            "fields": schema.get("fields"), "render": "raw"}
    if kind == "capability":
        base.update({"render": "capability", "available": True,
                     "message": str((meta or {}).get("capability") or "interface/capability only")})
        return base
    if kind == "waveform" or any("PCM24" in str(f) for f in (schema.get("fields") or [])):
        channels = int((axes or {}).get("channels") or 1)
        words2 = words
        values = [_pcm24(w) for w in words2]
        chans = []
        if 1 < channels <= 6:
            for ch in range(channels):
                chans.append([float(v) for v in values[ch::channels]][:8192])
        else:
            chans = [[float(v) for v in values][:8192]]
        return {**base, "render": "waveform", "channels": chans,
                "sampleRateHz": float((meta or {}).get("sampleRateHz") or 0.0)}
    fields = layout.get("fields") if isinstance(layout, dict) else None
    if not fields:
        base.update({"available": False, "reason": "missing-producer-layout",
                     "render": "raw"})
        return base
    # field map (offset per scalar)
    if isinstance(fields, dict) and all(
            isinstance(v, int) or (isinstance(v, dict) and ("offset" in v or "wordOffset" in v)
                                    and "count" not in v and "fields" not in v)
            for v in fields.values()):
        scalars = {}
        for name, spec in fields.items():
            if isinstance(spec, int):
                offset, ftype = spec, ("float32" if is_float else "uint32")
            else:
                offset = int(spec.get("offset", spec.get("wordOffset", 0)) or 0)
                ftype = str(spec.get("type") or ("float32" if is_float else "uint32"))
            if offset < len(words):
                scalars[name] = _f32(words[offset]) if "float32" in ftype.lower() else words[offset]
        base.update({"render": "scalars", "scalars": scalars,
                     "fields": list(fields.keys())})
        return base
    # triplet/explicit tensor layouts
    series = []
    if isinstance(fields, dict):
        triplet = fields.get("triplets")
        if isinstance(triplet, dict):
            offset = int(triplet.get("offset", 0) or 0)
            count = int(triplet.get("count", 0) or 0)
            names = list(triplet.get("fields") or [])
            for idx, fname in enumerate(names):
                vals = [words[offset + i * len(names) + idx]
                        for i in range(count) if offset + i * len(names) + idx < len(words)]
                xs = axes.get("centersHz") or list(range(len(vals)))
                if axes.get("centersHz") and len(xs) == len(vals):
                    pts = [[float(x), float(v)] for x, v in zip(xs, vals)]
                else:
                    pts = [[float(i), (float(_f32(v)) if is_float else float(v))]
                           for i, v in enumerate(vals)]
                series.append({"name": fname, "points": pts[:4096]})
        for name, spec in fields.items():
            if name == "triplets":
                continue
            if isinstance(spec, dict) and "count" in spec and int(spec.get("count", 0)) > 1:
                vals = [words[int(spec.get("offset", 0)) + i] for i in range(int(spec["count"]))
                        if int(spec.get("offset", 0)) + i < len(words)]
                xs = axes.get("centersHz") or list(range(len(vals)))
                series.append({"name": name, "points": [[float(x), float(v)] for x, v in zip(xs, vals)][:4096]})
    if series:
        return {**base, "render": "line", "series": series,
                "xLabel": str((axes or {}).get("frequencyHz") or ""),
                "yLabel": base["units"]}
    # list of fields + axes count
    names = fields if isinstance(fields, list) else []
    if names:
        count = int((axes or {}).get("count") or (layout.get("count") if isinstance(layout, dict) else 0) or 0)
        if count <= 0:
            count = max(1, len(words) // max(1, len(names)))
        n = min(count, len(words) // max(1, len(names)))
        for idx, name in enumerate(names):
            vals = [words[i * len(names) + idx] for i in range(n)]
            if is_float:
                vals = [_f32(v) for v in vals]
            xs = axes.get("centersHz") or list(range(n))
            series.append({"name": name, "points": [[float(x), float(v)] for x, v in zip(xs, vals)][:4096]})
        return {**base, "render": "line", "series": series}
    base.update({"available": False, "reason": "unsupported-producer-layout", "render": "raw"})
    return base
