#!/bin/sh
# Roll back echo_spatial_off_20261031 to the 2026-10-30 working state (51 features,
# gateway b982, image cba07779) using the on-board backups made by the first deploy.
# Run on the board (COM6 root console):
#   wget -q -O /tmp/rollback.sh http://192.168.77.1:48190/rollback_spatial_off.sh && sh /tmp/rollback.sh
set -eu
echo __SPATIALOFF_ROLLBACK_START__
for f in /opt/echo/registry/INTERFACE_REGISTRY.json.before-spatial-off-20261031          /opt/echo/bin/echo-gateway.before-spatial-off-20261031          /mnt/echo-sd/image.ub.before-spatial-off-20261031          /mnt/echo-sd/ECHO_RELEASE.json.before-spatial-off-20261031          /mnt/echo-sd/SHA256SUMS.before-spatial-off-20261031; do
  test -f "$f" || { echo "missing backup: $f"; exit 1; }
done
cp -p /opt/echo/registry/INTERFACE_REGISTRY.json.before-spatial-off-20261031 /opt/echo/registry/INTERFACE_REGISTRY.json
cp -p /opt/echo/bin/echo-gateway.before-spatial-off-20261031 /opt/echo/bin/echo-gateway
cp -p /mnt/echo-sd/image.ub.before-spatial-off-20261031 /mnt/echo-sd/image.ub
cp -p /mnt/echo-sd/ECHO_RELEASE.json.before-spatial-off-20261031 /mnt/echo-sd/ECHO_RELEASE.json
cp -p /mnt/echo-sd/SHA256SUMS.before-spatial-off-20261031 /mnt/echo-sd/SHA256SUMS
sync
echo '301636354dc1902426fe57e4dbd1a0a95809323d0ad2eff46cd71cad51a5bead  /opt/echo/registry/INTERFACE_REGISTRY.json' | sha256sum -c -
echo 'b982cecea0e9da4bf3a73dc7855d2ba41be7d22322f7a0221d8e0b07ef928920  /opt/echo/bin/echo-gateway' | sha256sum -c -
echo 'cba07779ad32643380a96462569dabb4f4f4b2ec62bc9476a8dd4caa1fbc4902  /mnt/echo-sd/image.ub' | sha256sum -c -
/opt/echo/bin/echo-runtime stop 2>/dev/null || true
sleep 2
/opt/echo/bin/echo-runtime start
sleep 6
ps | grep echo-gateway | grep -v grep
grep -c '"featureId":' /opt/echo/registry/INTERFACE_REGISTRY.json
sha256sum /opt/echo/bin/echo-gateway /opt/echo/registry/INTERFACE_REGISTRY.json /mnt/echo-sd/image.ub
echo __SPATIALOFF_ROLLBACK_DONE__
