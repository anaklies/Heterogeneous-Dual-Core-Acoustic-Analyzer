"""Patch the current SD image.ub with the new STIPA quick registry + gateway binary.

Source: deployment/echo_measurement_stability_20261030/image.ub (sha256 dadfc4f8...,
the image currently on /mnt/echo-sd). Only the ramdisk cpio entries
opt/echo/registry/** and opt/echo/bin/echo-gateway are replaced; kernel, dtb,
bootloader and every other entry are preserved bit-for-bit and proven unchanged.
"""
from pathlib import Path
import gzip, hashlib, json, struct, sys, zlib

R = Path(__file__).resolve().parent
ROOT = R.parents[1]
sys.path.insert(0, str(ROOT / 'deployment'))
from firmware_formats_20261012 import read_fdt, write_fdt, read_cpio, write_cpio

SOURCE = ROOT / 'deployment/echo_measurement_stability_20261030/image.ub'
SOURCE_SHA = 'dadfc4f8d8915388548c7b960b03ef48822cf7e4755fbbfa02fcab11e81955aa'
REG = R / 'registry'
GATEWAY = R / 'gateway/echo-gateway'
OUT = R / 'image.ub'


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    source = SOURCE.read_bytes()
    assert sha(source) == SOURCE_SHA, ('source image is not the current SD image', sha(source))
    tree, reserves, cpu = read_fdt(source)
    images = tree.child('images')
    ram = next(n for n in images.children if n.properties.get('type') == b'ramdisk\0')
    entries = read_cpio(gzip.decompress(ram.properties['data']))
    other_images = {n.name: sha(n.properties.get('data', b'')) for n in images.children if n is not ram}
    other_entries = {k: sha(v['data']) for k, v in entries.items()
                     if not k.startswith('opt/echo/registry/')
                     and k != 'opt/echo/bin/echo-gateway'}
    # Replace the registry (same layout as the board /opt/echo mount).
    changed = 0
    for p in REG.rglob('*'):
        if not p.is_file():
            continue
        name = 'opt/echo/registry/' + p.relative_to(REG).as_posix()
        entries[name] = {'fields': [0, 0o100644, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0],
                         'data': p.read_bytes()}
        changed += 1
    # Replace the gateway binary (supervisor restarts it after deployment).
    gw = GATEWAY.read_bytes()
    assert gw[:5] == b'\x7fELF\x01', 'gateway is not an ARM ELF'
    assert 'opt/echo/bin/echo-gateway' in entries, 'ramdisk does not contain echo-gateway'
    entries['opt/echo/bin/echo-gateway'] = {
        'fields': [0, 0o100755, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0], 'data': gw}
    ram.properties['data'] = gzip.compress(write_cpio(entries), compresslevel=6, mtime=0)
    for n in images.children:
        if 'data' in n.properties:
            for h in n.children:
                if h.name.startswith('hash'):
                    algo = h.properties['algo'].rstrip(b'\0').decode()
                    body = n.properties['data']
                    if algo == 'crc32':
                        h.properties['value'] = struct.pack('>I', zlib.crc32(body))
                    else:
                        h.properties['value'] = hashlib.new(algo, body).digest()
    output = write_fdt(tree, reserves, cpu)
    # Prove nothing except the ramdisk changed.
    tree2, _, _ = read_fdt(output)
    images2 = tree2.child('images')
    assert other_images == {n.name: sha(n.properties.get('data', b''))
                            for n in images2.children
                            if n.properties.get('type') != b'ramdisk\0'}, 'non-ramdisk image changed'
    ram2 = next(n for n in images2.children if n.properties.get('type', b'').rstrip(b'\0') == b'ramdisk')
    entries2 = read_cpio(gzip.decompress(ram2.properties['data']))
    assert other_entries == {k: sha(v['data']) for k, v in entries2.items()
                             if not k.startswith('opt/echo/registry/')
                             and k != 'opt/echo/bin/echo-gateway'}, 'unrelated cpio entries changed'
    # Prove the new registry and gateway inside the ramdisk equal the delivered files.
    for p in REG.rglob('*'):
        if p.is_file():
            name = 'opt/echo/registry/' + p.relative_to(REG).as_posix()
            assert entries2[name]['data'] == p.read_bytes(), name
    assert entries2['opt/echo/bin/echo-gateway']['data'] == gw
    assert entries2['opt/echo/bin/echo-gateway']['data'] == gw
    assert entries2['opt/echo/registry/INTERFACE_REGISTRY.json']['data'] == \
        (REG / 'INTERFACE_REGISTRY.json').read_bytes()
    OUT.write_bytes(output)
    report = {
        'source': str(SOURCE), 'sourceSHA256': sha(source),
        'imageSHA256': sha(output), 'bytes': len(output),
        'registryFiles': changed,
        'gatewaySHA256': sha(gw), 'gatewayBytes': len(gw),
        'kernelAndDTBUnchanged': True, 'bitstreamChanged': False,
    }
    (R / 'SD_PATCH.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
