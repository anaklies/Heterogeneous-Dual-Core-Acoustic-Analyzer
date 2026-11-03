#!/bin/sh
# echo_spatial_off_20261031 - spatial interfaces off (45 features) + 45-feature gateway.
# Final state: registry dcbc39372351..., gateway 5d4b0291146f..., image 646631abdd1a...
# Run on the board (COM6 root console):
#   wget -q -O /tmp/spatial-off45.sh http://192.168.77.1:48190/deploy_board.sh && sh /tmp/spatial-off45.sh
# The script is idempotent: if the board is already in the final state it only verifies.
# Changes  : /opt/echo/registry/INTERFACE_REGISTRY.json (51/45 -> 45 features),
#            /opt/echo/bin/echo-gateway (45-feature build),
#            /mnt/echo-sd/image.ub (ramdisk registry + gateway only),
#            /mnt/echo-sd/ECHO_RELEASE.json, /mnt/echo-sd/SHA256SUMS.
# Unchanged: BOOT.BIN, boot.scr, system.dtb, kernel, dtb, bitstream.
# Failure  : files replaced before the final check are backed up on the board; recover with
#            rollback_spatial_off.sh. A gateway restart takes up to 60 s after echo-runtime start.
set -eu
trap 'rc=$?; if [ "$rc" -ne 0 ]; then echo __SPATIALOFF45_FAILED__; echo "rollback: wget -q -O /tmp/rollback.sh http://192.168.77.1:48190/rollback_spatial_off.sh && sh /tmp/rollback.sh"; fi' EXIT
echo __SPATIALOFF45_START__
R=$(sha256sum /opt/echo/registry/INTERFACE_REGISTRY.json | cut -d" " -f1)
G=$(sha256sum /opt/echo/bin/echo-gateway | cut -d" " -f1)
I=$(sha256sum /mnt/echo-sd/image.ub | cut -d" " -f1)
E=$(sha256sum /mnt/echo-sd/ECHO_RELEASE.json | cut -d" " -f1)
echo "current registry=$R gateway=$G image=$I release=$E"
if [ "$R" = "dcbc393723513773867f6a9d96f396eb22b13386060881fdae06dda4ecb77628" ] && [ "$G" = "5d4b0291146f71fd0f5e39ef11d326cb49e723fe6e43763a0fffaa4e370ecc44" ] && [ "$I" = "646631abdd1add91b96ea28d2553eafeac647c42267386e03fddaf17613b6565" ] && [ "$E" = "f51249c8b9118139b54210d11f4c0bc1dd691f9280e9bd8f012125492d697066" ]; then
  echo __SPATIALOFF45_ALREADY_DONE__
  sha256sum /opt/echo/bin/echo-gateway /opt/echo/registry/INTERFACE_REGISTRY.json /mnt/echo-sd/image.ub
  grep -c '"featureId":' /opt/echo/registry/INTERFACE_REGISTRY.json
  ps | grep echo-gateway | grep -v grep
  echo __SPATIALOFF45_DONE__
  exit 0
