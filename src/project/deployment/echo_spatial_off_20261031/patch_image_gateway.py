
"""Patch current 45-feature image.ub with the rebuilt 45-feature ARM gateway.
Source: deployment/echo_spatial_off_20261031/image.ub (sha 00b93b14..., already 45 registry)
Only cpio entries opt/echo/registry/INTERFACE_REGISTRY.json and opt/echo/bin/echo-gateway change.
"""
from pathlib import Path
import gzip, hashlib, json, struct, sys, zlib
ROOT = Path(r"C:\Users\sunxi\Desktop\sixmic3D")
sys.path.insert(0, str(ROOT / "deployment"))
from firmware_formats_20261012 import read_fdt, write_fdt, read_cpio, write_cpio
R = ROOT / "deployment/echo_spatial_off_20261031"
SOURCE = R / "image.ub"
SOURCE_SHA = "00b93b142f81d6db5da50eeb8b35a6e2405cbc82fa1d542ae147d7d64dcfe238"
REG = R / "registry"
GATEWAY = ROOT / "deployment/echo_interface_guard_20261026/build/arm/echo-gateway"
OUT = R / "image.ub"
def sha(b): return hashlib.sha256(b).hexdigest()
source = SOURCE.read_bytes()
assert sha(source) == SOURCE_SHA, ("source mismatch", sha(source))
if not (R/"image.ub.before-gateway-fix-20261031").exists():
    (R/"image.ub.before-gateway-fix-20261031").write_bytes(source)
tree, reserves, cpu = read_fdt(source)
images = tree.child("images")
ram = next(n for n in images.children if (n.properties.get("type") or b"").rstrip(b"\0") == b"ramdisk")
entries = read_cpio(gzip.decompress(ram.properties["data"]))
other_images = {n.name: sha(n.properties.get("data", b"")) for n in images.children if n is not ram}
other_entries = {k: sha(v["data"]) for k, v in entries.items()
                 if not k.startswith("opt/echo/registry/") and k != "opt/echo/bin/echo-gateway"}
for p in sorted(REG.rglob("*")):
    if p.is_file():
        name = "opt/echo/registry/" + p.relative_to(REG).as_posix()
        entries[name] = {"fields": [0, 0o100644, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0], "data": p.read_bytes()}
gw = GATEWAY.read_bytes()
assert gw[:5] == b"\x7fELF\x01", "gateway is not ARM ELF"
assert "opt/echo/bin/echo-gateway" in entries
entries["opt/echo/bin/echo-gateway"] = {"fields": [0, 0o100755, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0], "data": gw}
ram.properties["data"] = gzip.compress(write_cpio(entries), compresslevel=6, mtime=0)
for n in images.children:
    if "data" in n.properties:
        for h in n.children:
            if h.name.startswith("hash"):
                algo = h.properties["algo"].rstrip(b"\0").decode()
                body = n.properties["data"]
                if algo == "crc32": h.properties["value"] = struct.pack(">I", zlib.crc32(body))
                else: h.properties["value"] = hashlib.new(algo, body).digest()
output = write_fdt(tree, reserves, cpu)
tree2, _, _ = read_fdt(output); images2 = tree2.child("images")
assert other_images == {n.name: sha(n.properties.get("data", b"")) for n in images2.children if n.name != ram.name}
ram2 = next(n for n in images2.children if (n.properties.get("type") or b"").rstrip(b"\0") == b"ramdisk")
entries2 = read_cpio(gzip.decompress(ram2.properties["data"]))
assert other_entries == {k: sha(v["data"]) for k, v in entries2.items() if not k.startswith("opt/echo/registry/") and k != "opt/echo/bin/echo-gateway"}
assert entries2["opt/echo/bin/echo-gateway"]["data"] == gw
OUT.write_bytes(output)
report = {"sourceSHA256": sha(source), "imageSHA256": sha(output), "bytes": len(output),
          "gatewaySHA256": sha(gw), "gatewayBytes": len(gw), "registryEntries": sum(1 for p in REG.rglob("*") if p.is_file()),
          "changedEntries": ["opt/echo/registry/INTERFACE_REGISTRY.json","opt/echo/bin/echo-gateway"],
          "kernelAndDTBUnchanged": True, "otherCpioEntriesUnchanged": True}
(R/"SD_PATCH_GATEWAY.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
print(json.dumps(report, indent=2))
