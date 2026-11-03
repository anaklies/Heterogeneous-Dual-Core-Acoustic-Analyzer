#!/bin/sh
set -eu
echo __QUICK_DEPLOY_START__
echo "e1100dcd66cd3a941c053bac1ce383d180d48e3f24bd25337e87f799589ff944  /opt/echo/registry/INTERFACE_REGISTRY.json" | sha256sum -c -
echo "d3a1967146ef5166f2047e3953ad741c49c1230b638461641a25f405017de86d  /mnt/echo-sd/image.ub" | sha256sum -c -
cp /opt/echo/registry/INTERFACE_REGISTRY.json /opt/echo/registry/INTERFACE_REGISTRY.json.before-quick-20261030
wget -q -T 15 -O /tmp/echo-quick-registry.tar.gz http://192.168.77.1:48190/quick_registry_update.tar.gz
echo "6aeb6403332406745d4f3346723d96c4955fd1a39fa2975b41fb81cf3ab83951  /tmp/echo-quick-registry.tar.gz" | sha256sum -c -
tar -xzf /tmp/echo-quick-registry.tar.gz -C /opt/echo
echo "b6c864b53bc1d513b5c9d2ea54b1c2f018b6e9aace8ba41b11c2a51653f5625a  /opt/echo/registry/INTERFACE_REGISTRY.json" | sha256sum -c -
cp /mnt/echo-sd/image.ub /mnt/echo-sd/image.ub.before-stipa-quick-20261030
wget -q -T 20 -O /mnt/echo-sd/image.ub.stipa-new http://192.168.77.1:48190/image.ub
echo "06f0fe39b9596da8f18443220045803f24d654bacf0354f0b7882a4ed5d19828  /mnt/echo-sd/image.ub.stipa-new" | sha256sum -c -
mv /mnt/echo-sd/image.ub.stipa-new /mnt/echo-sd/image.ub
sync
echo __QUICK_FILES_AND_SD_OK__
for pid in $(pidof echo-gateway); do
 case "$(tr '\000' ' ' </proc/$pid/cmdline)" in */opt/echo/bin/echo-gateway*) kill "$pid";; esac
done
echo __QUICK_GATEWAY_RELOAD_REQUESTED__
