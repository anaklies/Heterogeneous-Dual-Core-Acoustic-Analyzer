"""Post-deploy acceptance probe for echo_spatial_off_20261031 (run AFTER Lead go).

PC-side, read-only except for control.claim/probe: talks to the board gateway
control port (192.168.77.2:48120, protocol sixmic-analysis v1), reads
feature.list, and probes feature.start for the six removed spatial feature ids
(they must fail with unsupported_feature and must not create jobs).

Optionally parses the serial after-check log to verify the board-side hashes,
feature count and gateway restart, then writes POST_DEPLOY.json.

Usage:
  python post_deploy_verify.py [--serial-log board_after_serial.txt]
"""
from pathlib import Path
import argparse, hashlib, json, re, socket, time

R = Path(__file__).resolve().parent
HOST, PORT = '192.168.77.2', 48120
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
REMOVED = ['spatial_interface', 'directed_das', 'full_das', 'band_das',
           'spatial_grid', 'spatial_peaks']
NEW_REGISTRY_SHA = 'dcbc393723513773867f6a9d96f396eb22b13386060881fdae06dda4ecb77628'
OLD_GATEWAY_SHA = 'b982cecea0e9da4bf3a73dc7855d2ba41be7d22322f7a0221d8e0b07ef928920'
NEW_IMAGE_SHA = '646631abdd1add91b96ea28d2553eafeac647c42267386e03fddaf17613b6565'
OLD_IMAGE_SHA = 'cba07779ad32643380a96462569dabb4f4f4b2ec62bc9476a8dd4caa1fbc4902'
RELEASE_SHA = 'f51249c8b9118139b54210d11f4c0bc1dd691f9280e9bd8f012125492d697066'
GATEWAY45_SHA = '5d4b0291146f71fd0f5e39ef11d326cb49e723fe6e43763a0fffaa4e370ecc44'
OLD_PID = 576  # from BOARD_READONLY.json pre-deploy check


class Checks:
    def __init__(self):
        self.rows = []

    def add(self, name, ok, detail=None):
        row = {'check': name, 'pass': bool(ok)}
        if detail is not None:
            row['detail'] = detail
        self.rows.append(row)
        return row['pass']

    def require(self, name, ok, detail=None):
        if not self.add(name, ok, detail):
            raise AssertionError('check failed: ' + name)


def error_code(response):
    error = response.get('error')
    if isinstance(error, dict):
        return error.get('code') or error.get('error') or error
    if isinstance(error, str):
        return error
    return response.get('code') or response.get('errorCode')


class Peer:
    def __init__(self, connect_timeout=180):
        self.sock = None
        self.reader = None
        self.sequence = 0
        self.sid = None
        self.hello = None
        deadline = time.monotonic() + connect_timeout
        last = None
        while time.monotonic() < deadline:
            try:
                self.sock = socket.create_connection((HOST, PORT), timeout=8)
                self.reader = self.sock.makefile('rb')
                self.hello = self.call('hello', clientName='spatial-off-acceptance',
                                       clientVersion='1',
                                       maxBinaryPayloadBytes=1048576)['result']
                self.sid = self.hello.get('sessionId')
                return
            except Exception as exc:  # noqa: BLE001
                last = repr(exc)
                self.close()
                time.sleep(2)
        raise AssertionError('gateway not reachable on %s:%s: %s' % (HOST, PORT, last))

    def call_raw(self, op, **args):
        time.sleep(0.05)  # gateway documents 64 req/s; stay far below
        self.sequence += 1
        request = dict(protocol='sixmic-analysis', version=1,
                       requestId=str(self.sequence), op=op, args=args)
        if self.sid:
            request['sessionId'] = self.sid
        self.sock.sendall(json.dumps(request).encode() + b'\n')
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            line = self.reader.readline()
            if not line:
                raise AssertionError('gateway disconnected')
            response = json.loads(line)
            if response.get('requestId') == request['requestId']:
                return response
        raise AssertionError('response timeout: ' + op)

    def call(self, op, **args):
        response = self.call_raw(op, **args)
        return {'result': response.get('result'), 'response': response}

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:  # noqa: BLE001
                pass
        self.sock = self.reader = None


