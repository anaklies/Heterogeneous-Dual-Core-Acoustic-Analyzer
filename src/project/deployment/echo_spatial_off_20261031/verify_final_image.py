"""Independent offline verification of the FINAL gateway-45 image.ub (Lead repack).

Compares deployment/echo_spatial_off_20261031/image.ub (sha 646631ab...) against the
original board source image (cba07779...) and proves exactly two ramdisk entries
changed: opt/echo/registry/INTERFACE_REGISTRY.json and opt/echo/bin/echo-gateway.
"""
from pathlib import Path
import gzip, hashlib, json, time

from image_patch_lib import (EXPECTED_FEATURE_IDS, REMOVED_FEATURE_IDS, fit_parts,
                             read_ramdisk, entry_bytes, non_data_props, hash_children,
                             fdt_header, unique_offset, differing_runs, sha)

R = Path(__file__).resolve().parent
PROJECT = R.parents[1]
SOURCE = PROJECT / 'deployment/echo_stipa_8s_progress_20261030/image.ub'
SOURCE_SHA = 'cba07779ad32643380a96462569dabb4f4f4b2ec62bc9476a8dd4caa1fbc4902'
FINAL = R / 'image.ub'
FINAL_SHA = '646631abdd1add91b96ea28d2553eafeac647c42267386e03fddaf17613b6565'
REGISTRY = R / 'registry/INTERFACE_REGISTRY.json'
REGISTRY_SHA = 'dcbc393723513773867f6a9d96f396eb22b13386060881fdae06dda4ecb77628'
GATEWAY = R / 'echo-gateway'
GATEWAY_SHA = '5d4b0291146f71fd0f5e39ef11d326cb49e723fe6e43763a0fffaa4e370ecc44'
OLD_GATEWAY_SHA = 'b982cecea0e9da4bf3a73dc7855d2ba41be7d22322f7a0221d8e0b07ef928920'
CHANGED = ['opt/echo/registry/INTERFACE_REGISTRY.json', 'opt/echo/bin/echo-gateway']


