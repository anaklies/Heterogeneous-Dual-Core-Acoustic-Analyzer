"""Shared FIT/cpio helpers for the 20261031 spatial-off image.ub patch and verification.

Only one ramdisk entry (opt/echo/registry/INTERFACE_REGISTRY.json) may change.
The helpers prove the rest of the FIT image (kernel, dtb, other ramdisk cpio
entries, FIT metadata) is byte-identical between source and patched image.
"""
from pathlib import Path
import gzip, hashlib, struct, sys

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / 'deployment'))
from firmware_formats_20261012 import read_fdt, write_fdt, read_cpio, write_cpio

TARGET_ENTRY = 'opt/echo/registry/INTERFACE_REGISTRY.json'
FDT_HEADER_FIELDS = [
    'magic', 'totalsize', 'off_dt_struct', 'off_dt_strings', 'off_mem_rsvmap',
    'version', 'last_comp_version', 'boot_cpuid_phys', 'size_dt_strings', 'size_dt_struct',
]
# Canonical 45-feature list after removing the six spatial features (Lead-owned registry).
EXPECTED_FEATURE_IDS = [
    'io_pcm', 'levels_core', 'data_continuity', 'fft', 'psd', 'stft',
    'spectrum_average', 'signal_quality', 'levels_extended', 'octave',
    'third_octave', 'peak_hold', 'smoothing', 'frequency_tracking',
    'frequency_drift', 'csd', 'coherence_phase', 'energy_change',
    'band_tracking', 'centroid', 'flatness', 'event_trigger',
    'frequency_time_weighting', 'level_statistics', 'zoom_fft', 'fundamental',
    'harmonic_ratio', 'sidebands', 'envelope_hilbert', 'envelope_spectrum',
    'modulation_spectrum', 'autocorrelation', 'cross_correlation', 'gcc_phat',
    'spectral_flux', 'spectrum_freeze', 'relative_limit', 'cepstrum',
    'spectral_kurtosis', 'room_decay', 'relative_insulation', 'stipa_experimental',
    'noise_rating', 'room_clarity', 'spectral_decay',
]
REMOVED_FEATURE_IDS = [
    'spatial_interface', 'directed_das', 'full_das', 'band_das',
    'spatial_grid', 'spatial_peaks',
]


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def entry_bytes(name, item):
    """Serialize one newc entry exactly the way write_cpio() does."""
    fields = list(item['fields'])
    encoded = name.encode() + b'\x00'
    data = item['data']
    fields[6] = len(data)
    fields[11] = len(encoded)
    fields[12] = 0
    out = bytearray(b'070701' + ''.join(f'{value:08x}' for value in fields).encode())
    out.extend(encoded)
    out.extend(bytes((-len(out)) % 4))
    out.extend(data)
    out.extend(bytes((-len(out)) % 4))
    return bytes(out)


def fit_parts(blob):
    tree, reserves, bootcpu = read_fdt(blob)
    images = tree.child('images')
    if images is None:
        raise ValueError('FIT image has no images node')
    ramdisks = [node for node in images.children
                if node.properties.get('type', b'').rstrip(b'\x00') == b'ramdisk']
    if len(ramdisks) != 1:
        raise ValueError('expected exactly one ramdisk image')
    ram = ramdisks[0]
    others = [node for node in images.children if node is not ram]
    return {'tree': tree, 'reserves': reserves, 'bootcpu': bootcpu,
            'images': images, 'ramdisk': ram, 'others': others}


def read_ramdisk(part):
    compressed = part['ramdisk'].properties['data']
    cpio = gzip.decompress(compressed)
    entries = read_cpio(cpio)
    if write_cpio(entries) != cpio:
        raise ValueError('cpio read/write round-trip is not byte-identical')
    return {'compressed': compressed, 'cpio': cpio, 'entries': entries}


def non_data_props(node):
    return {name: value for name, value in node.properties.items() if name != 'data'}


def hash_children(node):
    return {child.name: dict(child.properties) for child in node.children
            if child.name.startswith('hash')}


