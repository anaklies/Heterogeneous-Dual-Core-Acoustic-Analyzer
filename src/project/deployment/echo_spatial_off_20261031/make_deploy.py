"""Generate the board deploy/rollback scripts, ECHO_RELEASE.json and manifest.

All hashes embedded in deploy_board.sh are read back from the built artifacts, so
the script can only succeed against exactly the files in this package. The board
pre-state hashes are the hashes reported by the 2026-10-30 deployed release and
are re-checked read-only on the board before this package is used.
"""
from pathlib import Path
import hashlib, json

R = Path(__file__).resolve().parent
PROJECT = R.parents[1]
BASE_RELEASE = PROJECT / 'deployment/echo_stipa_8s_progress_20261030/ECHO_RELEASE.json'
GATEWAY = PROJECT / 'deployment/echo_stipa_8s_progress_20261030/gateway/echo-gateway'

# Board state before this deployment (verified read-only over COM6 by board_serial.ps1).
OLD_REGISTRY_SHA = '301636354dc1902426fe57e4dbd1a0a95809323d0ad2eff46cd71cad51a5bead'
OLD_GATEWAY_SHA = 'b982cecea0e9da4bf3a73dc7855d2ba41be7d22322f7a0221d8e0b07ef928920'
OLD_IMAGE_SHA = 'cba07779ad32643380a96462569dabb4f4f4b2ec62bc9476a8dd4caa1fbc4902'
NEW_REGISTRY_SHA = 'dcbc393723513773867f6a9d96f396eb22b13386060881fdae06dda4ecb77628'
BACKUP_SUFFIX = '.before-spatial-off-20261031'
HTTP_ROOT = 'http://192.168.77.1:48190'
PC_HTTP_PORT = 48190


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def fsha(path):
    return sha(path.read_bytes())