def parse_serial_log(path):
    """Parse the board_after_serial.txt produced with AFTER_* markers."""
    text = path.read_text(encoding='utf-8', errors='replace')
    data = {'rawText': str(path), 'sha256': {}, 'featureKeyLines': None,
            'spatialHits': {}, 'gatewayPid': None, 'gatewayLine': None,
            'sums': {}, 'releaseVersion': None}
    marker, section = None, []
    sections = {}
    for raw in text.splitlines():
        line = raw.strip()
        match = re.match(r'^AFTER_([A-Z_]+)$', line)
        if match:
            if marker:
                sections[marker] = section
            marker, section = match.group(1), []
            continue
        if marker is not None and line and not line.startswith('echo '):
            section.append(line)
    if marker:
        sections[marker] = section
    for line in sections.get('HASHES', []):
        for token, target in ((NEW_REGISTRY_SHA, '/opt/echo/registry/INTERFACE_REGISTRY.json'),
                              (GATEWAY45_SHA, '/opt/echo/bin/echo-gateway'),
                              (NEW_IMAGE_SHA, '/mnt/echo-sd/image.ub')):
            if line.startswith(token) and target in line:
                data['sha256'][target] = token
    for line in sections.get('FEATURE_ID_LINES', []):
        if line.isdigit():
            data['featureKeyLines'] = int(line)
            break
    spatial_lines = sections.get('SPATIAL', [])
    for index, line in enumerate(spatial_lines):
        if line not in REMOVED:
            continue
        for follower in spatial_lines[index + 1:]:
            if follower.isdigit():
                data['spatialHits'][line] = int(follower)
                break
    for line in sections.get('PS', []):
        match = re.match(r'^\s*(\d+)\s+\S+\s+\S+\s+\S+\s+/opt/echo/bin/echo-gateway', line)
        if match:
            data['gatewayPid'] = int(match.group(1))
            data['gatewayLine'] = line
            break
    for line in sections.get('SUMS', []):
        match = re.match(r'^([0-9a-f]{64})\s+(\S+)$', line)
        if match:
            data['sums'][match.group(2)] = match.group(1)
    for line in sections.get('VER', []):
        match = re.search(r'"version"\s*:\s*"([^"]+)"', line)
        if match:
            data['releaseVersion'] = match.group(1)
            break
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--serial-log', default='')
    parser.add_argument('--output', default='POST_DEPLOY_SERIAL.json')
    args = parser.parse_args()
    checks = Checks()
    doc = {'report': 'POST_DEPLOY.json', 'host': HOST, 'port': PORT,
           'startedAt': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
           'probe': 'feature.list + feature.start(removed ids) via sixmic-analysis v1',
           'deployed': True}
    peer = None
    try:
        peer = Peer()
        doc['hello'] = peer.hello
        checks.require('api.hello.ok', bool(peer.hello.get('sessionId')), peer.hello)

        features, cursor, pages = [], 0, 0
        while cursor is not None:
            response = peer.call_raw('feature.list', cursor=cursor, limit=8)
            checks.require('api.feature.list.page.' + str(pages),
                           response.get('status') in ('ok', 'accepted'), response.get('status'))
            page = response['result']
            features.extend(page['features'])
            cursor = page.get('nextCursor')
            pages += 1
        ids = [feature.get('featureId') for feature in features]
        doc['featureCount'] = len(features)
        doc['featureIds'] = ids
        doc['featureListSha256'] = hashlib.sha256(
            json.dumps(features, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        checks.require('api.feature.count.45', len(features) == 45, len(features))
        checks.require('api.feature.ids.canonical45', ids == EXPECTED_FEATURE_IDS, ids)
        checks.require('api.removed.spatial.ids.absent',
                       all(feature_id not in ids for feature_id in REMOVED), REMOVED)

        token = None
        claim = peer.call_raw('control.claim', leaseSeconds=60)
        if claim.get('status') in ('ok', 'accepted'):
            token = claim['result'].get('controlToken')
        checks.add('api.control.claim', bool(token),
                   {'status': claim.get('status'), 'error': error_code(claim)})

        probe_ok = True
        for feature_id in REMOVED:
            deadline = time.monotonic() + 60
            last_response = None
            while time.monotonic() < deadline:
                request = dict(featureId=feature_id, params={})
                if token:
                    request['controlToken'] = token
                response = peer.call_raw('feature.start', **request)
                last_response = response
                if response.get('status') == 'error':
                    code = error_code(response)
                    if code == 'unsupported_feature':
                        break
                    if code == 'not_ready':
                        time.sleep(2)  # gateway still initialising after restart
                        continue
                    break
                else:
                    # A removed feature must never start; stop it defensively.
                    job = (response.get('result') or {}).get('jobId')
                    if job and token:
                        peer.call_raw('feature.stop', jobId=job, controlToken=token)
                    break
            code = (error_code(last_response) if last_response else None)
            ok = last_response is not None and last_response.get('status') == 'error' \
                and code == 'unsupported_feature'
            probe_ok = probe_ok and ok
            checks.add('api.feature.start.removed.' + feature_id, ok,
                       {'status': last_response.get('status') if last_response else None,
                        'error': code})
        checks.require('api.removed.six.probes.unsupported_feature', probe_ok)
        doc['removedFeatureProbes'] = [
            row for row in checks.rows if row['check'].startswith('api.feature.start.removed.')]

        serial_data = None
        if args.serial_log:
            serial_path = Path(args.serial_log)
            if not serial_path.is_absolute():
                serial_path = R / serial_path
            if serial_path.is_file():
                serial_data = parse_serial_log(serial_path)
                doc['serial'] = serial_data
                hashes = serial_data['sha256']
                checks.require('board.after.registry.sha256',
                               hashes.get('/opt/echo/registry/INTERFACE_REGISTRY.json')
                               == NEW_REGISTRY_SHA, hashes)
                checks.require('board.after.gateway.sha256',
                               hashes.get('/opt/echo/bin/echo-gateway') == GATEWAY45_SHA,
                               hashes)
                checks.require('board.after.image.sha256',
                               hashes.get('/mnt/echo-sd/image.ub') == NEW_IMAGE_SHA, hashes)
                checks.require('board.after.feature.key.lines.45',
                               serial_data['featureKeyLines'] == 45,
                               serial_data['featureKeyLines'])
                checks.require('board.after.gateway.restarted',
                               serial_data['gatewayPid'] is not None
                               and serial_data['gatewayPid'] != OLD_PID,
                               {'beforePID': OLD_PID, 'afterPID': serial_data['gatewayPid']})
                checks.require('board.after.release.version',
                               serial_data['releaseVersion']
                               == '20261031-spatial-off-45-features-gatewayfix',
                               serial_data['releaseVersion'])
                checks.require('board.after.spatial.ids.absent',
                               set(serial_data['spatialHits']) == set(REMOVED)
                               and all(count == 0 for count in serial_data['spatialHits'].values()),
                               serial_data['spatialHits'])
                sums = serial_data['sums']
                checks.require('board.after.sums.image', sums.get('image.ub') == NEW_IMAGE_SHA, sums)
                checks.require('board.after.sums.release',
                               sums.get('ECHO_RELEASE.json') == RELEASE_SHA, sums)
            else:
                checks.add('board.after.serial.log.present', False, str(serial_path))

        doc['checks'] = checks.rows
        doc['status'] = 'PASS' if all(row['pass'] for row in checks.rows) else 'FAIL'
        doc['passed'] = sum(1 for row in checks.rows if row['pass'])
        doc['checksTotal'] = len(checks.rows)
    except Exception as exc:  # noqa: BLE001
        doc['status'] = 'ERROR'
        doc['error'] = repr(exc)[:1200]
        doc['checks'] = checks.rows
    finally:
        if peer:
            peer.close()
    doc['finishedAt'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
    (R / args.output).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n',
                                 encoding='utf-8')
    print(json.dumps({'status': doc.get('status'),
                      'featureCount': doc.get('featureCount'),
                      'passed': doc.get('passed'),
                      'checksTotal': doc.get('checksTotal'),
                      'error': doc.get('error')}, ensure_ascii=False))
    if doc.get('status') != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()