fi
echo __SPATIALOFF45_NEEDS_UPDATE__
case "$R" in "301636354dc1902426fe57e4dbd1a0a95809323d0ad2eff46cd71cad51a5bead"|"dcbc393723513773867f6a9d96f396eb22b13386060881fdae06dda4ecb77628") ;; *) echo "unexpected registry $R"; exit 1;; esac
case "$G" in "b982cecea0e9da4bf3a73dc7855d2ba41be7d22322f7a0221d8e0b07ef928920"|"5d4b0291146f71fd0f5e39ef11d326cb49e723fe6e43763a0fffaa4e370ecc44") ;; *) echo "unexpected gateway $G"; exit 1;; esac
case "$I" in "cba07779ad32643380a96462569dabb4f4f4b2ec62bc9476a8dd4caa1fbc4902"|"00b93b142f81d6db5da50eeb8b35a6e2405cbc82fa1d542ae147d7d64dcfe238"|"646631abdd1add91b96ea28d2553eafeac647c42267386e03fddaf17613b6565") ;; *) echo "unexpected image $I"; exit 1;; esac
FREE_KB=$(df -k /mnt/echo-sd | awk 'NR==2 {print $4}')
if [ -z "$FREE_KB" ] || [ "$FREE_KB" -lt 340000 ]; then echo "not enough space on /mnt/echo-sd: $FREE_KB KB"; exit 1; fi
rm -f /mnt/echo-sd/image.ub.spatial-off45.new /mnt/echo-sd/ECHO_RELEASE.json.spatial-off45.new
cp -p /opt/echo/registry/INTERFACE_REGISTRY.json /opt/echo/registry/INTERFACE_REGISTRY.json.before-gateway45-20261031
cp -p /opt/echo/bin/echo-gateway /opt/echo/bin/echo-gateway.before-gateway45-20261031
cp -p /mnt/echo-sd/image.ub /mnt/echo-sd/image.ub.before-gateway45-20261031
cp -p /mnt/echo-sd/ECHO_RELEASE.json /mnt/echo-sd/ECHO_RELEASE.json.before-gateway45-20261031
cp -p /mnt/echo-sd/SHA256SUMS /mnt/echo-sd/SHA256SUMS.before-gateway45-20261031
echo __SPATIALOFF45_BACKUPS_OK__
mkdir -p /tmp/spatial-off45
wget -q -T 20 -O /tmp/spatial-off45/registry_update.tar.gz http://192.168.77.1:48190/registry_update.tar.gz
echo 'c5ff16196ddca0d435954ab890a0a09582cb336c4be0b3741d64a32b825fb603  /tmp/spatial-off45/registry_update.tar.gz' | sha256sum -c -
wget -q -T 20 -O /tmp/spatial-off45/echo-gateway http://192.168.77.1:48190/echo-gateway
echo '5d4b0291146f71fd0f5e39ef11d326cb49e723fe6e43763a0fffaa4e370ecc44  /tmp/spatial-off45/echo-gateway' | sha256sum -c -
wget -q -T 30 -O /mnt/echo-sd/image.ub.spatial-off45.new http://192.168.77.1:48190/image.ub
echo '646631abdd1add91b96ea28d2553eafeac647c42267386e03fddaf17613b6565  /mnt/echo-sd/image.ub.spatial-off45.new' | sha256sum -c -
wget -q -T 10 -O /mnt/echo-sd/ECHO_RELEASE.json.spatial-off45.new http://192.168.77.1:48190/ECHO_RELEASE.json
echo 'f51249c8b9118139b54210d11f4c0bc1dd691f9280e9bd8f012125492d697066  /mnt/echo-sd/ECHO_RELEASE.json.spatial-off45.new' | sha256sum -c -
echo __SPATIALOFF45_DOWNLOAD_OK__
tar -xzf /tmp/spatial-off45/registry_update.tar.gz -C /opt/echo
echo 'dcbc393723513773867f6a9d96f396eb22b13386060881fdae06dda4ecb77628  /opt/echo/registry/INTERFACE_REGISTRY.json' | sha256sum -c -
chmod 755 /tmp/spatial-off45/echo-gateway
mv /tmp/spatial-off45/echo-gateway /opt/echo/bin/echo-gateway
echo '5d4b0291146f71fd0f5e39ef11d326cb49e723fe6e43763a0fffaa4e370ecc44  /opt/echo/bin/echo-gateway' | sha256sum -c -
mv /mnt/echo-sd/image.ub.spatial-off45.new /mnt/echo-sd/image.ub
mv /mnt/echo-sd/ECHO_RELEASE.json.spatial-off45.new /mnt/echo-sd/ECHO_RELEASE.json
echo '646631abdd1add91b96ea28d2553eafeac647c42267386e03fddaf17613b6565  /mnt/echo-sd/image.ub' | sha256sum -c -
echo 'f51249c8b9118139b54210d11f4c0bc1dd691f9280e9bd8f012125492d697066  /mnt/echo-sd/ECHO_RELEASE.json' | sha256sum -c -
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
