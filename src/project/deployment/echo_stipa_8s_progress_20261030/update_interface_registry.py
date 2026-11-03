"""Patch ONLY stipa_experimental in the current board INTERFACE_REGISTRY.

Baseline: deployment/echo_measurement_stability_20261030/registry/INTERFACE_REGISTRY.json
(the current board registry, utf-8). Fallback: before/INTERFACE_REGISTRY.json
snapshot taken from the same baseline.

Quick-mode 8 s delivery changes, nothing else:
  variants[0].completeParams.samples = 384000
  quickMode.samples                  = 384000
  output.fields                      = 9 frozen fields
  output.wordCount                   = 9 (new)
  schema.fields                      = 9 frozen fields
  schema.producerLayout.fields       = 9 frozen fields
  schema.units / schema.validity     = appended 9-field wording
All other features are copied byte-for-byte from the baseline JSON.
"""
import hashlib
import json
import sys
from pathlib import Path

R = Path(__file__).resolve().parent
ROOT = R.parents[1]
BASELINE = ROOT / 'deployment/echo_measurement_stability_20261030/registry/INTERFACE_REGISTRY.json'
SNAPSHOT = R / 'before/INTERFACE_REGISTRY.json'
OUT = R / 'registry/INTERFACE_REGISTRY.json'
SAMPLES = 384000
FIELDS = ['experimental_index', 'valid', 'certified_zero', 'reason_code',
          'failed_band_hz', 'failed_modulation_hz', 'reference_depth',
          'measured_depth', 'transfer_ratio']
WORD_COUNT = len(FIELDS)

def load_baseline():
    if BASELINE.exists():
        return BASELINE
    if SNAPSHOT.exists():
        return SNAPSHOT
    raise SystemExit('no INTERFACE_REGISTRY baseline found')

def main():
    src = load_baseline()
    raw = src.read_text(encoding='utf-8')
    if SNAPSHOT.exists():
        snap = SNAPSHOT.read_text(encoding='utf-8')
        if hashlib.sha256(snap.encode('utf-8')).hexdigest() != hashlib.sha256(raw.encode('utf-8')).hexdigest():
            print('WARNING: baseline differs from before/ snapshot; using', src)
    d = json.loads(raw)
    matched = [f for f in d['features'] if f.get('featureId') == 'stipa_experimental']
    if len(matched) != 1:
        raise SystemExit('stipa_experimental entry not found exactly once')
    f = matched[0]
    f['variants'][0]['completeParams']['samples'] = SAMPLES
    f['variants'][0]['completeParams']['measurementMode'] = 'quick'
    f['quickMode']['samples'] = SAMPLES
    out = f['output']
    out['offset'] = 1056768
    out['fields'] = list(FIELDS)
    out['wordCount'] = WORD_COUNT
    schema = f['schema']
    schema['fields'] = list(FIELDS)
    schema['producerLayout']['offset'] = out['offset']
    schema['producerLayout']['fields'] = list(FIELDS)
    suffix = ('；9字段（experimental_index, valid, certified_zero, reason_code, failed_band_hz, '
              'failed_modulation_hz, reference_depth, measured_depth, transfer_ratio）；'
              'failed_band_hz∈{0,500,1000,2000}；failed_modulation_hz∈{0,0.63,3.15,2,10,1.25,6.25}（快速三频带：500Hz→0.63/3.15，1000Hz→2/10，2000Hz→1.25/6.25）')
    if '9字段' not in schema['units']:
        schema['units'] = schema['units'] + suffix
    if '9字段' not in schema['validity']:
        schema['validity'] = schema['validity'] + ('；拒绝时 reason_code=1..4 且 failed_band_hz/failed_modulation_hz/reference_depth/'
            'measured_depth/transfer_ratio 同帧发布（9字段，未知量0）；success 时 3..8 为0；'
            'failed_band_hz∈{0,500,1000,2000}；failed_modulation_hz∈{0,0.63,3.15,2,10,1.25,6.25}')
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(d, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    raw_out = OUT.read_bytes()
    reread = json.loads(raw_out.decode('utf-8'))
    f2 = [x for x in reread['features'] if x.get('featureId') == 'stipa_experimental'][0]
    assert f2['variants'][0]['completeParams']['samples'] == SAMPLES
    assert f2['quickMode']['samples'] == SAMPLES
    assert f2['output']['fields'] == FIELDS and f2['output']['wordCount'] == WORD_COUNT
    assert f2['schema']['fields'] == FIELDS and f2['schema']['producerLayout']['fields'] == FIELDS
    other_before = [x for x in d['features'] if x.get('featureId') != 'stipa_experimental']
    other_after = [x for x in reread['features'] if x.get('featureId') != 'stipa_experimental']
    assert other_before == other_after, 'other feature entries must be byte-identical'
    print('registry updated', OUT)
    print(' baseline', src)
    print(' size', len(raw_out), 'sha256', hashlib.sha256(raw_out).hexdigest())
    print(' features', len(reread['features']), 'other entries unchanged', other_before == other_after)

if __name__ == '__main__':
    main()
