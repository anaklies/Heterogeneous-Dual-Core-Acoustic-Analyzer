#!/bin/sh
set -eu
echo __STABILITY_START__
echo 'b6c864b53bc1d513b5c9d2ea54b1c2f018b6e9aace8ba41b11c2a51653f5625a  /opt/echo/registry/INTERFACE_REGISTRY.json' | sha256sum -c -
echo '06f0fe39b9596da8f18443220045803f24d654bacf0354f0b7882a4ed5d19828  /mnt/echo-sd/image.ub' | sha256sum -c -
cp /opt/echo/registry/INTERFACE_REGISTRY.json /opt/echo/registry/INTERFACE_REGISTRY.json.before-stability-20261030
wget -q -T 10 -O /tmp/echo-stability-registry.tar.gz http://192.168.77.1:48190/registry_update.tar.gz
echo '6236563ce6bb49aad34b077208f91c226b4e2737c721eabfe144629eb9cf11dd  /tmp/echo-stability-registry.tar.gz' | sha256sum -c -
tar -xzf /tmp/echo-stability-registry.tar.gz -C /opt/echo
echo '1e6d3fb1d076096b61930441e1ee2ce9b11264ee958860e0cab61690d32a2e73  /opt/echo/registry/INTERFACE_REGISTRY.json' | sha256sum -c -
cp /mnt/echo-sd/image.ub /mnt/echo-sd/image.ub.before-stability-20261030
wget -q -T 20 -O /mnt/echo-sd/image.ub.stability-new http://192.168.77.1:48190/image.ub
echo 'dadfc4f8d8915388548c7b960b03ef48822cf7e4755fbbfa02fcab11e81955aa  /mnt/echo-sd/image.ub.stability-new' | sha256sum -c -
mv /mnt/echo-sd/image.ub.stability-new /mnt/echo-sd/image.ub
cp /mnt/echo-sd/ECHO_RELEASE.json /mnt/echo-sd/ECHO_RELEASE.json.before-stability-20261030
cp /mnt/echo-sd/SHA256SUMS /mnt/echo-sd/SHA256SUMS.before-stability-20261030
wget -q -T 5 -O /mnt/echo-sd/ECHO_RELEASE.json.new http://192.168.77.1:48190/ECHO_RELEASE.json
echo '2a638d1fdb038fe61bdb594effc7a6fc6db1802a2930d7076decd6961d999365  /mnt/echo-sd/ECHO_RELEASE.json.new' | sha256sum -c -
mv /mnt/echo-sd/ECHO_RELEASE.json.new /mnt/echo-sd/ECHO_RELEASE.json
cd /mnt/echo-sd
sha256sum BOOT.BIN boot.scr system.dtb image.ub ECHO_RELEASE.json >SHA256SUMS.new
mv SHA256SUMS.new SHA256SUMS
sync
echo __STABILITY_FILES_AND_SD_PASS__
