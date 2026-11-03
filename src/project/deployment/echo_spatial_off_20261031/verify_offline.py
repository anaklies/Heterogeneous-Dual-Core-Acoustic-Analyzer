"""Independent offline verification of the echo_spatial_off_20261031 package.

Re-reads image.ub, the source image.ub, registry_update.tar.gz, ECHO_RELEASE.json
and deploy_board.sh from disk, re-proves the ramdisk/FIT patch and writes
VERIFY.json. This does not touch the board.
"""
from pathlib import Path
import gzip, hashlib, io, json, tarfile, time

from image_patch_lib import (EXPECTED_FEATURE_IDS, REMOVED_FEATURE_IDS, TARGET_ENTRY,
                             build_patched_image, sha, verify_patch)

R = Path(__file__).resolve().parent
PROJECT = R.parents[1]
SOURCE = PROJECT / 'deployment/echo_stipa_8s_progress_20261030/image.ub'
SOURCE_SHA = 'cba07779ad32643380a96462569dabb4f4f4b2ec62bc9476a8dd4caa1fbc4902'
OLD_REGISTRY_SHA = '301636354dc1902426fe57e4dbd1a0a95809323d0ad2eff46cd71cad51a5bead'
OLD_IMAGE_SHA = 'cba07779ad32643380a96462569dabb4f4f4b2ec62bc9476a8dd4caa1fbc4902'
NEW_REGISTRY_SHA = 'dcbc393723513773867f6a9d96f396eb22b13386060881fdae06dda4ecb77628'
OLD_GATEWAY_SHA = 'b982cecea0e9da4bf3a73dc7855d2ba41be7d22322f7a0221d8e0b07ef928920'
HTTP_ROOT = 'http://192.168.77.1:48190'


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


def rel(path):
    try:
        return path.resolve().relative_to(PROJECT).as_posix()
    except ValueError:
        return str(path)


