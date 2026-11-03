"""Final artifact gate for the echo_spatial_off_20261031 deployment package.

Cross-checks every produced artifact against DEPLOY_MANIFEST.json / VERIFY.json /
SD_PATCH.json / BOARD_READONLY.json and writes ARTIFACT_CHECK.json.
"""
from pathlib import Path
import hashlib, json, time

R = Path(__file__).resolve().parent
NEW_REGISTRY_SHA = 'dcbc393723513773867f6a9d96f396eb22b13386060881fdae06dda4ecb77628'
OLD_REGISTRY_SHA = '301636354dc1902426fe57e4dbd1a0a95809323d0ad2eff46cd71cad51a5bead'
OLD_GATEWAY_SHA = 'b982cecea0e9da4bf3a73dc7855d2ba41be7d22322f7a0221d8e0b07ef928920'
OLD_IMAGE_SHA = 'cba07779ad32643380a96462569dabb4f4f4b2ec62bc9476a8dd4caa1fbc4902'
NEW_IMAGE_SHA = '00b93b142f81d6db5da50eeb8b35a6e2405cbc82fa1d542ae147d7d64dcfe238'
TAR_SHA = 'c5ff16196ddca0d435954ab890a0a09582cb336c4be0b3741d64a32b825fb603'
RELEASE_SHA = '5f8f3fb0722335878db6b9e544fd1fa38a0d85e5bdcf4bf3211fdcb82e12a30c'

REQUIRED = [
    'deploy_board.sh', 'rollback_spatial_off.sh', 'registry_update.tar.gz',
    'image.ub', 'ECHO_RELEASE.json', 'DEPLOY_STEPS.md', 'DEPLOY_MANIFEST.json',
    'REGISTRY_TAR.json', 'SD_PATCH.json', 'VERIFY.json', 'BOARD_READONLY.json',
    'board_serial.ps1', 'board_readonly_serial.txt',
    'build_registry_tar.py', 'patch_sd_image.py', 'image_patch_lib.py',
    'verify_offline.py', 'make_deploy.py', 'check_artifacts.py',
    'post_deploy_verify.py', 'board_after_check.ps1',
    'registry/INTERFACE_REGISTRY.json', 'REGISTRY_TAR.json',
]


def sha_bytes(blob):
    return hashlib.sha256(blob).hexdigest()


