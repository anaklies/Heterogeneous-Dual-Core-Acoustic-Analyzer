"""Generate ECHO_RELEASE.json and the board deploy script from the final artifacts."""
from pathlib import Path
import hashlib, json

R = Path(__file__).resolve().parent
ROOT = R.parents[1]
BASE_RELEASE = ROOT / 'deployment/echo_measurement_stability_20261030/ECHO_RELEASE.json'
OLD_REGISTRY_SHA = '1e6d3fb1d076096b61930441e1ee2ce9b11264ee958860e0cab61690d32a2e73'
OLD_IMAGE_SHA = 'dadfc4f8d8915388548c7b960b03ef48822cf7e4755fbbfa02fcab11e81955aa'


def sha(b):
    return hashlib.sha256(b).hexdigest()


def fsha(p):
    return sha((R / p).read_bytes())


tar_info = json.loads((R / 'REGISTRY_TAR.json').read_text())
reg_sha = fsha('registry/INTERFACE_REGISTRY.json')
gw_sha = fsha('gateway/echo-gateway')
img_sha = fsha('image.ub')
release = json.loads(BASE_RELEASE.read_text(encoding='utf-8'))
release.update({
    'version': '20261030-stipa-8s-reasons-and-progress',
    'algorithmChanged': True,
    'PSImageReused': False,
    'registryHotfix': '20261030-stipa-8s-reason-progress-1',
    'registrySHA256': reg_sha,
    'gatewayHotfix': '20261030-stipa-progress-fields-1',
    'gatewaySHA256': gw_sha,
    'imageSHA256': img_sha,
    'stipaQuickMode': {
        'stages': 15,
        'samples': 384000,
        'secondsNominal': 8,
        'bandsHz': [500, 1000, 2000],
        'scope': 'rapid modulation-transfer estimate',
        'centeredAnalysisSeconds': 7.4,
    },
    'stipaQuickResultFields': [
        'experimental_index', 'valid', 'certified_zero', 'reason_code',
        'failed_band_hz', 'failed_modulation_hz', 'reference_depth',
        'measured_depth', 'transfer_ratio'],
    'stipaQuickReasonCodes': {
        '0': 'ok', '1': 'capture', '2': 'energy_or_fit',
        '3': 'reference_modulation', '4': 'transfer_ratio'},
    'stipaProgressProtocol': 'completedStages+currentStageIndex+totalStages',
    'stipaFinalResultAccepted': False,
    'hardwareAccepted': False,
})
(R / 'ECHO_RELEASE.json').write_text(json.dumps(release, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
release_sha = fsha('ECHO_RELEASE.json')

def w(name, text):
    p = R / name
    p.write_text(text, encoding='utf-8', newline='\n')
    return p

deploy = f'''#!/bin/sh
set -eu
echo __STIPA8_START__
echo '{OLD_REGISTRY_SHA}  /opt/echo/registry/INTERFACE_REGISTRY.json' | sha256sum -c -
echo '{OLD_IMAGE_SHA}  /mnt/echo-sd/image.ub' | sha256sum -c -
cp /opt/echo/registry/INTERFACE_REGISTRY.json /opt/echo/registry/INTERFACE_REGISTRY.json.before-stipa-8s-20261030
cp /opt/echo/bin/echo-gateway /opt/echo/bin/echo-gateway.before-stipa-8s-20261030
cp /mnt/echo-sd/image.ub /mnt/echo-sd/image.ub.before-stipa-8s-20261030
cp /mnt/echo-sd/ECHO_RELEASE.json /mnt/echo-sd/ECHO_RELEASE.json.before-stipa-8s-20261030
cp /mnt/echo-sd/SHA256SUMS /mnt/echo-sd/SHA256SUMS.before-stipa-8s-20261030
wget -q -T 20 -O /tmp/stipa8-registry.tar.gz http://192.168.77.1:48190/registry_update.tar.gz
echo '{tar_info['sha256']}  /tmp/stipa8-registry.tar.gz' | sha256sum -c -
tar -xzf /tmp/stipa8-registry.tar.gz -C /opt/echo
echo '{reg_sha}  /opt/echo/registry/INTERFACE_REGISTRY.json' | sha256sum -c -
wget -q -T 20 -O /tmp/echo-gateway.stipa8 http://192.168.77.1:48190/echo-gateway
echo '{gw_sha}  /tmp/echo-gateway.stipa8' | sha256sum -c -
chmod 755 /tmp/echo-gateway.stipa8
mv /tmp/echo-gateway.stipa8 /opt/echo/bin/echo-gateway
echo '{gw_sha}  /opt/echo/bin/echo-gateway' | sha256sum -c -
wget -q -T 30 -O /mnt/echo-sd/image.ub.stipa8 http://192.168.77.1:48190/image.ub
echo '{img_sha}  /mnt/echo-sd/image.ub.stipa8' | sha256sum -c -
mv /mnt/echo-sd/image.ub.stipa8 /mnt/echo-sd/image.ub
wget -q -T 10 -O /mnt/echo-sd/ECHO_RELEASE.json.stipa8 http://192.168.77.1:48190/ECHO_RELEASE.json
echo '{release_sha}  /mnt/echo-sd/ECHO_RELEASE.json.stipa8' | sha256sum -c -
mv /mnt/echo-sd/ECHO_RELEASE.json.stipa8 /mnt/echo-sd/ECHO_RELEASE.json
cd /mnt/echo-sd
sha256sum BOOT.BIN boot.scr system.dtb image.ub ECHO_RELEASE.json >SHA256SUMS.new
mv SHA256SUMS.new SHA256SUMS
sync
echo __STIPA8_FILES_OK__
# The supervisor (echo-runtime supervise) restarts echo-gateway within a few seconds.
for pid in $(pidof echo-gateway); do kill "$pid"; done
sleep 5
ps | grep echo-gateway | grep -v grep
sha256sum /opt/echo/bin/echo-gateway /opt/echo/registry/INTERFACE_REGISTRY.json /mnt/echo-sd/image.ub
echo __STIPA8_GATEWAY_RELOADED__
'''
w('deploy_board.sh', deploy)
print(json.dumps({'registrySHA256': reg_sha, 'gatewaySHA256': gw_sha, 'imageSHA256': img_sha,
                  'releaseSHA256': release_sha, 'tarSHA256': tar_info['sha256']}, indent=2))
