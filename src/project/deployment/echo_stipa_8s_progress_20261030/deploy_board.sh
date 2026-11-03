#!/bin/sh
set -eu
echo __STIPA8_START__
echo '1e6d3fb1d076096b61930441e1ee2ce9b11264ee958860e0cab61690d32a2e73  /opt/echo/registry/INTERFACE_REGISTRY.json' | sha256sum -c -
echo 'dadfc4f8d8915388548c7b960b03ef48822cf7e4755fbbfa02fcab11e81955aa  /mnt/echo-sd/image.ub' | sha256sum -c -
cp /opt/echo/registry/INTERFACE_REGISTRY.json /opt/echo/registry/INTERFACE_REGISTRY.json.before-stipa-8s-20261030
cp /opt/echo/bin/echo-gateway /opt/echo/bin/echo-gateway.before-stipa-8s-20261030
cp /mnt/echo-sd/image.ub /mnt/echo-sd/image.ub.before-stipa-8s-20261030
cp /mnt/echo-sd/ECHO_RELEASE.json /mnt/echo-sd/ECHO_RELEASE.json.before-stipa-8s-20261030
cp /mnt/echo-sd/SHA256SUMS /mnt/echo-sd/SHA256SUMS.before-stipa-8s-20261030
wget -q -T 20 -O /tmp/stipa8-registry.tar.gz http://192.168.77.1:48190/registry_update.tar.gz
echo 'b2a7b97f79969ef01c5227bc7174f6b8bf8a380f7751b8580a716d1214a2b490  /tmp/stipa8-registry.tar.gz' | sha256sum -c -
tar -xzf /tmp/stipa8-registry.tar.gz -C /opt/echo
echo '301636354dc1902426fe57e4dbd1a0a95809323d0ad2eff46cd71cad51a5bead  /opt/echo/registry/INTERFACE_REGISTRY.json' | sha256sum -c -
wget -q -T 20 -O /tmp/echo-gateway.stipa8 http://192.168.77.1:48190/echo-gateway
echo 'b982cecea0e9da4bf3a73dc7855d2ba41be7d22322f7a0221d8e0b07ef928920  /tmp/echo-gateway.stipa8' | sha256sum -c -
chmod 755 /tmp/echo-gateway.stipa8
mv /tmp/echo-gateway.stipa8 /opt/echo/bin/echo-gateway
echo 'b982cecea0e9da4bf3a73dc7855d2ba41be7d22322f7a0221d8e0b07ef928920  /opt/echo/bin/echo-gateway' | sha256sum -c -
wget -q -T 30 -O /mnt/echo-sd/image.ub.stipa8 http://192.168.77.1:48190/image.ub
echo 'cba07779ad32643380a96462569dabb4f4f4b2ec62bc9476a8dd4caa1fbc4902  /mnt/echo-sd/image.ub.stipa8' | sha256sum -c -
mv /mnt/echo-sd/image.ub.stipa8 /mnt/echo-sd/image.ub
wget -q -T 10 -O /mnt/echo-sd/ECHO_RELEASE.json.stipa8 http://192.168.77.1:48190/ECHO_RELEASE.json
echo '5e73d838eda15403f92a39c7e1b4a493b65307f4257f93199cfd842bf94500ee  /mnt/echo-sd/ECHO_RELEASE.json.stipa8' | sha256sum -c -
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