def fdt_header(blob):
    return list(struct.unpack_from('>10I', blob))


def unique_offset(blob, needle, label):
    offset = blob.find(needle)
    if offset < 0:
        raise ValueError(label + ' not found')
    if blob.find(needle, offset + 1) >= 0:
        raise ValueError(label + ' is not unique')
    return offset


def differing_runs(left, right):
    if len(left) != len(right):
        raise ValueError('inputs have different lengths')
    runs, start = [], None
    for index in range(len(left)):
        if left[index] != right[index]:
            if start is None:
                start = index
        elif start is not None:
            runs.append([start, index])
            start = None
    if start is not None:
        runs.append([start, len(left)])
    return runs


def recompute_hash_nodes(images):
    for node in images.children:
        if 'data' not in node.properties:
            continue
        for child in node.children:
            if not child.name.startswith('hash'):
                continue
            algo = child.properties['algo'].rstrip(b'\x00').decode()
            body = node.properties['data']
            if algo == 'crc32':
                import zlib
                child.properties['value'] = struct.pack('>I', zlib.crc32(body))
            else:
                child.properties['value'] = hashlib.new(algo, body).digest()


def build_patched_image(source, new_registry, expected_source_sha,
                        expected_old_registry_sha=None):
    """Return (patched image bytes, build report); only TARGET_ENTRY changes."""
    source = bytes(source)
    new_registry = bytes(new_registry)
    if sha(source) != expected_source_sha:
        raise ValueError('source image sha256 mismatch: ' + sha(source))
    if write_fdt(*read_fdt(source)) != source:
        raise ValueError('source FDT does not round-trip byte-identically')
    parts = fit_parts(source)
    ramdisk = read_ramdisk(parts)
    entries = ramdisk['entries']
    if TARGET_ENTRY not in entries:
        raise ValueError('source ramdisk has no ' + TARGET_ENTRY)
    old_registry = entries[TARGET_ENTRY]['data']
    if expected_old_registry_sha and sha(old_registry) != expected_old_registry_sha:
        raise ValueError('embedded registry is not the expected current one')
    kernel = next(node for node in parts['others']
                  if node.properties.get('type', b'').rstrip(b'\x00') == b'kernel')
    dtb = next(node for node in parts['others']
               if node.properties.get('type', b'').rstrip(b'\x00') == b'flat_dt')
    kernel_sha, dtb_sha = sha(kernel.properties['data']), sha(dtb.properties['data'])
    new_entries = {}
    for name, item in entries.items():
        if name == TARGET_ENTRY:
            new_entries[name] = {'fields': list(item['fields']), 'data': new_registry}
        else:
            new_entries[name] = item
    new_cpio = write_cpio(new_entries)
    new_compressed = gzip.compress(new_cpio, compresslevel=6, mtime=0)
    parts['ramdisk'].properties['data'] = new_compressed
    recompute_hash_nodes(parts['images'])
    output = write_fdt(parts['tree'], parts['reserves'], parts['bootcpu'])
    report = {
        'sourceSHA256': sha(source), 'sourceBytes': len(source),
        'imageSHA256': sha(output), 'bytes': len(output),
        'oldRegistrySHA256': sha(old_registry), 'oldRegistryBytes': len(old_registry),
        'newRegistrySHA256': sha(new_registry), 'newRegistryBytes': len(new_registry),
        'kernelSHA256': kernel_sha, 'dtbSHA256': dtb_sha,
        'ramdiskEntries': len(entries), 'changedEntries': [TARGET_ENTRY],
        'sourceRamdiskCompressedBytes': len(ramdisk['compressed']),
        'outputRamdiskCompressedBytes': len(new_compressed),
        'sourceCpioBytes': len(ramdisk['cpio']), 'outputCpioBytes': len(new_cpio),
    }
    return output, report


class _Checks:
    def __init__(self):
        self.checks = []

    def add(self, name, ok, detail=None):
        entry = {'check': name, 'pass': bool(ok)}
        if detail is not None:
            entry['detail'] = detail
        self.checks.append(entry)
        return entry['pass']

    def require(self, name, ok, detail=None):
        if not self.add(name, ok, detail):
            raise AssertionError('check failed: ' + name)


