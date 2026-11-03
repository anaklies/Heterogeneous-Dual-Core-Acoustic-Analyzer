"""Quick-mode software checks for the 8 s (N=384000) STIPA quick chain.

Covered:
  * registry file inventory + 15 stage plan load/hash/descriptor self-consistency
  * materialized weight pages (sha256, size, content equals frozen host config)
  * INTERFACE_REGISTRY stipa_experimental contract (samples/fields/wordCount) and
    proof that every other feature entry is unchanged from the baseline
  * joint_fit numeric unit test
  * quick_index numeric unit tests + frozen result-word tests for rejection
    paths reason_code=1/2/3/4 and the 1.3 ratio boundary
  * same-PCM full 15-stage summary from SAME_PCM_CHECK.json (run
    check_same_pcm.py first).

Writes QUICK_SOFTWARE_CHECK.json.
"""
import ctypes
import hashlib
import json
import math
import struct
import sys
from pathlib import Path
import numpy as np

R = Path(__file__).resolve().parent
ROOT = R.parents[1]
sys.path.insert(0, str(R))
import quick_program as q
from check_same_pcm import PL, encode_pcm24, run_chain, synthetic_pcm

REG = R / 'registry'
PLANS = REG / 'plans'
LAYOUT = q.old.layout(q.N)
RES = LAYOUT['result']
CHECKS = []
def ck(name, passed, detail=None):
    row = {'check': name, 'pass': bool(passed)}
    if detail is not None:
        row['detail'] = detail
    CHECKS.append(row)
    return bool(passed)

def f32(x):
    return np.float32(x)

