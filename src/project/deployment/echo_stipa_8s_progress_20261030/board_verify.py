"""Read/write verification of the deployed STIPA quick mode on the real board.

No acoustic stimulus is used: it records 8 s of silence/ambient as the reference,
then runs the new 15-stage quick graph on that silent capture. The expected
outcome is a *rejected* measurement with a truthful reason code - this proves the
new PL microprogram, the 9-word result, the 8 s sample counts and the
completedStages/currentStageIndex/totalStages progress protocol end-to-end
without pretending the silent recording is a valid STIPA measurement.
"""
from pathlib import Path
import json, socket, struct, sys, time

R = Path(__file__).resolve().parent
ROOT = R.parents[1]
HOST, PORT = '192.168.77.2', 48120
TIMEOUT = 900


class Peer:
    def __init__(self):
        self.sock = socket.create_connection((HOST, PORT), timeout=8)
        self.reader = self.sock.makefile('rb')
        self.sequence = 0
        self.sid = None
        self.t0 = time.monotonic()
        self.sid = self.call('hello', clientName='stipa8-acceptance',
                             clientVersion='1', maxBinaryPayloadBytes=1048576)['sessionId']
        self.token = self.call('control.claim', leaseSeconds=300)['controlToken']

    def call(self, op, **args):
        time.sleep(.02)
        self.sequence += 1
        request = dict(protocol='sixmic-analysis', version=1,
                       requestId=str(self.sequence), op=op, args=args)
        if self.sid:
            request['sessionId'] = self.sid
        self.sock.sendall(json.dumps(request).encode() + b'\n')
        deadline = time.monotonic() + 30
        while True:
            line = self.reader.readline()
            if not line:
                raise AssertionError('gateway disconnected')
            response = json.loads(line)
            if response.get('requestId') == request['requestId']:
                if response.get('status') not in ('ok', 'accepted'):
                    raise AssertionError((op, response))
                return response['result']
            if time.monotonic() > deadline:
                raise AssertionError(('response timeout', op))

    def start(self, feature, **params):
        args = dict(featureId=feature, params=params, controlToken=self.token)
        return self.call('feature.start', **args)['jobId']

    def get(self, job):
        return self.call('feature.get', jobId=job)

    def wait(self, job, feature, timeout=TIMEOUT):
        deadline = time.monotonic() + timeout
        seen = []
        while time.monotonic() < deadline:
            result = self.get(job)
            if result.get('featureId') != feature:
                raise AssertionError(('job feature mismatch', result.get('featureId')))
            progress = result.get('progress') or {}
            seen.append(dict({k: progress.get(k) for k in
                              ('phase', 'completedStages', 'currentStageIndex', 'totalStages',
                               'capturedSamples', 'requiredSamples')},
                             t=round(time.monotonic() - self.t0, 2)))
            if result.get('state') == 'failed':
                raise AssertionError(('job failed', result))
            if result.get('state') == 'completed':
                return result, seen
            time.sleep(.25)
        raise AssertionError(('job timeout', job, seen[-3:]))

    def pages(self, job):
        offset, words = 0, []
        while True:
            result = self.call('feature.result', jobId=job, offsetWords=offset, maxWords=1024)
            chunk = result.get('words') or []
            words.extend(chunk)
            offset += len(chunk)
            if not result.get('more'):
                return words, result


def f32(w):
    return struct.unpack('<f', struct.pack('<I', int(w) & 0xFFFFFFFF))[0]


def near(x, y, tol=2e-3):
    return abs(float(x) - float(y)) <= tol