def verify_patch(source, output, new_registry, expected_source_sha=None,
                 expected_output_sha=None, expected_old_registry_sha=None,
                 expected_new_registry_sha=None):
    """Independently verify a patched image against its source; return report dict."""
    source = bytes(source)
    output = bytes(output)
    new_registry = bytes(new_registry)
    checks = _Checks()
    summary = {}
    try:
        if expected_source_sha is not None:
            checks.require('source.sha256', sha(source) == expected_source_sha,
                           {'expected': expected_source_sha, 'actual': sha(source)})
        if expected_output_sha is not None:
            checks.require('output.sha256', sha(output) == expected_output_sha,
                           {'expected': expected_output_sha, 'actual': sha(output)})
        checks.add('source.bytes', len(source) > 0, len(source))
        checks.add('output.bytes', len(output) > 0, len(output))

        checks.require('fdt.source.roundtrip', write_fdt(*read_fdt(source)) == source)
        checks.require('fdt.output.roundtrip', write_fdt(*read_fdt(output)) == output)

        src = fit_parts(source)
        out = fit_parts(output)
        src_ramdisk = read_ramdisk(src)
        out_ramdisk = read_ramdisk(out)
        src_entries, out_entries = src_ramdisk['entries'], out_ramdisk['entries']

        src_names = [node.name for node in src['images'].children]
        out_names = [node.name for node in out['images'].children]
        checks.require('fit.images.names', src_names == out_names,
                       {'source': src_names, 'output': out_names})
        checks.require('fit.ramdisk.name', src['ramdisk'].name == out['ramdisk'].name,
                       {'source': src['ramdisk'].name, 'output': out['ramdisk'].name})
        checks.require('fit.configs.unchanged',
                       {c.name: non_data_props(c) for c in src['tree'].child('configurations').children}
                       == {c.name: non_data_props(c) for c in out['tree'].child('configurations').children})
        checks.require('fit.root.props.unchanged',
                       non_data_props(src['tree']) == non_data_props(out['tree']))

        def compare_other(node_type):
            src_node = next(n for n in src['others']
                            if n.properties.get('type', b'').rstrip(b'\x00') == node_type)
            out_node = next(n for n in out['others']
                            if n.properties.get('type', b'').rstrip(b'\x00') == node_type)
            return src_node, out_node

        for node_type, label in ((b'kernel', 'kernel'), (b'flat_dt', 'dtb')):
            src_node, out_node = compare_other(node_type)
            checks.require(label + '.data.unchanged',
                           sha(src_node.properties['data']) == sha(out_node.properties['data']),
                           {'sha256': sha(src_node.properties['data'])})
            checks.require(label + '.props.unchanged',
                           non_data_props(src_node) == non_data_props(out_node))
            checks.require(label + '.hash.unchanged',
                           hash_children(src_node) == hash_children(out_node))
            checks.add(label + '.sha256', True, sha(src_node.properties['data']))

        checks.require('ramdisk.entries.count', len(src_entries) == len(out_entries),
                       {'source': len(src_entries), 'output': len(out_entries)})
        checks.require('ramdisk.entries.order', list(src_entries) == list(out_entries))
        other_entries_identical = all(
            entry_bytes(name, src_entries[name]) == entry_bytes(name, out_entries[name])
            for name in src_entries if name != TARGET_ENTRY)
        checks.require('ramdisk.entries.other.bytes.identical', other_entries_identical,
                       {'unchangedEntries': len(src_entries) - 1})
        checks.require('ramdisk.target.data', out_entries[TARGET_ENTRY]['data'] == new_registry,
                       {'sha256': sha(new_registry), 'bytes': len(new_registry)})
        checks.require('ramdisk.target.mode',
                       src_entries[TARGET_ENTRY]['fields'][1] == out_entries[TARGET_ENTRY]['fields'][1],
                       {'mode': oct(src_entries[TARGET_ENTRY]['fields'][1])})
        differences = [index for index in range(13)
                       if src_entries[TARGET_ENTRY]['fields'][index]
                       != out_entries[TARGET_ENTRY]['fields'][index]]
        checks.require('ramdisk.target.fields', differences == [6],
                       {'differingFieldIndexes': differences})

        src_hashes = hash_children(src['ramdisk'])
        out_hashes = hash_children(out['ramdisk'])
        ram_algo = out_hashes['hash-1']['algo'].rstrip(b'\x00').decode()
        checks.require('ramdisk.hash.updated.correct',
                       out_hashes['hash-1']['value'] == hashlib.new(
                           ram_algo, out['ramdisk'].properties['data']).digest())
        checks.require('ramdisk.hash.changed',
                       src_hashes['hash-1']['value'] != out_hashes['hash-1']['value'],
                       {'source': src_hashes['hash-1']['value'].hex(),
                        'output': out_hashes['hash-1']['value'].hex()})

        # Registry semantics.
        import json
        registry = json.loads(new_registry.decode('utf-8'))
        raw_text = new_registry.decode('utf-8')
        ids = [feature['featureId'] for feature in registry['features']]
        if expected_new_registry_sha is not None:
            checks.require('registry.sha256', sha(new_registry) == expected_new_registry_sha,
                           {'expected': expected_new_registry_sha, 'actual': sha(new_registry)})
        checks.add('registry.sha256', True, sha(new_registry))
        checks.require('registry.features.count', len(ids) == 45, len(ids))
        checks.require('registry.count.field', registry.get('count') == 45, registry.get('count'))
        checks.require('registry.feature.ids', ids == EXPECTED_FEATURE_IDS,
                       {'first': ids[:3], 'last': ids[-3:], 'count': len(ids)})
        checks.require('registry.spatial.ids.absent',
                       all(feature_id not in raw_text for feature_id in REMOVED_FEATURE_IDS),
                       REMOVED_FEATURE_IDS)
        quoted_key_lines = sum(1 for line in raw_text.splitlines() if '"featureId":' in line)
        checks.require('registry.featureId.quoted.lines', quoted_key_lines == 45, quoted_key_lines)

        # Byte-level proof: FDT header changes are limited to three length fields.
        src_header, out_header = fdt_header(source), fdt_header(output)
        changed_fields = [FDT_HEADER_FIELDS[index] for index in range(10)
                          if src_header[index] != out_header[index]]
        checks.require('fdt.header.changed.fields',
                       changed_fields == ['totalsize', 'off_dt_strings', 'size_dt_struct'],
                       {'changed': changed_fields,
                        'sourceTotalsize': src_header[1], 'outputTotalsize': out_header[1]})
        src_ram_off = unique_offset(source, src_ramdisk['compressed'], 'source ramdisk data')
        out_ram_off = unique_offset(output, out_ramdisk['compressed'], 'output ramdisk data')
        checks.require('fdt.ramdisk.data.offset.identical', src_ram_off == out_ram_off,
                       {'sourceOffset': src_ram_off, 'outputOffset': out_ram_off})
        prefix_src = source[40:src_ram_off - 8]
        prefix_out = output[40:out_ram_off - 8]
        checks.require('fdt.prefix.bytes.identical', prefix_src == prefix_out,
                       {'range': [40, src_ram_off - 8], 'bytes': len(prefix_src)})
        src_prop = struct.unpack_from('>2I', source, src_ram_off - 8)
        out_prop = struct.unpack_from('>2I', output, out_ram_off - 8)
        checks.require('fdt.ramdisk.data.property.header',
                       src_prop[1] == out_prop[1]
                       and src_prop[0] == len(src_ramdisk['compressed'])
                       and out_prop[0] == len(out_ramdisk['compressed']),
                       {'sourceLengthNameoff': list(src_prop),
                        'outputLengthNameoff': list(out_prop)})
        src_pad = (-len(src_ramdisk['compressed'])) % 4
        out_pad = (-len(out_ramdisk['compressed'])) % 4
        checks.add('fdt.ramdisk.data.padding', True,
                   {'sourcePaddingBytes': src_pad, 'outputPaddingBytes': out_pad})
        src_tail = source[src_ram_off + len(src_ramdisk['compressed']) + src_pad:]
        out_tail = output[out_ram_off + len(out_ramdisk['compressed']) + out_pad:]
        checks.require('fdt.tail.length.identical', len(src_tail) == len(out_tail),
                       {'sourceTailBytes': len(src_tail), 'outputTailBytes': len(out_tail)})
        tail_runs = differing_runs(src_tail, out_tail)
        hash_value = out_hashes['hash-1']['value']
        hash_value_offset = unique_offset(out_tail, hash_value, 'output ramdisk hash value')
        checks.require('fdt.tail.bytes.identical.except.ramdisk.hash',
                       tail_runs == [[hash_value_offset, hash_value_offset + len(hash_value)]],
                       {'differingRuns': tail_runs,
                        'expectedRun': [hash_value_offset, hash_value_offset + len(hash_value)]})

        summary = {
            'verificationStatus': 'PASS',
            'source': {'sha256': sha(source), 'bytes': len(source)},
            'output': {'sha256': sha(output), 'bytes': len(output)},
            'changedRamdiskEntries': [TARGET_ENTRY],
            'ramdiskEntries': len(src_entries),
            'unchangedRamdiskEntries': len(src_entries) - 1,
            'oldRegistry': {'sha256': sha(src_entries[TARGET_ENTRY]['data']),
                            'bytes': len(src_entries[TARGET_ENTRY]['data'])},
            'newRegistry': {'sha256': sha(new_registry), 'bytes': len(new_registry)},
            'features': {'count': len(ids), 'removedFeatureIds': REMOVED_FEATURE_IDS},
            'kernel': {'sha256': sha(next(n for n in src['others']
                        if n.properties.get('type', b'').rstrip(b'\x00') == b'kernel').properties['data'])},
            'dtb': {'sha256': sha(next(n for n in src['others']
                     if n.properties.get('type', b'').rstrip(b'\x00') == b'flat_dt').properties['data'])},
            'fdtHeaderChangedFields': changed_fields,
            'ramdiskDataOffset': src_ram_off,
            'ramdiskCompressedBytes': {'source': len(src_ramdisk['compressed']),
                                       'output': len(out_ramdisk['compressed'])},
            'ramdiskDataPropertyPadding': {'source': src_pad, 'output': out_pad},
            'byteIdenticalOutsidePatch': True,
            'fdtDiffRegions': [
                {'what': 'FDT totalsize field', 'absRange': [4, 8]},
                {'what': 'FDT off_dt_strings field', 'absRange': [12, 16]},
                {'what': 'FDT size_dt_struct field', 'absRange': [36, 40]},
                {'what': 'ramdisk data property length field',
                 'absRange': [src_ram_off - 8, src_ram_off - 4]},
                {'what': 'ramdisk gzip data and FDT 4-byte padding',
                 'absRange': [src_ram_off, src_ram_off + len(src_ramdisk['compressed']) + src_pad]},
                {'what': 'ramdisk hash value',
                 'absRange': [out_ram_off + len(out_ramdisk['compressed']) + hash_value_offset,
                              out_ram_off + len(out_ramdisk['compressed']) + hash_value_offset + len(hash_value)]},
            ],
            'proof': ('Only these bytes differ: three FDT length fields (totalsize, '
                      'off_dt_strings, size_dt_struct), the ramdisk data property length, the '
                      'ramdisk gzip payload (plus its 0-3 byte FDT 4-byte padding) and the '
                      'ramdisk sha256 hash value. Every other byte of image.ub is identical to '
                      'the source image; all 2839 other ramdisk cpio entries are byte-identical '
                      'and kernel/dtb payloads are unchanged.'),
        }
    except AssertionError as error:
        summary = {'verificationStatus': 'FAIL', 'error': str(error)}
    return {'status': summary.get('verificationStatus', 'FAIL'),
            'checks': checks.checks, 'summary': summary}


if __name__ == '__main__':
    raise SystemExit('library module: import it from patch_sd_image.py / verify_offline.py')