def main():
    source, final = SOURCE.read_bytes(), FINAL.read_bytes()
    registry = REGISTRY.read_bytes()
    gateway = GATEWAY.read_bytes()
    checks = []

    def check(name, ok, detail=None):
        row = {'check': name, 'pass': bool(ok)}
        if detail is not None:
            row['detail'] = detail
        checks.append(row)
        return row['pass']

    def require(name, ok, detail=None):
        if not check(name, ok, detail):
            raise AssertionError('check failed: ' + name)

    try:
        require('source.sha256', sha(source) == SOURCE_SHA, sha(source))
        require('final.sha256', sha(final) == FINAL_SHA, sha(final))
        require('final.bytes', len(final) == 166612952, len(final))
        require('registry.sha256', sha(registry) == REGISTRY_SHA)
        require('gateway.sha256', sha(gateway) == GATEWAY_SHA)
        from firmware_formats_20261012 import read_fdt, write_fdt
        require('fdt.roundtrip.final', write_fdt(*read_fdt(final)) == final)

        src, fin = fit_parts(source), fit_parts(final)
        src_ram, fin_ram = read_ramdisk(src), read_ramdisk(fin)
        src_entries, fin_entries = src_ram['entries'], fin_ram['entries']
        require('fit.images.same', [n.name for n in src['images'].children]
                == [n.name for n in fin['images'].children])
        for node_type, label in ((b'kernel', 'kernel'), (b'flat_dt', 'dtb')):
            s = next(n for n in src['others']
                     if n.properties.get('type', b'').rstrip(b'\x00') == node_type)
            f = next(n for n in fin['others']
                     if n.properties.get('type', b'').rstrip(b'\x00') == node_type)
            require(label + '.data.unchanged', sha(s.properties['data']) == sha(f.properties['data']))
            require(label + '.props.unchanged', non_data_props(s) == non_data_props(f))
            require(label + '.hash.unchanged', hash_children(s) == hash_children(f))
        require('fit.root.unchanged', non_data_props(src['tree']) == non_data_props(fin['tree']))
        require('fit.configs.unchanged',
                {c.name: non_data_props(c) for c in src['tree'].child('configurations').children}
                == {c.name: non_data_props(c) for c in fin['tree'].child('configurations').children})

        require('ramdisk.entries.count', len(src_entries) == len(fin_entries) == 2840,
                {'source': len(src_entries), 'final': len(fin_entries)})
        require('ramdisk.entries.order', list(src_entries) == list(fin_entries))
        unchanged = [n for n in src_entries if n not in CHANGED]
        identical = all(entry_bytes(n, src_entries[n]) == entry_bytes(n, fin_entries[n])
                        for n in unchanged)
        require('ramdisk.entries.other.bytes.identical', identical,
                {'changedEntries': CHANGED, 'unchangedEntries': len(unchanged)})
        require('ramdisk.registry.data', fin_entries[CHANGED[0]]['data'] == registry)
        require('ramdisk.registry.mode',
                fin_entries[CHANGED[0]]['fields'][1] == src_entries[CHANGED[0]]['fields'][1])
        require('ramdisk.registry.only.size.changed',
                [i for i in range(13)
                 if src_entries[CHANGED[0]]['fields'][i] != fin_entries[CHANGED[0]]['fields'][i]] == [6])
        require('ramdisk.gateway.data', fin_entries[CHANGED[1]]['data'] == gateway)
        require('ramdisk.gateway.mode',
                fin_entries[CHANGED[1]]['fields'][1] == 0o100755)
        require('ramdisk.gateway.fields.identical',
                src_entries[CHANGED[1]]['fields'] == fin_entries[CHANGED[1]]['fields'],
                {'oldBytes': len(src_entries[CHANGED[1]]['data']),
                 'newBytes': len(fin_entries[CHANGED[1]]['data'])})
        old_gateway = src_entries[CHANGED[1]]['data']
        require('ramdisk.gateway.old.sha', sha(old_gateway) == OLD_GATEWAY_SHA)

        hashes = hash_children(fin['ramdisk'])
        algo = hashes['hash-1']['algo'].rstrip(b'\x00').decode()
        require('ramdisk.hash.correct',
                hashes['hash-1']['value'] == hashlib.new(
                    algo, fin['ramdisk'].properties['data']).digest())

        registry_json = json.loads(registry.decode('utf-8'))
        ids = [f['featureId'] for f in registry_json['features']]
        raw = registry.decode('utf-8')
        require('registry.feature.count', len(ids) == 45, len(ids))
        require('registry.feature.ids', ids == EXPECTED_FEATURE_IDS)
        require('registry.spatial.ids.absent',
                all(fid not in raw for fid in REMOVED_FEATURE_IDS), REMOVED_FEATURE_IDS)
        require('registry.featureId.lines',
                sum(1 for line in raw.splitlines() if '"featureId":' in line) == 45)

        src_header, fin_header = fdt_header(source), fdt_header(final)
        names = ['magic', 'totalsize', 'off_dt_struct', 'off_dt_strings', 'off_mem_rsvmap',
                 'version', 'last_comp_version', 'boot_cpuid_phys', 'size_dt_strings',
                 'size_dt_struct']
        changed_fields = [names[i] for i in range(10) if src_header[i] != fin_header[i]]
        require('fdt.header.changed.fields',
                changed_fields == ['totalsize', 'off_dt_strings', 'size_dt_struct'],
                changed_fields)
        src_off = unique_offset(source, src_ram['compressed'], 'source ramdisk data')
        fin_off = unique_offset(final, fin_ram['compressed'], 'final ramdisk data')
        require('fdt.ramdisk.data.offset.identical', src_off == fin_off,
                {'source': src_off, 'final': fin_off})
        require('fdt.prefix.bytes.identical', source[40:src_off - 8] == final[40:fin_off - 8])
        src_pad = (-len(src_ram['compressed'])) % 4
        fin_pad = (-len(fin_ram['compressed'])) % 4
        src_tail = source[src_off + len(src_ram['compressed']) + src_pad:]
        fin_tail = final[fin_off + len(fin_ram['compressed']) + fin_pad:]
        require('fdt.tail.length.identical', len(src_tail) == len(fin_tail),
                {'source': len(src_tail), 'final': len(fin_tail)})
        differing = [index for index, (left, right) in enumerate(zip(src_tail, fin_tail))
                     if left != right]
        hash_value = hashes['hash-1']['value']
        hash_off = unique_offset(fin_tail, hash_value, 'final ramdisk hash value')
        hash_range = set(range(hash_off, hash_off + len(hash_value)))
        require('fdt.tail.only.ramdisk.hash.differs',
                differing
                and set(differing) <= hash_range
                and min(differing) == hash_off
                and max(differing) == hash_off + len(hash_value) - 1,
                {'differingBytes': len(differing), 'hashOffset': hash_off,
                 'hashBytes': len(hash_value), 'allInsideHash': set(differing) <= hash_range,
                 'sourceTailBytes': len(src_tail), 'finalTailBytes': len(fin_tail)})
        summary = {
            'verificationStatus': 'PASS',
            'source': {'sha256': sha(source), 'bytes': len(source)},
            'final': {'sha256': sha(final), 'bytes': len(final)},
            'changedRamdiskEntries': CHANGED,
            'ramdiskEntries': len(src_entries),
            'unchangedRamdiskEntries': len(unchanged),
            'registry': {'sha256': sha(registry), 'bytes': len(registry), 'features': len(ids)},
            'gateway': {'sha256': sha(gateway), 'bytes': len(gateway),
                        'previousSHA256': OLD_GATEWAY_SHA, 'changed': True},
            'kernelAndDTBUnchanged': True,
            'byteIdenticalOutsidePatch': True,
            'proof': ('Only the ramdisk data (containing the 45-feature registry and the rebuilt '
                      '45-feature gateway), its FDT length/padding, the ramdisk sha256 and the '
                      'three FDT length fields differ; kernel, dtb and all 2838 other ramdisk '
                      'cpio entries are byte-identical to the original board image.'),
            'verifiedAt': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        }
    except AssertionError as error:
        summary = {'verificationStatus': 'FAIL', 'error': str(error)}
    report = {'report': 'FINAL_IMAGE_VERIFY.json', 'status': summary.get('verificationStatus', 'FAIL'),
              'summary': summary, 'checks': checks}
    (R / 'FINAL_IMAGE_VERIFY.json').write_text(
        json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'],
                      'finalSHA256': summary.get('final', {}).get('sha256'),
                      'checks': len(checks),
                      'failed': sum(1 for c in checks if not c['pass']),
                      'error': summary.get('error')}, indent=2))
    if report['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