def read_words(path):
    return list(struct.unpack('<' + 'I' * (len(path.read_bytes()) // 4), path.read_bytes()))

def execute_final(m, pl):
    pl.run(m, q.final())
    return [float(m[q.OUT + i]) for i in range(9)]

def result_bits(m):
    return [int(m.view(np.uint32)[q.OUT + i]) for i in range(9)]

def seed_result_region(m, valid=1.0, dc=0.1, refamp=0.05, measamp=None, powers=0.01, override=None):
    """Seed the intermediate result region exactly as the upstream stages would."""
    m[q.OUT + RES + 31] = valid
    for b in q.BANDS:
        for tr in (0, 1):
            m[q.OUT + RES + 32 + 2 * b + tr] = powers
            a = RES + 48 + tr * 42 + b * 6
            m[q.OUT + a] = dc
            amp = measamp if (measamp is not None and tr == 1) else refamp
            m[q.OUT + a + 2] = amp
            m[q.OUT + a + 4] = amp
    if override:
        override(m)
    return m

def seed_final(ratio=1.0, valid=1.0, dc=0.1, refamp=0.05, measamp=None, powers=0.01,
               band=2, override=None):
    m = np.zeros(q.ARENA, np.float32)
    if measamp is None:
        measamp = refamp * ratio
    return seed_result_region(m, valid=valid, dc=dc, refamp=refamp, measamp=measamp,
                              powers=powers, override=override)

def registry_inventory():
    files = sorted(p.relative_to(REG).as_posix() for p in REG.rglob('*') if p.is_file())
    plan_jsons = [f for f in files if f.endswith('.json') and f.startswith('plans/stipa_quick')]
    smps = [f for f in files if f.startswith('plans/') and f.endswith('.smp')]
    weights = [f for f in files if f.startswith('plans/') and f.endswith('.f32le')]
    ck('registry/interface_registry_present', 'INTERFACE_REGISTRY.json' in files)
    ck('registry/15_stage_plans', len(plan_jsons) == 16, {'planJsonCount': len(plan_jsons), 'expected': 16})
    ck('registry/15_patch_files', len(smps) == 15, {'smpCount': len(smps)})
    ck('registry/3_weight_files', len(weights) == 3, {'weights': weights})
    ck('registry/file_inventory', len(files) == 1 + 16 + 15 + 3, {'fileCount': len(files)})

def plan_checks():
    graph = json.loads((PLANS / 'stipa_quick.json').read_text(encoding='utf-8'))
    ck('plan/graph_stage_count_15', len(graph['stages']) == 15)
    ck('plan/graph_samples_384000', graph['samples'] == 384000, {'samples': graph['samples']})
    ck('plan/graph_final_fields_9', graph['finalOutput']['fields'] == q.RESULT_FIELDS,
       {'fields': graph['finalOutput']['fields']})
    ck('plan/graph_final_word_count_9', graph['finalOutput'].get('wordCount') == 9 and graph.get('outputWordCount') == 9,
       {'finalOutputWordCount': graph['finalOutput'].get('wordCount'), 'outputWordCount': graph.get('outputWordCount')})
    ck('plan/graph_initial_clear_covers_workspace',
       graph['initialClearRange']['wordOffset'] == q.BASE and
       graph['initialClearRange']['wordCount'] >= 8192 + LAYOUT['words'] and
       graph['initialClearRange']['wordOffset'] + graph['initialClearRange']['wordCount'] <= q.ARENA,
       graph['initialClearRange'])
    expected = [(0, 'convert_raw_PCM24'), (1, 'validate_captures')]
    for band in q.BANDS:
        for tr in (0, 1):
            expected += [('quick_filter', band, tr), ('joint_fit', band, tr)]
    ok_graph = True
    stage_hashes = []
    for i, stage in enumerate(graph['stages']):
        plan = json.loads((REG / stage['plan']).read_text(encoding='utf-8'))
        smp = (REG / plan['patchFile']).read_bytes()
        ok = hashlib.sha256(smp).hexdigest() == plan['patchSHA256']
        ok = ok and plan['samples'] == 384000
        ok = ok and plan['workspace']['n'] == 384000
        ok = ok and plan['service']['output'] + plan['workspace']['words'] <= q.ARENA
        ok = ok and plan['scheduledDescriptor'] == q.TABLE
        ok = ok and plan.get('clearWorkspace') is False
        if not ok:
            ok_graph = False
        # patch records must reproduce the file bytes exactly
        off = 0
        for rec in plan['patchRecords']:
            rec_bytes = struct.pack('<II', rec['wordOffset'], rec['wordCount']) + \
                b''.join(struct.pack('<I', w) for w in rec['words'])
            ok_rec = rec_bytes == smp[off:off + len(rec_bytes)]
            off += len(rec_bytes)
            ok = ok and ok_rec
        ok = ok and smp[off:off + 8] == struct.pack('<II', 0, 0) and off + 8 == len(smp)
        ok_graph = ok_graph and ok
        stage_hashes.append({'stage': i, 'patchFile': plan['patchFile'], 'patchSHA256': plan['patchSHA256']})
        if i == 14:
            ck('plan/final_stage_defines_quick_index', plan['definition']['kind'] == 'quick_index')
            ck('plan/final_stage_output_word_count_9', plan.get('outputWordCount') == 9,
               {'outputWordCount': plan.get('outputWordCount')})
    ck('plan/all_15_stage_load_and_hash', ok_graph, {
        'graphSHA256': hashlib.sha256((PLANS / 'stipa_quick.json').read_bytes()).hexdigest(),
        'registrySHA256': hashlib.sha256((REG / 'INTERFACE_REGISTRY.json').read_bytes()).hexdigest(),
        'stagePatchHashes': stage_hashes})

def apply_stage_patch(plan):
    m = np.zeros(q.ARENA, np.float32)
    u = m.view(np.uint32)
    for rec in plan['patchRecords']:
        a, b = rec['wordOffset'], rec['wordCount']
        u[a:a + b] = np.asarray(rec['words'], np.uint32)
    return m

def q_graph_program_obj(stage):
    d = q.graph()[stage]
    if d['kind'] == 'convert_raw_PCM24':
        c, _, _ = q.convert_pcm24(2 * q.N, 0)
    elif d['kind'] == 'validate_captures':
        c = q.validation()
    elif d['kind'] == 'quick_filter':
        c, _ = q.filt(d['band'], d['trace'])
    elif d['kind'] == 'joint_fit':
        c = q.joint(d['band'], d['trace'])
    else:
        c = q.final()
    return c

def q_graph_program(stage):
    return [int(x) for x in np.asarray(q_graph_program_obj(stage).words, np.uint32).ravel()]

def stage_built_image(stage):
    """Regenerate exactly the arena image quick_program.build() installs for a stage."""
    m = np.zeros(q.ARENA, np.float32)
    q.old.install_stage(m, q_graph_program_obj(stage), q.old.layout(q.N), base=q.BASE)
    u = m.view(np.uint32)
    proto = u[q.BASE:q.BASE + 16].copy()
    for slot in range(4):
        v = proto.copy()
        v[4] = q.BASE + 4352 + 80 * slot
        v[9] = 512
        v[13] = stage + 1
        u[q.TABLE + 16 * slot:q.TABLE + 16 * (slot + 1)] = v
    return m

def descriptor_checks():
    """Validate the shipped .smp patch load path.

    The BASE+0 prototype descriptor is builder scratch: build() writes it while
    composing the image but the shipped patch only carries the scheduled
    descriptor-table entry (scheduledDescriptor = P2DescriptorTable = 525312,
    see registry p2DescriptorTable), the code page, the context page and the
    output meta page. A patch-only arena therefore reads all-zero at BASE by
    design; the runtime engine reads its descriptor from the scheduled table
    slot. The meaningful assertions are made on that scheduled entry, on the
    patched code/context/output pages and on a real execution of the patched
    final stage through the scheduled descriptor.
    """
    ok = True
    detail = []
    for i in range(15):
        plan = json.loads((PLANS / f'stipa_quick_stage_{i:03}.json').read_text(encoding='utf-8'))
        m = apply_stage_patch(plan)
        u = m.view(np.uint32)
        code = q.BASE + 128
        w = [int(x) for x in u[q.TABLE:q.TABLE + 16]]
        good = (w[0] == 0x414c5531 and w[1] == 1 and w[2] == code and 0 < w[3] <= 1024 and
                w[4] == q.BASE + 4352 and w[5] == q.OUT and w[6] == LAYOUT['words'] and
                w[7] == q.OUT and w[8] == LAYOUT['words'] and w[9] == 512 and w[10] == 2 and
                w[11] == 1 and w[12] == 1 and w[13] == i + 1 and w[14] == 1 and w[15] == 0)
        for slot in range(1, 4):
            s = [int(x) for x in u[q.TABLE + 16 * slot:q.TABLE + 16 * (slot + 1)]]
            good = good and s[:4] == w[:4] and s[4] == q.BASE + 4352 + 80 * slot and s[5:] == w[5:]
        expected = q_graph_program(i)
        good = good and len(expected) == 4 * w[3]
        good = good and all(int(u[code + k]) == expected[k] for k in range(len(expected)))
        good = good and all(int(x) == 0 for x in u[q.BASE + 4352:q.BASE + 4352 + 320])
        good = good and all(int(x) == 0 for x in u[q.OUT - 16:q.OUT])
        img = stage_built_image(i)
        iu = img.view(np.uint32)
        for rec in plan['patchRecords']:
            a, b = rec['wordOffset'], rec['wordCount']
            good = good and all(int(u[a + k]) == int(iu[a + k]) for k in range(b))
        if not good:
            ok = False
            detail.append({'stage': i, 'scheduledDescriptor': w})
    ck('plan/15_patch_load_scheduled_descriptor_and_code', ok, detail or None)
    # End-to-end: a patch-only arena (no builder image at BASE at all) executes
    # stage 14 through the scheduled descriptor, exactly like the board patch path.
    plan = json.loads((PLANS / 'stipa_quick_stage_014.json').read_text(encoding='utf-8'))
    m = apply_stage_patch(plan)
    seed_result_region(m)
    pl = PL()
    status = ctypes.c_uint()
    calls = 0
    while True:
        pl.fn(m.ctypes.data, q.TABLE, q.ARENA, 0, ctypes.byref(status))
        calls += 1
        if status.value & 255:
            raise RuntimeError('patched final stage PL error %s' % hex(status.value))
        if status.value & 0x80000000:
            break
        if calls > 8:
            raise RuntimeError('patched final stage did not finish')
    res = [float(m[q.OUT + i]) for i in range(9)]
    good = res == [1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0] and calls == 1
    ck('plan/patch_only_final_stage_executes_from_scheduled_descriptor', good,
       {'result': res, 'submissions': calls})

def weight_checks():
    ok = True
    detail = []
    for band in q.BANDS:
        fn = PLANS / f'stipa_quick_band{band}.f32le'
        raw = fn.read_bytes()
        expected = q.weights(band).ravel().astype('<f4').tobytes()
        good = raw == expected and len(raw) == 4 * 6 * (q.N // q.DEC)
        ok = ok and good
        detail.append({'bandHz': int(q.old.CENTERS[band]), 'bytes': len(raw),
                       'words': len(raw) // 4, 'sha256': hashlib.sha256(raw).hexdigest(),
                       'equalsHostConfig': raw == expected})
    graph = json.loads((PLANS / 'stipa_quick.json').read_text(encoding='utf-8'))
    for stage in graph['stages']:
        wp = stage.get('weightPage')
        if not wp:
            continue
        raw = (PLANS / wp['file']).read_bytes()
        plan = json.loads((REG / stage['plan']).read_text(encoding='utf-8'))
        pw = plan['weightPage']
        good = (hashlib.sha256(raw).hexdigest() == wp['sha256'] == pw['sha256'] and
                wp['wordCount'] == pw['wordCount'] == len(raw) // 4 and
                pw['wordOffset'] == q.OUT + 3 * q.N and wp['wordOffset'] == q.OUT + 3 * q.N)
        ok = ok and good
    ck('weights/3_pages_match_host_config_and_hash', ok, detail)

def interface_registry_checks():
    reg = json.loads((REG / 'INTERFACE_REGISTRY.json').read_text(encoding='utf-8'))
    f = [x for x in reg['features'] if x['featureId'] == 'stipa_experimental'][0]
    good = (f['variants'][0]['completeParams']['samples'] == 384000 and
            f['quickMode']['samples'] == 384000 and
            f['output']['fields'] == q.RESULT_FIELDS and
            f['output']['wordCount'] == 9 and
            f['schema']['fields'] == q.RESULT_FIELDS and
            f['schema']['producerLayout']['fields'] == q.RESULT_FIELDS and
            f['variants'][0]['file'] == 'plans/stipa_quick.json' and
            f['quickMode']['stages'] == 15)
    ck('interface/stipa_quick_contract', good, {
        'completeParamsSamples': f['variants'][0]['completeParams']['samples'],
        'quickModeSamples': f['quickMode']['samples'],
        'outputWordCount': f['output'].get('wordCount'),
        'outputFields': f['output']['fields']})
    baseline_path = R / 'before/INTERFACE_REGISTRY.json'
    if baseline_path.exists():
        base = json.loads(baseline_path.read_text(encoding='utf-8'))
        other_base = [x for x in base['features'] if x.get('featureId') != 'stipa_experimental']
        other_new = [x for x in reg['features'] if x.get('featureId') != 'stipa_experimental']
        ck('interface/other_features_unchanged', other_base == other_new,
           {'featureCount': len(other_new)})
        b = [x for x in base['features'] if x.get('featureId') == 'stipa_experimental'][0]
        changed = [k for k in set(b) | set(f) if b.get(k) != f.get(k)]
        ck('interface/only_stipa_entry_fields_changed', set(changed) <= {'output', 'schema', 'variants', 'quickMode'},
           {'changedTopLevelKeys': sorted(changed)})
    else:
        ck('interface/baseline_snapshot_for_diff_available', False, {'missing': str(baseline_path)})

def joint_fit_checks():
    pl = PL()
    m = np.zeros(q.ARENA, np.float32)
    t = (np.arange(q.N // q.DEC) + .5) / 200
    coeff = np.array([.1, .001, .04, .01, .02, .01])
    rows = []
    ok = True
    for band in q.BANDS:
        X = np.column_stack([np.ones(len(t)), t - t[60:-60].mean(),
                             *[v for f in q.old.PAIRS[band] for v in (np.sin(2 * np.pi * f * t), np.cos(2 * np.pi * f * t))]])
        m.fill(0)
        m[q.OUT + 2 * q.N:q.OUT + 2 * q.N + len(t)] = (X @ coeff).astype(np.float32)
        w = q.weights(band).ravel()
        m[q.OUT + 3 * q.N:q.OUT + 3 * q.N + len(w)] = w
        pl.run(m, q.joint(band, 0))
        a = m[q.OUT + RES + 48 + band * 6:q.OUT + RES + 48 + band * 6 + 6]
        err = float(np.max(np.abs(a - coeff)))
        ok = ok and err < 2e-6
        rows.append({'bandHz': int(q.old.CENTERS[band]), 'maxAbsoluteError': err,
                     'coefficients': [float(v) for v in a]})
    ck('unit/joint_fit_coefficients', ok, rows)
    return pl

def frozen_expected_index(ratio):
    """Reference host formula of the unchanged frozen quick index (six pairs):
    x = clamp(10*log10(r/(1-r)), -15, 15);  index = (x+15)/30."""
    r = min(max(ratio, 1e-6), 1 - 1e-6)
    x = 10 * math.log10(r / (1 - r))
    x = min(max(x, -15), 15)
    return (x + 15) / 30

def index_checks(pl):
    rows = []
    ok = True
    for ratio in (1.0, 0.5, 0.25, 0.75):
        m = seed_final(ratio=ratio)
        res = execute_final(m, pl)
        expected = frozen_expected_index(ratio)
        good = (abs(res[0] - expected) < 1e-5 and res[1] == 1.0 and res[2] == 0.0 and
                all(v == 0.0 for v in res[3:]))
        ok = ok and good
        rows.append({'inputMTF': ratio, 'index': res[0], 'expectedIndex': expected, 'result': res, 'pass': good})
    ck('unit/quick_index_and_frozen_fields', ok, rows)
    m = seed_final()
    res = execute_final(m, pl)
    ck('unit/success_reason_fields_zero', res[3:] == [0.0] * 6, {'result': res})

def failure_checks(pl):
    rows = []
    # reason1: capture validation flag cleared
    m = seed_final(valid=0.0)
    res = execute_final(m, pl)
    good = res == [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    ck('failure/reason1_capture_invalid', good, {'result': res})

    # reason2 energy: one band power is zero (band 2000)
    def zero_band_power(mm):
        mm[q.OUT + RES + 32 + 2 * 4] = 0.0
        mm[q.OUT + RES + 32 + 2 * 4 + 1] = 0.0
    m = seed_final(override=zero_band_power)
    res = execute_final(m, pl)
    good = res[3] == 2.0 and res[4] == 2000.0 and res[1] == 0.0 and res[0] == 0.0
    ck('failure/reason2_energy_band', good, {'result': res})

    # reason2 fit: DC coefficient of band 1000 trace0 is zero
    def bad_fit(mm):
        mm[q.OUT + RES + 48 + 3 * 6] = 0.0
    m = seed_final(override=bad_fit)
    res = execute_final(m, pl)
    good = res[3] == 2.0 and res[4] == 1000.0 and res[1] == 0.0
    ck('failure/reason2_fit_band', good, {'result': res})

    # reason3: reference modulation depth below .15 (all bands low, first band/pair fires)
    m = seed_final(dc=1.0, refamp=0.05)
    res = execute_final(m, pl)
    good = (res[3] == 3.0 and res[4] == 500.0 and abs(res[5] - 0.63) < 1e-6 and
            abs(res[6] - 0.05) < 1e-6 and abs(res[7] - 0.05) < 1e-6 and
            abs(res[8] - 1.0) < 1e-6 and res[1] == 0.0 and res[0] == 0.0)
    ck('failure/reason3_reference_depth', good, {'result': res})
    # reason3 on band 1000 second modulation pair: 10.0 Hz is part of the frozen
    # quick-mode enumeration {0,0.63,3.15,2,10,1.25,6.25}
    def low_pair2_1000(mm):
        mm[q.OUT + RES + 48 + 3 * 6 + 2] = 0.5
        mm[q.OUT + RES + 48 + 3 * 6 + 3] = 0.0
        mm[q.OUT + RES + 48 + 3 * 6 + 4] = 0.005
        mm[q.OUT + RES + 48 + 3 * 6 + 5] = 0.0
    m = seed_final(dc=1.0, refamp=0.5, override=low_pair2_1000)
    res = execute_final(m, pl)
    good = res[3] == 3.0 and res[4] == 1000.0 and res[5] == 10.0 and abs(res[6] - 0.005) < 1e-6
    ck('failure/reason3_band1000_modulation_10hz', good, {'result': res})

    # reason4: measured/reference ratio 1.5
    m = seed_final(dc=1.0, refamp=0.5, measamp=0.75)
    res = execute_final(m, pl)
    good = (res[3] == 4.0 and res[4] == 500.0 and abs(res[5] - 0.63) < 1e-6 and
            abs(res[6] - 0.5) < 1e-6 and abs(res[7] - 0.75) < 1e-6 and
            abs(res[8] - 1.5) < 1e-6 and res[1] == 0.0 and res[0] == 0.0)
    ck('failure/reason4_ratio_1.5', good, {'result': res})

    # boundary: ratio exactly 1.3 must remain valid (strict >1.3 rejection)
    m = seed_final(dc=1.0, refamp=0.5, measamp=0.65)
    res = execute_final(m, pl)
    good = res[1] == 1.0 and res[3] == 0.0 and abs(res[0] - 1.0) < 1e-6
    ck('failure/ratio_1.3_boundary_valid', good, {'result': res})
    # just above boundary must be rejected
    m = seed_final(dc=1.0, refamp=0.5, measamp=0.6501)
    res = execute_final(m, pl)
    good = res[1] == 0.0 and res[3] == 4.0 and res[8] > 1.3
    ck('failure/ratio_above_1.3_rejected', good, {'result': res})
    return rows

def same_pcm_section():
    p = R / 'SAME_PCM_CHECK.json'
    if not p.exists():
        ck('samePcm/result_json_present', False, {'hint': 'run check_same_pcm.py first'})
        return None
    d = json.loads(p.read_text(encoding='utf-8'))
    ck('samePcm/result_json_present', True)
    ck('samePcm/all_checks_pass', d.get('allPass') is True,
       {'checks': len(d.get('checks', [])), 'plSubmissions': d.get('plSubmissions')})
    syn = d.get('synthetic', {})
    final = syn.get('final', {})
    ck('samePcm/synthetic_index_valid_reason', final.get('experimental_index') == 1.0 and
       final.get('valid') == 1.0 and final.get('reason_code') == 0.0 and final.get('certified_zero') == 0.0,
       {'final': {k: v for k, v in final.items() if k != 'bits'}})
    ratios = [dd['ratio'] for b in syn.get('bands', []) for dd in b.get('depths', [])]
    ck('samePcm/synthetic_six_ratios_1', len(ratios) == 6 and all(abs(r - 1) < 1e-6 for r in ratios),
       {'ratios': ratios})
    reals = d.get('realPcm', [])
    ck('samePcm/real_pcm_runs_present', len(reals) >= 1,
       [{'kind': r['source']['kind'], 'reason_code': r['final']['reason_code'],
         'failed_band_hz': r['final']['failed_band_hz'],
         'failed_modulation_hz': r['final']['failed_modulation_hz'],
         'valid': r['final']['valid'], 'index': r['final']['experimental_index']} for r in reals])
    ck('samePcm/all_real_filter_and_fit_bitwise_equal',
       all(c['pass'] for c in d.get('checks', []) if 'bitwise_equal' in c['check']))
    return {'allPass': d.get('allPass'), 'plSubmissions': d.get('plSubmissions'),
            'syntheticFinal': {k: v for k, v in final.items() if k != 'bits'},
            'real': [{'kind': r['source']['kind'], 'final': {k: v for k, v in r['final'].items() if k != 'bits'},
                      'bands': [{'bandHz': b['bandHz'], 'depths': b['depths']} for b in r['bands']]} for r in reals]}

def main():
    registry_inventory()
    plan_checks()
    descriptor_checks()
    weight_checks()
    interface_registry_checks()
    pl = joint_fit_checks()
    index_checks(pl)
    failure_checks(pl)
    same = same_pcm_section()
    result = {'generatedAt': None, 'stipaQuickSamples': q.N,
              'resultFields': q.RESULT_FIELDS, 'checks': CHECKS,
              'passed': sum(1 for c in CHECKS if c['pass']), 'total': len(CHECKS),
              'samePcmSummary': same,
              'allPass': all(c['pass'] for c in CHECKS)}
    import time
    result['generatedAt'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
    (R / 'QUICK_SOFTWARE_CHECK.json').write_text(json.dumps(result, ensure_ascii=False, indent=2,
        default=lambda o: o.item() if hasattr(o, 'item') else str(o)), encoding='utf-8')
    for c in CHECKS:
        print('PASS' if c['pass'] else 'FAIL', c['check'])
    print('QUICK_SOFTWARE_CHECK', 'PASS' if result['allPass'] else 'FAIL', result['passed'], '/', result['total'])
    return 0 if result['allPass'] else 1

if __name__ == '__main__':
    sys.exit(main())