def main():
    checks = Checks()
    summary = {}
    try:
        source = SOURCE.read_bytes()
        output = (R / 'image.ub').read_bytes()
        registry = (R / 'registry/INTERFACE_REGISTRY.json').read_bytes()
        tar_bytes = (R / 'registry_update.tar.gz').read_bytes()
        release_bytes = (R / 'ECHO_RELEASE.json').read_bytes()
        deploy_text = (R / 'deploy_board.sh').read_text(encoding='utf-8')
        rollback_text = (R / 'rollback_spatial_off.sh').read_text(encoding='utf-8')
        patch_info = json.loads((R / 'SD_PATCH.json').read_text(encoding='utf-8'))
        tar_info = json.loads((R / 'REGISTRY_TAR.json').read_text(encoding='utf-8'))

        # 1. artifact hashes and reproducibility.
        checks.require('artifact.image.sha256', sha(output) == patch_info['imageSHA256'],
                       {'sha256': sha(output), 'bytes': len(output)})
        checks.require('artifact.source.sha256', sha(source) == SOURCE_SHA, sha(source))
        checks.require('artifact.registry.sha256', sha(registry) == NEW_REGISTRY_SHA, sha(registry))
        rebuilt, _ = build_patched_image(source, registry, SOURCE_SHA, OLD_REGISTRY_SHA)
        checks.require('image.reproducible.fromSourceAndRegistry', rebuilt == output,
                       {'rebuiltSHA256': sha(rebuilt)})

        # 2. FIT/ramdisk structural + byte-level proof (kernel/dtb/other entries unchanged).
        result = verify_patch(source, output, registry,
                              expected_source_sha=SOURCE_SHA,
                              expected_output_sha=sha(output),
                              expected_old_registry_sha=OLD_REGISTRY_SHA,
                              expected_new_registry_sha=NEW_REGISTRY_SHA)
        summary = result['summary']
        checks.require('fit.verifyPatch.status', result['status'] == 'PASS',
                       {'status': result['status'], 'checks': len(result['checks'])})

        # 3. Registry semantic checks (45 features, six spatial ids gone).
        parsed = json.loads(registry.decode('utf-8'))
        ids = [feature['featureId'] for feature in parsed['features']]
        raw_text = registry.decode('utf-8')
        checks.require('registry.feature.count.45', len(ids) == 45, len(ids))
        checks.require('registry.ids.match.canonical45', ids == EXPECTED_FEATURE_IDS,
                       {'count': len(ids)})
        checks.require('registry.removed.spatial.ids.absent',
                       all(feature_id not in raw_text for feature_id in REMOVED_FEATURE_IDS),
                       REMOVED_FEATURE_IDS)
        checks.require('registry.quoted.featureId.lines.45',
                       sum(1 for line in raw_text.splitlines() if '"featureId":' in line) == 45)

        # 4. registry_update.tar.gz structure and content.
        checks.require('tar.sha256', sha(tar_bytes) == tar_info['sha256'],
                       {'sha256': sha(tar_bytes), 'bytes': len(tar_bytes)})
        names, contents = [], {}
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode='r:gz') as tar:
            for member in tar.getmembers():
                names.append(member.name)
                contents[member.name] = tar.extractfile(member).read()
        checks.require('tar.members.single.registry.file',
                       names == ['registry/INTERFACE_REGISTRY.json'], names)
        checks.require('tar.registry.matches', contents[names[0]] == registry,
                       {'member': names[0], 'sha256': sha(contents[names[0]])})

        # 5. ECHO_RELEASE.json content matches the built artifacts.
        release = json.loads(release_bytes.decode('utf-8'))
        checks.require('release.version', release.get('version') == '20261031-spatial-off-45-features',
                       release.get('version'))
        checks.require('release.featureCount', release.get('featureCount') == 45,
                       release.get('featureCount'))
        checks.require('release.registrySHA256', release.get('registrySHA256') == NEW_REGISTRY_SHA)
        checks.require('release.gatewaySHA256', release.get('gatewaySHA256') == OLD_GATEWAY_SHA,
                       {'gatewayChanged': False})
        checks.require('release.imageSHA256', release.get('imageSHA256') == sha(output))
        checks.require('release.gatewayChanged.false', release.get('gatewayChanged') is False)
        checks.require('release.removed.six.ids',
                       release.get('spatialInterfaces', {}).get('removedFeatureIds')
                       == REMOVED_FEATURE_IDS)
        release_sha = sha(release_bytes)

        # 6. deploy_board.sh pins exactly these artifacts, backs up old state and only
        #    waits for go (it is not executed by this verification).
        pins = [
            ('pin.old.registry', f"echo '{OLD_REGISTRY_SHA}  /opt/echo/registry/INTERFACE_REGISTRY.json'"),
            ('pin.old.gateway', f"echo '{OLD_GATEWAY_SHA}  /opt/echo/bin/echo-gateway'"),
            ('pin.old.image', f"echo '{OLD_IMAGE_SHA}  /mnt/echo-sd/image.ub'"),
            ('pin.tar', f"echo '{tar_info['sha256']}  /tmp/spatial-off/registry_update.tar.gz'"),
            ('pin.new.registry', f"echo '{NEW_REGISTRY_SHA}  /opt/echo/registry/INTERFACE_REGISTRY.json'"),
            ('pin.new.image', f"echo '{sha(output)}  /mnt/echo-sd/image.ub.spatial-off.new'"),
            ('pin.new.image.after.move', f"echo '{sha(output)}  /mnt/echo-sd/image.ub'"),
            ('pin.new.release.tmp',
             f"echo '{release_sha}  /mnt/echo-sd/ECHO_RELEASE.json.spatial-off.new'"),
            ('pin.new.release.after.move', f"echo '{release_sha}  /mnt/echo-sd/ECHO_RELEASE.json'"),
        ]
        for name, needle in pins:
            checks.require(name, needle in deploy_text, needle)
        checks.require('deploy.extract.registry.to.opt.echo',
                       'tar -xzf /tmp/spatial-off/registry_update.tar.gz -C /opt/echo' in deploy_text)
        checks.require('deploy.http.root', HTTP_ROOT + '/registry_update.tar.gz' in deploy_text
                       and HTTP_ROOT + '/image.ub' in deploy_text)
        checks.require('deploy.backups.registry',
                       'INTERFACE_REGISTRY.json.before-spatial-off-20261031' in deploy_text)
        checks.require('deploy.backups.gateway',
                       'echo-gateway.before-spatial-off-20261031' in deploy_text)
        checks.require('deploy.backups.image',
                       'image.ub.before-spatial-off-20261031' in deploy_text)
        checks.require('deploy.backups.release',
                       'ECHO_RELEASE.json.before-spatial-off-20261031' in deploy_text)
        checks.require('deploy.sha256sums.updated',
                       'sha256sum BOOT.BIN boot.scr system.dtb image.ub ECHO_RELEASE.json' in deploy_text)
        checks.require('deploy.sync', 'sync' in deploy_text)
        checks.require('deploy.free.space.guard',
                       'df -k /mnt/echo-sd' in deploy_text and '__SPATIALOFF_SPACE_OK__' in deploy_text)
        checks.require('deploy.gateway.supervisor.restart',
                       'pidof echo-gateway' in deploy_text and 'kill' in deploy_text)
        checks.require('deploy.gateway.binary.not.downloaded',
                       HTTP_ROOT + '/echo-gateway' not in deploy_text)
        checks.require('deploy.markers',
                       all(marker in deploy_text for marker in (
                           '__SPATIALOFF_START__', '__SPATIALOFF_PRESTATE_OK__',
                           '__SPATIALOFF_SPACE_OK__', '__SPATIALOFF_DOWNLOAD_OK__',
                           '__SPATIALOFF_SYNC_OK__',
                           '__SPATIALOFF_DONE__', '__SPATIALOFF_FAILED__')))
        checks.require('rollback.restores.backups',
                       all(suffix in rollback_text for suffix in (
                           'INTERFACE_REGISTRY.json.before-spatial-off-20261031',
                           'image.ub.before-spatial-off-20261031')))
        checks.require('rollback.verifies.old.hashes',
                       OLD_REGISTRY_SHA in rollback_text and OLD_IMAGE_SHA in rollback_text)

        # 7. Gateway binary in the package reference is unchanged (not shipped/uploaded).
        package_gateway = (PROJECT / 'deployment/echo_stipa_8s_progress_20261030/gateway/echo-gateway')
        checks.require('gateway.binary.unchanged',
                       sha(package_gateway.read_bytes()) == OLD_GATEWAY_SHA,
                       {'sha256': OLD_GATEWAY_SHA, 'changed': False})

        summary = dict(summary)
        summary.update({
            'verificationStatus': 'PASS',
            'verifiedAt': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
            'artifacts': {
                'registry_update.tar.gz': {'sha256': sha(tar_bytes), 'bytes': len(tar_bytes)},
                'image.ub': {'sha256': sha(output), 'bytes': len(output)},
                'ECHO_RELEASE.json': {'sha256': release_sha, 'bytes': len(release_bytes)},
                'deploy_board.sh': {'sha256': sha(deploy_text.encode('utf-8'))},
                'rollback_spatial_off.sh': {'sha256': sha(rollback_text.encode('utf-8'))},
                'registry/INTERFACE_REGISTRY.json': {'sha256': sha(registry), 'bytes': len(registry)},
            },
            'checks': {'total': len(checks.rows) + len(result['checks']),
                       'failed': 0},
        })
    except AssertionError as error:
        summary = {'verificationStatus': 'FAIL', 'error': str(error),
                   'checks': len(checks.rows)}
    report = {
        'report': 'VERIFY.json',
        'status': summary.get('verificationStatus', 'FAIL'),
        'summary': summary,
        'checks': checks.rows,
        'fitChecks': result['checks'] if 'result' in locals() else [],
    }
    (R / 'VERIFY.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'summary': summary}, indent=2))
    if report['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
