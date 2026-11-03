
import json, struct
from pathlib import Path
APP = Path(r"C:\Users\sunxi\Desktop\sixmic3D\apps\sixmic-desktop")
OUT = APP/"docs/frontend/screenshots/final_verified"
batches = []
for path in sorted(OUT.glob("capture_manifest_*.json")):
    data = json.loads(path.read_text(encoding="utf-8"))
    batches.append(data)
def png_size(path):
    raw = path.read_bytes()[:32]
    if raw[:8] != b"\x89PNG\r\n\x1a\n": return (0,0)
    w, h = struct.unpack(">II", raw[16:24]); return (int(w), int(h))
shots = []
for data in batches:
    for shot in data.get("shots") or []:
        p = OUT / shot["file"]
        w, h = png_size(p) if p.is_file() else (0,0)
        shot = dict(shot); shot["pngWidth"], shot["pngHeight"] = w, h
        shot["pngOk"] = (w == shot["width"] and h == shot["height"])
        shot["batch"] = data.get("batch")
        shots.append(shot)
manifest = {
    "generatedAt": batches[-1].get("generatedAt") if batches else "",
    "method": "real offscreen GUI + host test-feature-server (TCP 48120, sourceKind=test-fixture)",
    "authoritative": True,
    "hardwareState": "NOT_TESTED", "numericDSPVerified": False,
    "assertionsPerShot": ["connectionState=connected", "workspaceState completed (or running for monitor/stipa progress)",
                          "sourceKind=test-fixture", "chart payload present", "PNG dimensions verified"],
    "batchManifests": [p.name for p in sorted(OUT.glob("capture_manifest_*.json"))],
    "totals": {"shots": len(shots), "pngOk": sum(1 for s in shots if s["pngOk"]),
               "failedAssertions": sum(len(b.get("failures") or []) for b in batches)},
    "notes": ["All shots are test-fixture; never pl-live; NOT board/acoustic evidence.",
              "64/64? see totals; DPI variants captured at logical 1920x1080 with QT_SCALE_FACTOR 1.5/2.0 (framebuffer 2880x1620/3840x2160)."],
    "shots": shots,
}
(OUT/"CAPTURE_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({k: manifest[k] for k in ("totals", "batchManifests")}, ensure_ascii=False, indent=1))
bad = [s["file"] for s in shots if not s["pngOk"]]
print("bad png:", bad[:5])
