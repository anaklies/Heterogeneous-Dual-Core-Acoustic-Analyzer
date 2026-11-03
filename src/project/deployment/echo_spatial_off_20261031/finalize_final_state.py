"""Finalize the echo_spatial_off_20261031 package at the recovered 45-feature state.

Authoritative final state (2026-10-31, deployed by Lead and verified read-only):
  registry_update.tar.gz     c5ff16196ddca0d435954ab890a0a09582cb336c4be0b3741d64a32b825fb603
  image.ub (in package)      646631abdd1add91b96ea28d2553eafeac647c42267386e03fddaf17613b6565
  gateway (echo-gateway)     5d4b0291146f71fd0f5e39ef11d326cb49e723fe6e43763a0fffaa4e370ecc44
  ECHO_RELEASE.json          f51249c8b9118139b54210d11f4c0bc1dd691f9280e9bd8f012125492d697066 (Lead owned)
  registry/INTERFACE_REGISTRY.json dcbc393723513773867f6a9d96f396eb22b13386060881fdae06dda4ecb77628
Writes: SD_PATCH.json, VERIFY.json, deploy_board.sh, rollback_spatial_off.sh,
        DEPLOY_MANIFEST.json, ARTIFACT_CHECK.json.
"""
from pathlib import Path
import hashlib, json, time

R = Path(__file__).resolve().parent
PROJECT = R.parents[1]
TAR_SHA = 'c5ff16196ddca0d435954ab890a0a09582cb336c4be0b3741d64a32b825fb603'
REG_SHA = 'dcbc393723513773867f6a9d96f396eb22b13386060881fdae06dda4ecb77628'
GW_SHA = '5d4b0291146f71fd0f5e39ef11d326cb49e723fe6e43763a0fffaa4e370ecc44'
OLD_GW_SHA = 'b982cecea0e9da4bf3a73dc7855d2ba41be7d22322f7a0221d8e0b07ef928920'
IMAGE_SHA = '646631abdd1add91b96ea28d2553eafeac647c42267386e03fddaf17613b6565'
REGISTRY_ONLY_IMAGE_SHA = '00b93b142f81d6db5da50eeb8b35a6e2405cbc82fa1d542ae147d7d64dcfe238'
ORIGINAL_IMAGE_SHA = 'cba07779ad32643380a96462569dabb4f4f4b2ec62bc9476a8dd4caa1fbc4902'
RELEASE_SHA = 'f51249c8b9118139b54210d11f4c0bc1dd691f9280e9bd8f012125492d697066'
RELEASE_VERSION = '20261031-spatial-off-45-features-gatewayfix'
OLD_REGISTRY_SHA = '301636354dc1902426fe57e4dbd1a0a95809323d0ad2eff46cd71cad51a5bead'
OLD_RELEASE_SHA = '5e73d838eda15403f92a39c7e1b4a493b65307f4257f93199cfd842bf94500ee'
HTTP_ROOT = 'http://192.168.77.1:48190'
BACKUP_SUFFIX = '.before-spatial-off-20261031'
GW_BACKUP_SUFFIX = '.before-gateway45-20261031'


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def fsha(name):
    return sha((R / name).read_bytes())