def main():
    out = {'status': 'RUN', 'host': HOST, 'errors': []}
    peer = Peer()
    features = []
    cursor = 0
    while cursor is not None:
        page = peer.call('feature.list', cursor=cursor, limit=4)
        features.extend(page['features'])
        cursor = page.get('nextCursor')
    out['featureCount'] = len(features)
    stipa = next(f for f in features if f.get('featureId') == 'stipa_experimental')
    out['stipaRegistryView'] = {
        'mode': stipa.get('mode'),
        'params': stipa.get('params'),
        'output': stipa.get('output'),
        'quickMode': stipa.get('quickMode'),
        'schemaFields': (stipa.get('schema') or {}).get('fields'),
        'variants': stipa.get('variants'),
    }
    fields9 = ['experimental_index', 'valid', 'certified_zero', 'reason_code',
               'failed_band_hz', 'failed_modulation_hz', 'reference_depth',
               'measured_depth', 'transfer_ratio']
    seen_fields = ((stipa.get('schema') or {}).get('producerLayout') or {}).get('fields')
    assert seen_fields == fields9, ('board catalog schema is not 9 fields', seen_fields)
    # 1) 8 s reference capture through the real PL ring (silence/ambient only).
    ref_t0 = time.monotonic()
    ref = peer.start('io_pcm', samples=384000, channels=1, channel=0)
    ref_result, ref_seen = peer.wait(ref, 'io_pcm', timeout=90)
    ref_elapsed = time.monotonic() - ref_t0
    out['reference'] = {'jobId': ref, 'state': ref_result.get('state'),
                        'capturedSamples': (ref_result.get('progress') or {}).get('capturedSamples'),
                        'requiredSamples': (ref_result.get('progress') or {}).get('requiredSamples'),
                        'progressSeen': ref_seen[-3:]}
    # 2) quick STIPA graph, 15 stages, on the silent capture.
    staged = peer.start('stipa_experimental', referenceJobId=ref,
                        testSignalConfirmed=True, samples=384000,
                        measurementMode='quick')
    staged_t0 = time.monotonic()
    staged_result, seen = peer.wait(staged, 'stipa_experimental', timeout=TIMEOUT)
    staged_elapsed = time.monotonic() - staged_t0
    progress = staged_result.get('progress') or {}
    out['staged'] = {
        'jobId': staged, 'state': staged_result.get('state'),
        'progressKeys': sorted(progress.keys()),
        'progressFinal': {k: progress.get(k) for k in
                          ('completedStages', 'currentStageIndex', 'totalStages', 'phase')},
        'progressSamples': [s for s in seen if s.get('totalStages')][:12],
        'totalStages': progress.get('totalStages'),
    }
    assert progress.get('totalStages') == 15, ('totalStages != 15', progress)
    assert progress.get('completedStages') == 15, ('completedStages != totalStages at completion', progress)
    assert progress.get('currentStageIndex') == 15, ('currentStageIndex != 15 at completion', progress)
    assert 'currentStageIndex' in progress, 'gateway did not expose currentStageIndex'
    # 3) 9-word result.
    words, result_meta = peer.pages(staged)
    fields = ['experimental_index', 'valid', 'certified_zero', 'reason_code',
              'failed_band_hz', 'failed_modulation_hz', 'reference_depth',
              'measured_depth', 'transfer_ratio']
    out['result'] = {
        'totalWords': result_meta.get('totalWords'),
        'schemaFields': (result_meta.get('schema') or {}).get('fields'),
        'words': len(words),
        'values': [f32(w) for w in words[:9]],
        'fields': fields[:min(len(words), 9)],
    }
    assert len(words) == 9, ('expected 9 result words', len(words), result_meta.get('schema'))
    values = out['result']['values']
    assert abs(values[2]) < 1e-9, 'certified_zero must stay 0'
    assert values[1] in (0.0, 1.0), ('valid not boolean', values[1])
    if values[1] == 0.0:
        assert int(values[3]) in (1, 2, 3, 4), ('invalid result without reason', values)
        if int(values[3]) in (2, 3, 4):
            assert any(near(values[4], v, 1e-3) for v in (500.0, 1000.0, 2000.0)), \
                ('bad failed band', values)
        if int(values[3]) in (3, 4):
            assert any(near(values[5], v) for v in (0.63, 3.15, 2.0, 10.0, 1.25, 6.25)), \
                ('bad failed mod', values)
    # 4) PC decoder must render the rejection truthfully (no green success, no fake index).
    sys.path.insert(0, str(ROOT / 'apps/sixmic-desktop'))
    from ui.features.decoder import decode_result
    spec = json.loads((ROOT / 'apps/sixmic-desktop/ui/config/feature_view_spec.json')
                      .read_text(encoding='utf-8'))
    feature = spec['features']['stipa_experimental']
    chart = decode_result(feature, {'state': 'completed', 'schema': result_meta.get('schema') or {}},
                          words, variant={'params': {'measurementMode': 'quick'},
                                          'progress': progress})
    out['pcDecode'] = {
        'indexValid': chart.get('indexValid'),
        'resultValid': chart.get('resultValid'),
        'invalidReason': chart.get('invalidReason'),
        'stage': chart.get('stage'),
        'scalarRows': chart.get('scalarRows'),
    }
    expect_valid = values[1] != 0.0
    assert chart.get('resultValid') is expect_valid, ('PC resultValid mismatch', chart.get('resultValid'), values)
    assert chart.get('indexValid') is expect_valid, 'PC index validity must follow the device valid word'
    if not expect_valid:
        assert chart.get('invalidReason'), 'PC decoder did not explain the rejection'
    assert chart.get('stage', {}).get('completed') == 15, chart.get('stage')
    assert chart.get('stage', {}).get('total') == 15, chart.get('stage')
    out['timings'] = {'referenceCaptureSeconds': round(ref_elapsed, 2),
                      'stagedReadSeconds': round(staged_elapsed, 2),
                      'totalSecondsBeforeResultFetch': round(time.monotonic() - peer.t0, 2)}
    out['status'] = 'PASS'
    out['hardwareAccepted'] = False
    out['note'] = ('Silent/ambient capture only: proves 8 s capture, 15-stage PL microprogram, '
                   '9-word reason result and progress protocol; NOT an acoustic STIPA acceptance.')
    peer.sock.close()
    (R / 'BOARD_ACCEPTANCE.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n',
                                             encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2)[:6000])


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        report = {'status': 'FAIL', 'error': repr(exc)[:1500]}
        (R / 'BOARD_ACCEPTANCE.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                                                encoding='utf-8')
        raise