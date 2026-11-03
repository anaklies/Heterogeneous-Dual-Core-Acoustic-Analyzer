"""Static integrity check of the STIPA 8 s / reason / progress deployment artifacts."""
from pathlib import Path
import gzip, hashlib, json, struct, sys

R = Path(__file__).resolve().parent
ROOT = R.parents[1]
sys.path.insert(0, str(ROOT / 'deployment'))
from firmware_formats_20261012 import read_fdt, read_cpio

FIELDS = ['experimental_index', 'valid', 'certified_zero', 'reason_code',
          'failed_band_hz', 'failed_modulation_hz', 'reference_depth',
          'measured_depth', 'transfer_ratio']
rows = []


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def check(name, ok, detail):
    rows.append({'check': name, 'pass': bool(ok), 'detail': detail})
    if not ok:
        raise AssertionError((name, detail))


# 1) quick plan graph
plan = json.loads((R / 'registry/plans/stipa_quick.json').read_text(encoding='utf-8'))
check('quick.samples', plan.get('samples') == 384000, plan.get('samples'))
check('quick.stages', len(plan.get('stages') or []) == 15, len(plan.get('stages') or []))
check('quick.outputWordCount', plan.get('outputWordCount') == 9, plan.get('outputWordCount'))
check('quick.finalFields', plan.get('finalOutput', {}).get('fields') == FIELDS,
      plan.get('finalOutput', {}).get('fields'))
for stage in plan['stages']:
    sp = json.loads((R / 'registry' / stage['plan']).read_text(encoding='utf-8'))
    check('stage%s.samples' % stage['stage'], sp.get('samples') == 384000, sp.get('samples'))
    patch = R / 'registry' / sp['patchFile']
    check('stage%s.patchSha' % stage['stage'], sha(patch) == sp['patchSHA256'], sp['patchFile'])
    if sp.get('weightPage'):
        wp = sp['weightPage']
        raw = (R / 'registry/plans' / wp['file']).read_bytes()
        check('stage%s.weightSha' % stage['stage'],
              len(raw) == 4 * wp['wordCount'] and hashlib.sha256(raw).hexdigest() == wp['sha256'],
              wp['file'])
    rows.append({'check': 'stage%s.plan' % stage['stage'], 'pass': True,
                 'detail': {'kind': sp.get('definition', {}).get('kind'),
                            'words': len(sp['patchRecords']),
                            'scheduledDescriptor': sp.get('scheduledDescriptor')}})

# 2) interface registry
reg = json.loads((R / 'registry/INTERFACE_REGISTRY.json').read_text(encoding='utf-8'))
feature = next(f for f in reg['features'] if f['featureId'] == 'stipa_experimental')
variant = (feature.get('variants') or [{}])[0]
check('registry.quickVariantSamples',
      variant.get('completeParams', {}).get('samples') == 384000, variant.get('completeParams'))
check('registry.quickModeSamples', feature.get('quickMode', {}).get('samples') == 384000,
      feature.get('quickMode'))
check('registry.outputFields', feature.get('output', {}).get('fields') == FIELDS,
      feature.get('output', {}).get('fields'))
check('registry.schemaFields', feature.get('schema', {}).get('fields') == FIELDS,
      feature.get('schema', {}).get('fields'))
check('registry.producerLayoutFields',
      feature.get('schema', {}).get('producerLayout', {}).get('fields') == FIELDS,
      feature.get('schema', {}).get('producerLayout', {}))
check('registry.otherFeatures', len(reg['features']) == 51, len(reg['features']))

# 3) gateway binary
gw = (R / 'gateway/echo-gateway').read_bytes()
check('gateway.elf', gw[:5] == b'\x7fELF\x01', gw[:5].hex())
check('gateway.currentStageIndex', b'currentStageIndex' in gw, 'string present')
check('gateway.outputWordCount', b'outputWordCount' in gw, 'string present')

# 4) SD image ramdisk contains the new registry + gateway, everything else intact
source = (ROOT / 'deployment/echo_measurement_stability_20261030/image.ub').read_bytes()
image = (R / 'image.ub').read_bytes()
patch_report = json.loads((R / 'SD_PATCH.json').read_text())
check('image.sha', hashlib.sha256(image).hexdigest() == patch_report['imageSHA256'],
      patch_report['imageSHA256'])


def ramdisk_entries(blob):
    tree, _, _ = read_fdt(blob)
    images = tree.child('images')
    ram = next(n for n in images.children if n.properties.get('type') == b'ramdisk\0')
    entries = read_cpio(gzip.decompress(ram.properties['data']))
    others = {n.name: hashlib.sha256(n.properties.get('data', b'')).hexdigest()
              for n in images.children if n is not ram}
    return entries, others


old_entries, old_others = ramdisk_entries(source)
new_entries, new_others = ramdisk_entries(image)
check('image.nonRamdiskUnchanged', old_others == new_others, sorted(new_others))
for p in (R / 'registry').rglob('*'):
    if p.is_file():
        name = 'opt/echo/registry/' + p.relative_to(R / 'registry').as_posix()
        check('image.registry.' + p.name, new_entries[name]['data'] == p.read_bytes(), name)
check('image.gateway', new_entries['opt/echo/bin/echo-gateway']['data'] == gw, 'echo-gateway')
untouched = {k: v for k, v in new_entries.items()
             if not k.startswith('opt/echo/registry/') and k != 'opt/echo/bin/echo-gateway'}
check('image.untouchedEntries',
      untouched == {k: v for k, v in old_entries.items()
                    if not k.startswith('opt/echo/registry/') and k != 'opt/echo/bin/echo-gateway'},
      len(untouched))

# 5) release metadata and deploy script
release = json.loads((R / 'ECHO_RELEASE.json').read_text(encoding='utf-8'))
check('release.imageSha', release['imageSHA256'] == patch_report['imageSHA256'],
      release['imageSHA256'])
check('release.gatewaySha', release['gatewaySHA256'] == sha(R / 'gateway/echo-gateway'),
      release['gatewaySHA256'])
check('release.registrySha', release['registrySHA256'] == sha(R / 'registry/INTERFACE_REGISTRY.json'),
      release['registrySHA256'])
check('release.quickSamples', release['stipaQuickMode']['samples'] == 384000,
      release['stipaQuickMode'])
check('release.resultFields', release['stipaQuickResultFields'] == FIELDS,
      release['stipaQuickResultFields'])
deploy = (R / 'deploy_board.sh').read_text(encoding='utf-8')
for expected in (sha(R / 'registry/INTERFACE_REGISTRY.json'), sha(R / 'gateway/echo-gateway'),
                 release['imageSHA256']):
    check('deploy.expected.' + expected[:8], expected in deploy, expected)

report = {'status': 'PASS', 'checks': len(rows), 'rows': rows}
(R / 'ARTIFACT_CHECK.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                                       encoding='utf-8')
print(json.dumps({'status': 'PASS', 'checks': len(rows)}))