def main():
    verify_final = json.loads((R / 'FINAL_IMAGE_VERIFY.json').read_text(encoding='utf-8'))
    if verify_final.get('status') != 'PASS':
        raise SystemExit('FINAL_IMAGE_VERIFY.json is not PASS')
    release = json.loads((R / 'ECHO_RELEASE.json').read_text(encoding='utf-8'))
    if fsha('image.ub') != IMAGE_SHA or fsha('echo-gateway') != GW_SHA:
        raise SystemExit('image/gateway hashes do not match the final verified artifacts')
    if fsha('ECHO_RELEASE.json') != RELEASE_SHA:
        raise SystemExit('ECHO_RELEASE.json is not the Lead-updated final release')
    if fsha('registry/INTERFACE_REGISTRY.json') != REG_SHA:
        raise SystemExit('registry is not the canonical 45-feature copy')
    if fsha('registry_update.tar.gz') != TAR_SHA:
        raise SystemExit('registry tar sha mismatch')

    sd_patch = {
        'source': 'deployment/echo_stipa_8s_progress_20261030/image.ub',
        'sourceSHA256': ORIGINAL_IMAGE_SHA,
        'sourceBytes': (PROJECT / 'deployment/echo_stipa_8s_progress_20261030/image.ub').stat().st_size,
        'imageSHA256': IMAGE_SHA,
        'bytes': (R / 'image.ub').stat().st_size,
        'changedRamdiskEntries': ['opt/echo/registry/INTERFACE_REGISTRY.json',
                                  'opt/echo/bin/echo-gateway'],
        'changedEntryCount': 2,
        'ramdiskEntries': 2840,
        'unchangedRamdiskEntries': 2838,
        'oldRegistrySHA256': OLD_REGISTRY_SHA,
        'newRegistrySHA256': REG_SHA,
        'oldGatewaySHA256': OLD_GW_SHA,
        'newGatewaySHA256': GW_SHA,
        'gatewayChanged': True,
        'kernelSHA256': '91f6859abac029d1a6922996ef6b166cfdc9806a7dac4548d2857d1017701c86',
        'dtbSHA256': '8395c6e2167ce5c5fef110362c9be4bce24bf931da44b838ebaf2fbb984410f7',
        'kernelAndDTBUnchanged': True,
        'otherRamdiskEntriesByteIdentical': True,
        'byteIdenticalOutsidePatch': True,
        'bitstreamChanged': False,
        'bootChanged': False,
        'intermediateImageSHA256': REGISTRY_ONLY_IMAGE_SHA,
        'intermediateImageNote': ('first attempt changed only the registry (00b93b14); the old '
                                  'gateway b982 rejected the 45-feature registry, so the final '
                                  'image additionally carries the rebuilt 45-feature gateway'),
        'verification': {'status': 'PASS', 'report': 'FINAL_IMAGE_VERIFY.json',
                         'checks': len(verify_final.get('checks', []))},
        'proof': verify_final.get('summary', {}).get('proof'),
    }
    (R / 'SD_PATCH.json').write_text(json.dumps(sd_patch, indent=2) + '\n', encoding='utf-8')

    deploy = f'''#!/bin/sh
# echo_spatial_off_20261031 - spatial interfaces off (45 features) + 45-feature gateway.
# Final state: registry {REG_SHA[:12]}..., gateway {GW_SHA[:12]}..., image {IMAGE_SHA[:12]}...
# Run on the board (COM6 root console):
#   wget -q -O /tmp/spatial-off45.sh {HTTP_ROOT}/deploy_board.sh && sh /tmp/spatial-off45.sh
# The script is idempotent: if the board is already in the final state it only verifies.
# Changes  : /opt/echo/registry/INTERFACE_REGISTRY.json (51/45 -> 45 features),
#            /opt/echo/bin/echo-gateway (45-feature build),
#            /mnt/echo-sd/image.ub (ramdisk registry + gateway only),
#            /mnt/echo-sd/ECHO_RELEASE.json, /mnt/echo-sd/SHA256SUMS.
# Unchanged: BOOT.BIN, boot.scr, system.dtb, kernel, dtb, bitstream.
# Failure  : files replaced before the final check are backed up on the board; recover with
#            rollback_spatial_off.sh. A gateway restart takes up to 60 s after echo-runtime start.
set -eu
trap 'rc=$?; if [ "$rc" -ne 0 ]; then echo __SPATIALOFF45_FAILED__; echo "rollback: wget -q -O /tmp/rollback.sh {HTTP_ROOT}/rollback_spatial_off.sh && sh /tmp/rollback.sh"; fi' EXIT
echo __SPATIALOFF45_START__
R=$(sha256sum /opt/echo/registry/INTERFACE_REGISTRY.json | cut -d" " -f1)
G=$(sha256sum /opt/echo/bin/echo-gateway | cut -d" " -f1)
I=$(sha256sum /mnt/echo-sd/image.ub | cut -d" " -f1)
E=$(sha256sum /mnt/echo-sd/ECHO_RELEASE.json | cut -d" " -f1)
echo "current registry=$R gateway=$G image=$I release=$E"
if [ "$R" = "{REG_SHA}" ] && [ "$G" = "{GW_SHA}" ] && [ "$I" = "{IMAGE_SHA}" ] && [ "$E" = "{RELEASE_SHA}" ]; then
  echo __SPATIALOFF45_ALREADY_DONE__
  sha256sum /opt/echo/bin/echo-gateway /opt/echo/registry/INTERFACE_REGISTRY.json /mnt/echo-sd/image.ub
  grep -c '"featureId":' /opt/echo/registry/INTERFACE_REGISTRY.json
  ps | grep echo-gateway | grep -v grep
  echo __SPATIALOFF45_DONE__
  exit 0
fi
echo __SPATIALOFF45_NEEDS_UPDATE__
case "$R" in "{OLD_REGISTRY_SHA}"|"{REG_SHA}") ;; *) echo "unexpected registry $R"; exit 1;; esac
case "$G" in "{OLD_GW_SHA}"|"{GW_SHA}") ;; *) echo "unexpected gateway $G"; exit 1;; esac
case "$I" in "{ORIGINAL_IMAGE_SHA}"|"{REGISTRY_ONLY_IMAGE_SHA}"|"{IMAGE_SHA}") ;; *) echo "unexpected image $I"; exit 1;; esac
FREE_KB=$(df -k /mnt/echo-sd | awk 'NR==2 {{print $4}}')
if [ -z "$FREE_KB" ] || [ "$FREE_KB" -lt 340000 ]; then echo "not enough space on /mnt/echo-sd: $FREE_KB KB"; exit 1; fi
rm -f /mnt/echo-sd/image.ub.spatial-off45.new /mnt/echo-sd/ECHO_RELEASE.json.spatial-off45.new
cp -p /opt/echo/registry/INTERFACE_REGISTRY.json /opt/echo/registry/INTERFACE_REGISTRY.json{GW_BACKUP_SUFFIX}
cp -p /opt/echo/bin/echo-gateway /opt/echo/bin/echo-gateway{GW_BACKUP_SUFFIX}
cp -p /mnt/echo-sd/image.ub /mnt/echo-sd/image.ub{GW_BACKUP_SUFFIX}
cp -p /mnt/echo-sd/ECHO_RELEASE.json /mnt/echo-sd/ECHO_RELEASE.json{GW_BACKUP_SUFFIX}
cp -p /mnt/echo-sd/SHA256SUMS /mnt/echo-sd/SHA256SUMS{GW_BACKUP_SUFFIX}
echo __SPATIALOFF45_BACKUPS_OK__
mkdir -p /tmp/spatial-off45
wget -q -T 20 -O /tmp/spatial-off45/registry_update.tar.gz {HTTP_ROOT}/registry_update.tar.gz
echo '{TAR_SHA}  /tmp/spatial-off45/registry_update.tar.gz' | sha256sum -c -
wget -q -T 20 -O /tmp/spatial-off45/echo-gateway {HTTP_ROOT}/echo-gateway
echo '{GW_SHA}  /tmp/spatial-off45/echo-gateway' | sha256sum -c -
wget -q -T 30 -O /mnt/echo-sd/image.ub.spatial-off45.new {HTTP_ROOT}/image.ub
echo '{IMAGE_SHA}  /mnt/echo-sd/image.ub.spatial-off45.new' | sha256sum -c -
wget -q -T 10 -O /mnt/echo-sd/ECHO_RELEASE.json.spatial-off45.new {HTTP_ROOT}/ECHO_RELEASE.json
echo '{RELEASE_SHA}  /mnt/echo-sd/ECHO_RELEASE.json.spatial-off45.new' | sha256sum -c -
echo __SPATIALOFF45_DOWNLOAD_OK__
tar -xzf /tmp/spatial-off45/registry_update.tar.gz -C /opt/echo
echo '{REG_SHA}  /opt/echo/registry/INTERFACE_REGISTRY.json' | sha256sum -c -
chmod 755 /tmp/spatial-off45/echo-gateway
mv /tmp/spatial-off45/echo-gateway /opt/echo/bin/echo-gateway
echo '{GW_SHA}  /opt/echo/bin/echo-gateway' | sha256sum -c -
mv /mnt/echo-sd/image.ub.spatial-off45.new /mnt/echo-sd/image.ub
mv /mnt/echo-sd/ECHO_RELEASE.json.spatial-off45.new /mnt/echo-sd/ECHO_RELEASE.json
echo '{IMAGE_SHA}  /mnt/echo-sd/image.ub' | sha256sum -c -
echo '{RELEASE_SHA}  /mnt/echo-sd/ECHO_RELEASE.json' | sha256sum -c -
echo __SPATIALOFF45_FILES_OK__
cd /mnt/echo-sd
sha256sum BOOT.BIN boot.scr system.dtb image.ub ECHO_RELEASE.json > SHA256SUMS.new
mv SHA256SUMS.new SHA256SUMS
sync
echo __SPATIALOFF45_SYNC_OK__
/opt/echo/bin/echo-runtime stop 2>/dev/null || true
sleep 2
/opt/echo/bin/echo-runtime start
n=0
while [ "$n" -lt 30 ]; do
  sleep 2; n=$((n+1))
  if pidof echo-gateway >/dev/null 2>&1; then break; fi
done
echo __SPATIALOFF45_RUNTIME_OK__ after_seconds=$((n*2))
ps | grep echo-gateway | grep -v grep
sha256sum /opt/echo/bin/echo-gateway /opt/echo/registry/INTERFACE_REGISTRY.json /mnt/echo-sd/image.ub /mnt/echo-sd/ECHO_RELEASE.json
grep -c '"featureId":' /opt/echo/registry/INTERFACE_REGISTRY.json
echo __SPATIALOFF45_DONE__
'''
    (R / 'deploy_board.sh').write_text(deploy, encoding='utf-8', newline='\n')

    rollback = f'''#!/bin/sh
# Roll back echo_spatial_off_20261031 to the 2026-10-30 working state (51 features,
# gateway b982, image cba07779) using the on-board backups made by the first deploy.
# Run on the board (COM6 root console):
#   wget -q -O /tmp/rollback.sh {HTTP_ROOT}/rollback_spatial_off.sh && sh /tmp/rollback.sh
set -eu
echo __SPATIALOFF_ROLLBACK_START__
for f in /opt/echo/registry/INTERFACE_REGISTRY.json{BACKUP_SUFFIX} \
         /opt/echo/bin/echo-gateway{BACKUP_SUFFIX} \
         /mnt/echo-sd/image.ub{BACKUP_SUFFIX} \
         /mnt/echo-sd/ECHO_RELEASE.json{BACKUP_SUFFIX} \
         /mnt/echo-sd/SHA256SUMS{BACKUP_SUFFIX}; do
  test -f "$f" || {{ echo "missing backup: $f"; exit 1; }}
done
cp -p /opt/echo/registry/INTERFACE_REGISTRY.json{BACKUP_SUFFIX} /opt/echo/registry/INTERFACE_REGISTRY.json
cp -p /opt/echo/bin/echo-gateway{BACKUP_SUFFIX} /opt/echo/bin/echo-gateway
cp -p /mnt/echo-sd/image.ub{BACKUP_SUFFIX} /mnt/echo-sd/image.ub
cp -p /mnt/echo-sd/ECHO_RELEASE.json{BACKUP_SUFFIX} /mnt/echo-sd/ECHO_RELEASE.json
cp -p /mnt/echo-sd/SHA256SUMS{BACKUP_SUFFIX} /mnt/echo-sd/SHA256SUMS
sync
echo '{OLD_REGISTRY_SHA}  /opt/echo/registry/INTERFACE_REGISTRY.json' | sha256sum -c -
echo '{OLD_GW_SHA}  /opt/echo/bin/echo-gateway' | sha256sum -c -
echo '{ORIGINAL_IMAGE_SHA}  /mnt/echo-sd/image.ub' | sha256sum -c -
/opt/echo/bin/echo-runtime stop 2>/dev/null || true
sleep 2
/opt/echo/bin/echo-runtime start
sleep 6
ps | grep echo-gateway | grep -v grep
grep -c '"featureId":' /opt/echo/registry/INTERFACE_REGISTRY.json
sha256sum /opt/echo/bin/echo-gateway /opt/echo/registry/INTERFACE_REGISTRY.json /mnt/echo-sd/image.ub
echo __SPATIALOFF_ROLLBACK_DONE__
'''
    (R / 'rollback_spatial_off.sh').write_text(rollback, encoding='utf-8', newline='\n')

    manifest = {
        'date': '2026-10-31',
        'package': 'deployment/echo_spatial_off_20261031',
        'purpose': 'device-side shutdown of the six spatial interfaces (51 -> 45 features)',
        'status': 'DEPLOYED_AND_VERIFIED',
        'deployedAt': '2026-10-31T21:13:00+08:00',
        'deployedBy': 'lead (recovery) with board-deploy verification',
        'target': {'board': '192.168.77.2', 'pcHttpRoot': HTTP_ROOT},
        'files': {
            'registry_update.tar.gz': {'sha256': TAR_SHA,
                                       'bytes': (R / 'registry_update.tar.gz').stat().st_size},
            'image.ub': {'sha256': IMAGE_SHA, 'bytes': (R / 'image.ub').stat().st_size},
            'echo-gateway': {'sha256': GW_SHA, 'bytes': (R / 'echo-gateway').stat().st_size},
            'ECHO_RELEASE.json': {'sha256': RELEASE_SHA,
                                  'bytes': (R / 'ECHO_RELEASE.json').stat().st_size},
            'deploy_board.sh': {'sha256': fsha('deploy_board.sh')},
            'rollback_spatial_off.sh': {'sha256': fsha('rollback_spatial_off.sh')},
        },
        'boardBefore': {'registrySHA256': OLD_REGISTRY_SHA, 'registryFeatures': 51,
                        'gatewaySHA256': OLD_GW_SHA, 'imageSHA256': ORIGINAL_IMAGE_SHA},
        'boardAfter': {'registrySHA256': REG_SHA, 'registryFeatures': 45,
                       'gatewaySHA256': GW_SHA, 'imageSHA256': IMAGE_SHA,
                       'releaseSHA256': RELEASE_SHA, 'releaseVersion': RELEASE_VERSION},
        'gatewayFix': {
            'required': True,
            'reason': ('legacy gateway b982 hard-requires exactly 51 registry features '
                       '(feature_runtime.c init) and hardcodes feature.list total=51; a '
                       '45-feature registry needs the rebuilt GW_FEATURE_COUNT=45 gateway'),
            'newGatewaySHA256': GW_SHA,
            'source': 'deployment/echo_interface_guard_20261026/gateway (GW_FEATURE_COUNT=45)',
            'buildLog': 'deployment/echo_interface_guard_20261026/build/arm/echo-gateway',
            'imageContainsNewGateway': True,
            'nextBootSafe': True,
        },
        'boardBackups': [
            '/opt/echo/registry/INTERFACE_REGISTRY.json' + BACKUP_SUFFIX,
            '/opt/echo/bin/echo-gateway' + BACKUP_SUFFIX,
            '/mnt/echo-sd/image.ub' + BACKUP_SUFFIX,
            '/mnt/echo-sd/ECHO_RELEASE.json' + BACKUP_SUFFIX,
            '/mnt/echo-sd/SHA256SUMS' + BACKUP_SUFFIX,
            '/opt/echo/bin/echo-gateway.before-gateway-fix-20261031',
            '/mnt/echo-sd/image.ub.before-gateway-fix-20261031',
        ],
        'deployCommand': ('wget -q -O /tmp/spatial-off45.sh ' + HTTP_ROOT
                          + '/deploy_board.sh && sh /tmp/spatial-off45.sh'),
        'rollbackCommand': ('wget -q -O /tmp/rollback.sh ' + HTTP_ROOT
                            + '/rollback_spatial_off.sh && sh /tmp/rollback.sh'),
        'verification': {
            'finalImage': 'FINAL_IMAGE_VERIFY.json',
            'package': 'VERIFY.json',
            'sdPatch': 'SD_PATCH.json',
            'registryTar': 'REGISTRY_TAR.json',
            'boardReadonlyBefore': 'BOARD_READONLY.json',
            'afterSerial': 'board_after_serial.txt',
            'postDeploy': 'POST_DEPLOY.json',
            'postDeploySerial': 'POST_DEPLOY_SERIAL.json',
            'postDeployPc': 'POST_DEPLOY_PC.json',
            'deployLog': 'BOARD_DEPLOY.log',
            'recoveryLog': 'BOARD_RECOVERY.log',
            'gatewayFixNote': 'GATEWAY_FIX_20261031.md',
            'artifactCheck': 'ARTIFACT_CHECK.json',
            'deploySteps': 'DEPLOY_STEPS.md',
        },
        'ready': {'prepared': True, 'deployed': True},
    }
    (R / 'DEPLOY_MANIFEST.json').write_text(
        json.dumps(manifest, indent=2) + '\n', encoding='utf-8')

    tar_info = json.loads((R / 'REGISTRY_TAR.json').read_text(encoding='utf-8'))
    serial = json.loads((R / 'POST_DEPLOY_SERIAL.json').read_text(encoding='utf-8'))
    deploy_text = (R / 'deploy_board.sh').read_text(encoding='utf-8')
    rollback_text = (R / 'rollback_spatial_off.sh').read_text(encoding='utf-8')
    checks = []

    def check(name, ok, detail=None):
        row = {'check': name, 'pass': bool(ok)}
        if detail is not None:
            row['detail'] = detail
        checks.append(row)
        return row['pass']

    def require(name, ok, detail=None):
        if not check(name, ok, detail):
            raise AssertionError(name)

    try:
        require('finalImage.verify.status', verify_final.get('status') == 'PASS')
        require('finalImage.changed.entries',
                verify_final['summary']['changedRamdiskEntries']
                == ['opt/echo/registry/INTERFACE_REGISTRY.json', 'opt/echo/bin/echo-gateway'])
        require('finalImage.unchanged.entries',
                verify_final['summary']['unchangedRamdiskEntries'] == 2838)
        require('finalImage.sha256', fsha('image.ub') == IMAGE_SHA)
        require('gateway.sha256', fsha('echo-gateway') == GW_SHA)
        require('gateway.elf.arm', (R / 'echo-gateway').read_bytes()[:5] == b'\x7fELF\x01')
        require('registry.sha256', fsha('registry/INTERFACE_REGISTRY.json') == REG_SHA)
        require('tar.sha256', fsha('registry_update.tar.gz') == TAR_SHA
                and tar_info.get('sha256') == TAR_SHA)
        require('tar.single.file',
                tar_info.get('files') == ['registry/INTERFACE_REGISTRY.json'])
        require('release.sha256', fsha('ECHO_RELEASE.json') == RELEASE_SHA)
        require('release.version', release.get('version') == RELEASE_VERSION)
        require('release.gateway',
                release.get('gatewaySHA256') == GW_SHA
                and release.get('gatewayHotfix') == '20261031-spatial-off-featurecount-45-1')
        require('release.image', release.get('imageSHA256') == IMAGE_SHA)
        require('release.registry', release.get('registrySHA256') == REG_SHA)
        require('release.featureCount', release.get('featureCount') == 45
                and release.get('spatialInterfaces', {}).get('removedCount') == 6)
        for label, needle in (
                ('old.registry.pin', OLD_REGISTRY_SHA),
                ('old.gateway.pin', OLD_GW_SHA),
                ('old.image.pin', ORIGINAL_IMAGE_SHA),
                ('registry.pin', REG_SHA),
                ('gateway.pin', GW_SHA),
                ('image.pin', IMAGE_SHA),
                ('release.pin', RELEASE_SHA),
                ('tar.pin', TAR_SHA),
                ('http.root', HTTP_ROOT),
                ('gateway45.backup.suffix', GW_BACKUP_SUFFIX),
                ('runtime.restart', '/opt/echo/bin/echo-runtime start'),
                ('idempotent.already.done', '__SPATIALOFF45_ALREADY_DONE__'),
                ('done.marker', '__SPATIALOFF45_DONE__'),
                ('sha256sums.update',
                 'sha256sum BOOT.BIN boot.scr system.dtb image.ub ECHO_RELEASE.json')):
            require('deploy.' + label, needle in deploy_text)
        for label, needle in (
                ('old.registry.pin', OLD_REGISTRY_SHA),
                ('old.gateway.pin', OLD_GW_SHA),
                ('old.image.pin', ORIGINAL_IMAGE_SHA),
                ('old.release.backup', '.before-spatial-off-20261031'),
                ('runtime.restart', '/opt/echo/bin/echo-runtime start'),
                ('done.marker', '__SPATIALOFF_ROLLBACK_DONE__')):
            require('rollback.' + label, needle in rollback_text)
        require('serial.after.status', serial.get('status') == 'PASS',
                {'checks': serial.get('checksTotal')})
        serial_data = serial.get('serial', {})
        require('serial.after.hashes',
                serial_data.get('sha256', {}).get('/opt/echo/registry/INTERFACE_REGISTRY.json') == REG_SHA
                and serial_data.get('sha256', {}).get('/opt/echo/bin/echo-gateway') == GW_SHA
                and serial_data.get('sha256', {}).get('/mnt/echo-sd/image.ub') == IMAGE_SHA)
        require('serial.after.feature.lines', serial_data.get('featureKeyLines') == 45)
        require('serial.after.spatial.absent',
                serial_data.get('spatialHits') == {fid: 0 for fid in (
                    'spatial_interface', 'directed_das', 'full_das', 'band_das',
                    'spatial_grid', 'spatial_peaks')})
        require('serial.after.gateway.process', bool(serial_data.get('gatewayPid')))
        require('serial.after.sha256sums',
                serial_data.get('sums', {}).get('image.ub') == IMAGE_SHA
                and serial_data.get('sums', {}).get('ECHO_RELEASE.json') == RELEASE_SHA)
        require('serial.after.release.version',
                serial_data.get('releaseVersion') == RELEASE_VERSION)
        require('api.after.featureCount', serial.get('featureCount') == 45)
    except AssertionError as error:
        checks.append({'check': 'verification.error', 'pass': False, 'detail': str(error)})
    failed = sum(1 for row in checks if not row['pass'])
    status = 'PASS' if failed == 0 else 'FAIL'
    report = {
        'report': 'VERIFY.json',
        'status': status,
        'verifiedAt': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'state': 'final recovered 45-feature state (registry + gateway45 + image 646631ab)',
        'finalImage': verify_final.get('summary'),
        'serialAfter': serial.get('serial'),
        'checks': {'total': len(checks), 'failed': failed},
        'rows': checks,
    }
    (R / 'VERIFY.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                                   encoding='utf-8')
    if status != 'PASS':
        raise SystemExit('VERIFY.json FAIL')

    required = [
        'deploy_board.sh', 'rollback_spatial_off.sh', 'registry_update.tar.gz',
        'image.ub', 'echo-gateway', 'ECHO_RELEASE.json', 'DEPLOY_STEPS.md',
        'DEPLOY_MANIFEST.json', 'REGISTRY_TAR.json', 'SD_PATCH.json', 'VERIFY.json',
        'FINAL_IMAGE_VERIFY.json', 'BOARD_READONLY.json', 'POST_DEPLOY.json',
        'POST_DEPLOY_SERIAL.json', 'POST_DEPLOY_PC.json', 'BOARD_DEPLOY.log',
        'BOARD_RECOVERY.log', 'GATEWAY_FIX_20261031.md', 'board_serial.ps1',
        'board_after_check.ps1', 'board_after_serial.txt', 'board_readonly_serial.txt',
        'registry/INTERFACE_REGISTRY.json', 'build_registry_tar.py', 'patch_sd_image.py',
        'image_patch_lib.py', 'verify_offline.py', 'make_deploy.py', 'check_artifacts.py',
        'finalize_final_state.py', 'verify_final_image.py', 'patch_image_gateway.py',
        'post_deploy_verify.py',
    ]
    missing = [name for name in required if not (R / name).is_file()]
    artifact_rows = [{'check': 'package.required.files', 'pass': not missing,
                      'detail': missing or 'all present'},
                     {'check': 'package.verify.status', 'pass': status == 'PASS'},
                     {'check': 'package.manifest.status',
                      'pass': manifest['status'] == 'DEPLOYED_AND_VERIFIED'}]
    files = {}
    total_bytes = 0
    for path in sorted(R.rglob('*')):
        if not path.is_file() or path.name.startswith('.'):
            continue
        if path.relative_to(R).parts[0] in ('backup', 'pc_release', 'history', '__pycache__'):
            continue
        blob = path.read_bytes()
        total_bytes += len(blob)
        files[path.relative_to(R).as_posix()] = {'bytes': len(blob), 'sha256': sha(blob)}
    artifact_rows.append({'check': 'package.final.image',
                          'pass': files.get('image.ub', {}).get('sha256') == IMAGE_SHA})
    artifact_rows.append({'check': 'package.gateway',
                          'pass': files.get('echo-gateway', {}).get('sha256') == GW_SHA})
    artifact_rows.append({'check': 'package.release',
                          'pass': files.get('ECHO_RELEASE.json', {}).get('sha256') == RELEASE_SHA})
    artifact_rows.append({'check': 'package.deploy.script',
                          'pass': files.get('deploy_board.sh', {}).get('sha256')
                          == manifest['files']['deploy_board.sh']['sha256']})
    artifact_rows.append({'check': 'package.rollback.script',
                          'pass': files.get('rollback_spatial_off.sh', {}).get('sha256')
                          == manifest['files']['rollback_spatial_off.sh']['sha256']})
    failed_artifacts = sum(1 for row in artifact_rows if not row['pass'])
    artifact = {
        'report': 'ARTIFACT_CHECK.json',
        'status': 'PASS' if failed_artifacts == 0 else 'FAIL',
        'checkedAt': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'state': 'final deployed and verified',
        'checks': {'total': len(artifact_rows), 'failed': failed_artifacts},
        'rows': artifact_rows,
        'files': files,
        'packageTotalBytesExcludingBackups': total_bytes,
    }
    (R / 'ARTIFACT_CHECK.json').write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': status,
                      'verifyChecks': len(checks),
                      'artifactStatus': artifact['status'],
                      'artifactFiles': len(files),
                      'deploySHA256': fsha('deploy_board.sh'),
                      'rollbackSHA256': fsha('rollback_spatial_off.sh')}, indent=2))


if __name__ == '__main__':
    main()