def main():
    tar_info = json.loads((R / 'REGISTRY_TAR.json').read_text(encoding='utf-8'))
    patch_info = json.loads((R / 'SD_PATCH.json').read_text(encoding='utf-8'))
    tar_sha = tar_info['sha256']
    reg_sha = fsha(R / 'registry/INTERFACE_REGISTRY.json')
    gateway_sha = fsha(GATEWAY)
    image_sha = fsha(R / 'image.ub')
    old_board_ok = (reg_sha == NEW_REGISTRY_SHA
                    and patch_info['sourceSHA256'] == OLD_IMAGE_SHA
                    and gateway_sha == OLD_GATEWAY_SHA
                    and OLD_REGISTRY_SHA != NEW_REGISTRY_SHA)
    if not old_board_ok:
        raise SystemExit('artifact hashes do not match the expected board state')

    release = json.loads(BASE_RELEASE.read_text(encoding='utf-8'))
    release.update({
        'version': '20261031-spatial-off-45-features',
        'featureCount': 45,
        'softwarePathsPassed': 45,
        'PSImageReused': True,
        'algorithmChanged': False,
        'registryHotfix': '20261031-spatial-off-six-spatial-features-1',
        'registrySHA256': reg_sha,
        'gatewaySHA256': gateway_sha,
        'imageSHA256': image_sha,
        'spatialInterfaces': {
            'enabled': False,
            'featureCountBefore': 51,
            'featureCountAfter': 45,
            'removedFeatureIds': [
                'spatial_interface', 'directed_das', 'full_das', 'band_das',
                'spatial_grid', 'spatial_peaks'],
            'removedCount': 6,
        },
        'imagePatch': {
            'sourceImageSHA256': patch_info['sourceSHA256'],
            'changedRamdiskEntries': patch_info['changedRamdiskEntries'],
            'ramdiskEntries': patch_info['ramdiskEntries'],
            'unchangedRamdiskEntries': patch_info['unchangedRamdiskEntries'],
            'kernelSHA256': patch_info['kernelSHA256'],
            'dtbSHA256': patch_info['dtbSHA256'],
            'kernelAndDTBUnchanged': True,
            'bitstreamChanged': False,
            'bootChanged': False,
        },
        'gatewayChanged': False,
        'deployPackage': 'deployment/echo_spatial_off_20261031',
        'notes': ('Device-side spatial interface shutdown: device registry lists 45 '
                  'features (six spatial features removed). echo-gateway binary, '
                  'BOOT.BIN, boot.scr, system.dtb, kernel, device tree and bitstream '
                  'are unchanged; image.ub only differs in the ramdisk registry entry.'),
    })
    (R / 'ECHO_RELEASE.json').write_text(
        json.dumps(release, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    release_sha = fsha(R / 'ECHO_RELEASE.json')

    deploy = f'''#!/bin/sh
# echo_spatial_off_20261031 - device-side shutdown of the six spatial interfaces.
# Run on the board (COM6 root console):
#   wget -q -O /tmp/spatial-off.sh {HTTP_ROOT}/deploy_board.sh && sh /tmp/spatial-off.sh
# The PC must serve this package directory on {HTTP_ROOT} (see DEPLOY_STEPS.md).
# Changes  : /opt/echo/registry/INTERFACE_REGISTRY.json  (51 -> 45 features),
#            /mnt/echo-sd/image.ub                        (ramdisk registry only),
#            /mnt/echo-sd/ECHO_RELEASE.json, /mnt/echo-sd/SHA256SUMS.
# Unchanged: echo-gateway, BOOT.BIN, boot.scr, system.dtb, kernel, dtb, bitstream.
# Failure  : every replaced file is backed up as *{BACKUP_SUFFIX};
#            recover with rollback_spatial_off.sh (see DEPLOY_STEPS.md).
set -eu
trap 'rc=$?; if [ "$rc" -ne 0 ]; then echo __SPATIALOFF_FAILED__; echo "restore with: wget -q -O /tmp/rollback.sh {HTTP_ROOT}/rollback_spatial_off.sh && sh /tmp/rollback.sh"; fi' EXIT
echo __SPATIALOFF_START__
# 1. preconditions: current board state must be exactly the 2026-10-30 release.
echo '{OLD_REGISTRY_SHA}  /opt/echo/registry/INTERFACE_REGISTRY.json' | sha256sum -c -
echo '{OLD_GATEWAY_SHA}  /opt/echo/bin/echo-gateway' | sha256sum -c -
echo '{OLD_IMAGE_SHA}  /mnt/echo-sd/image.ub' | sha256sum -c -
echo __SPATIALOFF_PRESTATE_OK__
# 1b. require enough free space on /mnt/echo-sd: the old image (backup) + the new image.
FREE_KB=$(df -k /mnt/echo-sd | awk 'NR==2 {{print $4}}')
if [ -z "$FREE_KB" ] || [ "$FREE_KB" -lt 340000 ]; then
  echo "not enough free space on /mnt/echo-sd: ${{FREE_KB:-unknown}} KB"; exit 1
fi
rm -f /mnt/echo-sd/image.ub.spatial-off.new /mnt/echo-sd/ECHO_RELEASE.json.spatial-off.new
echo __SPATIALOFF_SPACE_OK__ __FREE_KB__=$FREE_KB
# 2. backups of every file this script may replace (gateway backup kept as reference).
cp -p /opt/echo/registry/INTERFACE_REGISTRY.json /opt/echo/registry/INTERFACE_REGISTRY.json{BACKUP_SUFFIX}
cp -p /opt/echo/bin/echo-gateway /opt/echo/bin/echo-gateway{BACKUP_SUFFIX}
cp -p /mnt/echo-sd/image.ub /mnt/echo-sd/image.ub{BACKUP_SUFFIX}
cp -p /mnt/echo-sd/ECHO_RELEASE.json /mnt/echo-sd/ECHO_RELEASE.json{BACKUP_SUFFIX}
cp -p /mnt/echo-sd/SHA256SUMS /mnt/echo-sd/SHA256SUMS{BACKUP_SUFFIX}
echo __SPATIALOFF_BACKUPS_OK__
# 3. download and verify the payload BEFORE touching live files.
mkdir -p /tmp/spatial-off
wget -q -T 20 -O /tmp/spatial-off/registry_update.tar.gz {HTTP_ROOT}/registry_update.tar.gz
echo '{tar_sha}  /tmp/spatial-off/registry_update.tar.gz' | sha256sum -c -
wget -q -T 30 -O /mnt/echo-sd/image.ub.spatial-off.new {HTTP_ROOT}/image.ub
echo '{image_sha}  /mnt/echo-sd/image.ub.spatial-off.new' | sha256sum -c -
wget -q -T 10 -O /mnt/echo-sd/ECHO_RELEASE.json.spatial-off.new {HTTP_ROOT}/ECHO_RELEASE.json
echo '{release_sha}  /mnt/echo-sd/ECHO_RELEASE.json.spatial-off.new' | sha256sum -c -
echo __SPATIALOFF_DOWNLOAD_OK__
# 4. install registry (tar holds only registry/INTERFACE_REGISTRY.json).
tar -xzf /tmp/spatial-off/registry_update.tar.gz -C /opt/echo
echo '{reg_sha}  /opt/echo/registry/INTERFACE_REGISTRY.json' | sha256sum -c -
echo __SPATIALOFF_REGISTRY_OK__
# 5. swap image.ub and release metadata on the SD card (same filesystem rename).
mv /mnt/echo-sd/image.ub.spatial-off.new /mnt/echo-sd/image.ub
mv /mnt/echo-sd/ECHO_RELEASE.json.spatial-off.new /mnt/echo-sd/ECHO_RELEASE.json
echo '{image_sha}  /mnt/echo-sd/image.ub' | sha256sum -c -
echo '{release_sha}  /mnt/echo-sd/ECHO_RELEASE.json' | sha256sum -c -
echo __SPATIALOFF_SD_OK__
# 6. refresh the SD checksum manifest and flush.
cd /mnt/echo-sd
sha256sum BOOT.BIN boot.scr system.dtb image.ub ECHO_RELEASE.json > SHA256SUMS.new
mv SHA256SUMS.new SHA256SUMS
sync
echo __SPATIALOFF_SYNC_OK__
# 7. restart echo-gateway via the supervisor; the binary is NOT changed, it just
#    reloads the registry at start.
for pid in $(pidof echo-gateway); do kill "$pid"; done
sleep 5
ps | grep echo-gateway | grep -v grep
# 8. final verification of the whole deployed state.
sha256sum /opt/echo/bin/echo-gateway /opt/echo/registry/INTERFACE_REGISTRY.json /mnt/echo-sd/image.ub /mnt/echo-sd/ECHO_RELEASE.json
grep -c '"featureId":' /opt/echo/registry/INTERFACE_REGISTRY.json
echo __SPATIALOFF_DONE__
'''
    (R / 'deploy_board.sh').write_text(deploy, encoding='utf-8', newline='\n')

    rollback = f'''#!/bin/sh
# Roll back echo_spatial_off_20261031 using the on-board backups made by deploy_board.sh.
# Run on the board (COM6 root console):
#   wget -q -O /tmp/rollback.sh {HTTP_ROOT}/rollback_spatial_off.sh && sh /tmp/rollback.sh
set -eu
echo __SPATIALOFF_ROLLBACK_START__
for f in /opt/echo/registry/INTERFACE_REGISTRY.json{BACKUP_SUFFIX} \\
         /mnt/echo-sd/image.ub{BACKUP_SUFFIX} \\
         /mnt/echo-sd/ECHO_RELEASE.json{BACKUP_SUFFIX} \\
         /mnt/echo-sd/SHA256SUMS{BACKUP_SUFFIX}; do
  test -f "$f" || {{ echo "missing backup: $f"; exit 1; }}
done
cp -p /opt/echo/registry/INTERFACE_REGISTRY.json{BACKUP_SUFFIX} /opt/echo/registry/INTERFACE_REGISTRY.json
cp -p /mnt/echo-sd/image.ub{BACKUP_SUFFIX} /mnt/echo-sd/image.ub
cp -p /mnt/echo-sd/ECHO_RELEASE.json{BACKUP_SUFFIX} /mnt/echo-sd/ECHO_RELEASE.json
cp -p /mnt/echo-sd/SHA256SUMS{BACKUP_SUFFIX} /mnt/echo-sd/SHA256SUMS
sync
echo __SPATIALOFF_ROLLBACK_FILES_OK__
echo '{OLD_REGISTRY_SHA}  /opt/echo/registry/INTERFACE_REGISTRY.json' | sha256sum -c -
echo '{OLD_GATEWAY_SHA}  /opt/echo/bin/echo-gateway' | sha256sum -c -
echo '{OLD_IMAGE_SHA}  /mnt/echo-sd/image.ub' | sha256sum -c -
for pid in $(pidof echo-gateway); do kill "$pid"; done
sleep 5
ps | grep echo-gateway | grep -v grep
sha256sum /opt/echo/bin/echo-gateway /opt/echo/registry/INTERFACE_REGISTRY.json /mnt/echo-sd/image.ub
echo __SPATIALOFF_ROLLBACK_DONE__
'''
    (R / 'rollback_spatial_off.sh').write_text(rollback, encoding='utf-8', newline='\n')

    manifest = {
        'date': '2026-10-31',
        'package': 'deployment/echo_spatial_off_20261031',
        'purpose': 'device-side shutdown of the six spatial interfaces (51 -> 45 features)',
        'target': {
            'board': '192.168.77.2 (root console over COM6 115200)',
            'pcHttpRoot': HTTP_ROOT,
            'pcHttpBind': '192.168.77.1:' + str(PC_HTTP_PORT),
        },
        'files': {
            'registry_update.tar.gz': {'sha256': tar_sha, 'bytes': tar_info['tarBytes']},
            'image.ub': {'sha256': image_sha, 'bytes': (R / 'image.ub').stat().st_size},
            'ECHO_RELEASE.json': {'sha256': release_sha,
                                  'bytes': (R / 'ECHO_RELEASE.json').stat().st_size},
            'deploy_board.sh': {'sha256': fsha(R / 'deploy_board.sh')},
            'rollback_spatial_off.sh': {'sha256': fsha(R / 'rollback_spatial_off.sh')},
        },
        'boardBefore': {
            'registrySHA256': OLD_REGISTRY_SHA,
            'gatewaySHA256': OLD_GATEWAY_SHA,
            'imageSHA256': OLD_IMAGE_SHA,
            'registryFeatures': 51,
        },
        'boardAfter': {
            'registrySHA256': reg_sha,
            'gatewaySHA256': gateway_sha,
            'imageSHA256': image_sha,
            'releaseSHA256': release_sha,
            'registryFeatures': 45,
        },
        'boardBackups': [
            '/opt/echo/registry/INTERFACE_REGISTRY.json' + BACKUP_SUFFIX,
            '/opt/echo/bin/echo-gateway' + BACKUP_SUFFIX,
            '/mnt/echo-sd/image.ub' + BACKUP_SUFFIX,
            '/mnt/echo-sd/ECHO_RELEASE.json' + BACKUP_SUFFIX,
            '/mnt/echo-sd/SHA256SUMS' + BACKUP_SUFFIX,
        ],
        'deployCommand': ('wget -q -O /tmp/spatial-off.sh ' + HTTP_ROOT
                          + '/deploy_board.sh && sh /tmp/spatial-off.sh'),
        'rollbackCommand': ('wget -q -O /tmp/rollback.sh ' + HTTP_ROOT
                            + '/rollback_spatial_off.sh && sh /tmp/rollback.sh'),
        'verification': {
            'offlineImage': 'VERIFY.json',
            'sdPatch': 'SD_PATCH.json',
            'registryTar': 'REGISTRY_TAR.json',
            'boardReadonly': 'BOARD_READONLY.json',
            'artifactCheck': 'ARTIFACT_CHECK.json',
            'deploySteps': 'DEPLOY_STEPS.md',
        },
        'notDeployedYet': True,
        'ready': {'prepared': True, 'deployed': False, 'waitingForLeadGo': True},
    }
    (R / 'DEPLOY_MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'registrySHA256': reg_sha, 'gatewaySHA256': gateway_sha,
                      'imageSHA256': image_sha, 'tarSHA256': tar_sha,
                      'releaseSHA256': release_sha,
                      'deployScriptSHA256': manifest['files']['deploy_board.sh']['sha256']},
                     indent=2))


if __name__ == '__main__':
    main()