def main():
    rows = []

    def check(name, ok, detail=None):
        row = {'check': name, 'pass': bool(ok)}
        if detail is not None:
            row['detail'] = detail
        rows.append(row)
        return row['pass']

    def load_json(name):
        return json.loads((R / name).read_text(encoding='utf-8'))

    missing = [name for name in sorted(set(REQUIRED)) if not (R / name).is_file()]
    check('package.required.files', not missing, missing or 'all present')
    if missing:
        raise SystemExit('missing required files: ' + repr(missing))

    manifest = load_json('DEPLOY_MANIFEST.json')
    verify = load_json('VERIFY.json')
    patch = load_json('SD_PATCH.json')
    board = load_json('BOARD_READONLY.json')
    tar_info = load_json('REGISTRY_TAR.json')
    release = load_json('ECHO_RELEASE.json')

    def actual_sha(name):
        return sha_bytes((R / name).read_bytes())

    check('offline.verify.status', verify.get('status') == 'PASS', verify.get('status'))
    check('offline.verify.status.in.summary',
          verify.get('summary', {}).get('verificationStatus') == 'PASS')
    check('sd.patch.verification.status',
          patch.get('verification', {}).get('status') == 'PASS',
          patch.get('verification'))
    check('sd.patch.image.sha256', actual_sha('image.ub') == NEW_IMAGE_SHA
          and patch.get('imageSHA256') == NEW_IMAGE_SHA)
    check('sd.patch.source.sha256', patch.get('sourceSHA256') == OLD_IMAGE_SHA)
    check('sd.patch.only.one.changed.entry',
          patch.get('changedRamdiskEntries') == ['opt/echo/registry/INTERFACE_REGISTRY.json']
          and patch.get('changedEntryCount') == 1)
    check('sd.patch.unchanged.entries',
          patch.get('unchangedRamdiskEntries') == patch.get('ramdiskEntries') - 1 == 2839)
    check('sd.patch.kernel.dtb.unchanged',
          patch.get('kernelAndDTBUnchanged') is True
          and patch.get('kernelAndDTBByteIdentical') is True)
    check('sd.patch.byte.identical.outside.patch',
          patch.get('byteIdenticalOutsidePatch') is True)
    check('sd.patch.gateway.unchanged', patch.get('gatewayChanged') is False)

    check('manifest.image.sha256', manifest['boardAfter']['imageSHA256'] == NEW_IMAGE_SHA
          == actual_sha('image.ub'))
    check('manifest.registry.sha256', manifest['boardAfter']['registrySHA256'] == NEW_REGISTRY_SHA
          == actual_sha('registry/INTERFACE_REGISTRY.json'))
    check('manifest.gateway.unchanged',
          manifest['boardBefore']['gatewaySHA256'] == OLD_GATEWAY_SHA
          == manifest['boardAfter']['gatewaySHA256']
          == release.get('gatewaySHA256'))
    check('manifest.tar.sha256', manifest['files']['registry_update.tar.gz']['sha256'] == TAR_SHA
          == actual_sha('registry_update.tar.gz')
          == tar_info.get('sha256'))
    check('manifest.release.sha256', manifest['files']['ECHO_RELEASE.json']['sha256'] == RELEASE_SHA
          == actual_sha('ECHO_RELEASE.json'))
    check('manifest.deploy.script.sha256',
          manifest['files']['deploy_board.sh']['sha256'] == actual_sha('deploy_board.sh'))
    check('manifest.rollback.script.sha256',
          manifest['files']['rollback_spatial_off.sh']['sha256']
          == actual_sha('rollback_spatial_off.sh'))
    check('manifest.board.before.hashes',
          manifest['boardBefore']['registrySHA256'] == OLD_REGISTRY_SHA
          and manifest['boardBefore']['imageSHA256'] == OLD_IMAGE_SHA)
    check('manifest.not.deployed', manifest.get('notDeployedYet') is True
          and manifest.get('ready', {}).get('waitingForLeadGo') is True)

    check('tar.single.file', tar_info.get('files') == ['registry/INTERFACE_REGISTRY.json'],
          tar_info.get('files'))
    check('tar.target.sha256', tar_info.get('boardTargetSHA256') == NEW_REGISTRY_SHA)

    check('release.version', release.get('version') == '20261031-spatial-off-45-features')
    check('release.featureCount', release.get('featureCount') == 45
          and release.get('softwarePathsPassed') == 45)
    check('release.image.sha256', release.get('imageSHA256') == NEW_IMAGE_SHA)
    check('release.registry.sha256', release.get('registrySHA256') == NEW_REGISTRY_SHA)
    check('release.removed.ids',
          release.get('spatialInterfaces', {}).get('removedCount') == 6
          and release.get('spatialInterfaces', {}).get('featureCountBefore') == 51
          and release.get('spatialInterfaces', {}).get('featureCountAfter') == 45)

    check('board.readonly.online', board.get('board', {}).get('online') is True)
    check('board.readonly.prestate.matches',
          board.get('prestate', {}).get('matchesExpected') is True
          and board['prestate']['actual']['registrySHA256'] == OLD_REGISTRY_SHA
          and board['prestate']['actual']['gatewaySHA256'] == OLD_GATEWAY_SHA
          and board['prestate']['actual']['imageSHA256'] == OLD_IMAGE_SHA)
    check('board.readonly.feature.count',
          board.get('featureCounts', {}).get('featureKeyLines') == 51
          and board.get('featureCounts', {}).get('featuresBefore') == 51)
    check('board.readonly.no.writes', board.get('writeAttempted') is False
          and board.get('killAttempted') is False)
    check('board.readonly.free.space',
          board['storage']['sdFreeCheckForDeploy']['passes'] is True)
    check('board.readonly.supervisor.present',
          board.get('processes', {}).get('supervisorPresent') is True)

    deploy_text = (R / 'deploy_board.sh').read_text(encoding='utf-8')
    rollback_text = (R / 'rollback_spatial_off.sh').read_text(encoding='utf-8')
    for label, needle in (
            ('old.registry.pin', OLD_REGISTRY_SHA),
            ('old.gateway.pin', OLD_GATEWAY_SHA),
            ('old.image.pin', OLD_IMAGE_SHA),
            ('new.registry.pin', NEW_REGISTRY_SHA),
            ('new.image.pin', NEW_IMAGE_SHA),
            ('tar.pin', TAR_SHA),
            ('release.pin', RELEASE_SHA),
            ('http.root', 'http://192.168.77.1:48190/'),
            ('backup.suffix', '.before-spatial-off-20261031'),
            ('gateway.restart', 'pidof echo-gateway'),
            ('sha256sums.update', 'sha256sum BOOT.BIN boot.scr system.dtb image.ub ECHO_RELEASE.json'),
            ('end.marker', '__SPATIALOFF_DONE__')):
        check('deploy.' + label, needle in deploy_text)
    for label, needle in (
            ('old.registry.pin', OLD_REGISTRY_SHA),
            ('old.gateway.pin', OLD_GATEWAY_SHA),
            ('old.image.pin', OLD_IMAGE_SHA),
            ('end.marker', '__SPATIALOFF_ROLLBACK_DONE__')):
        check('rollback.' + label, needle in rollback_text)

    steps_text = (R / 'DEPLOY_STEPS.md').read_text(encoding='utf-8')
    for label, needle in (
            ('pc.http.command', 'python -m http.server 48190 --bind 192.168.77.1'),
            ('deploy.command', 'wget -q -O /tmp/spatial-off.sh http://192.168.77.1:48190/deploy_board.sh && sh /tmp/spatial-off.sh'),
            ('rollback.command', 'wget -q -O /tmp/rollback.sh http://192.168.77.1:48190/rollback_spatial_off.sh && sh /tmp/rollback.sh'),
            ('verify.command', 'sha256sum /opt/echo/registry/INTERFACE_REGISTRY.json'),
            ('post.deploy.api.command', 'python post_deploy_verify.py --serial-log board_after_serial.txt'),
            ('post.deploy.after.check.command', '.\board_after_check.ps1'),
            ('post.deploy.unsupported.feature', 'unsupported_feature')):
        check('steps.' + label, needle in steps_text)
    post_text = (R / 'post_deploy_verify.py').read_text(encoding='utf-8')
    for label, needle in (
            ('feature.list', "'feature.list'"),
            ('unsupported_feature', 'unsupported_feature'),
            ('post.deploy.report', 'POST_DEPLOY.json'),
            ('removed.six.ids', "'spatial_grid', 'spatial_peaks'")):
        check('post.deploy.script.' + label, needle in post_text)
    after_text = (R / 'board_after_check.ps1').read_text(encoding='utf-8')
    for label, needle in (
            ('after.hashes', 'AFTER_HASHES'),
            ('after.sums', 'AFTER_SUMS'),
            ('after.version', 'AFTER_VER'),
            ('after.spatial', 'AFTER_SPATIAL')):
        check('board.after.script.' + label, needle in after_text)

    raw_log = (R / 'board_readonly_serial.txt').read_text(encoding='utf-8', errors='replace')
    check('board.log.contains.prestate',
          OLD_REGISTRY_SHA in raw_log and OLD_GATEWAY_SHA in raw_log and OLD_IMAGE_SHA in raw_log)
    check('board.log.ends.with.end.marker', '__C' in raw_log and '_END' in raw_log)

    leftovers = [p.name for p in R.iterdir()
                 if p.is_file() and (p.name.endswith('.new') or p.name.endswith('.tmp'))]
    check('package.no.temp.leftovers', not leftovers, leftovers or 'none')

    files = {}
    total = 0
    for path in sorted(R.rglob('*')):
        if not path.is_file() or path.name.startswith('.'):
            continue
        if path.relative_to(R).parts[0] in ('_work', 'backup', 'pc_release', '__pycache__'):
            continue
        blob = path.read_bytes()
        total += len(blob)
        files[path.relative_to(R).as_posix()] = {'bytes': len(blob), 'sha256': sha_bytes(blob)}
    check('package.file.count', len(files) >= 20, len(files))
    status = 'PASS' if all(row['pass'] for row in rows) else 'FAIL'
    report = {
        'report': 'ARTIFACT_CHECK.json',
        'status': status,
        'checkedAt': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'checks': {'total': len(rows), 'failed': sum(1 for row in rows if not row['pass'])},
        'rows': rows,
        'files': files,
        'packageTotalBytes': total,
        'deployed': False,
        'waitingForLeadGo': True,
    }
    (R / 'ARTIFACT_CHECK.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': status, 'checks': report['checks'],
                      'fileCount': len(files), 'packageTotalBytes': total}, indent=2))
    if status != 'PASS':
        for row in rows:
            if not row['pass']:
                print('FAILED:', json.dumps(row))
        raise SystemExit(1)


if __name__ == '__main__':
    main()