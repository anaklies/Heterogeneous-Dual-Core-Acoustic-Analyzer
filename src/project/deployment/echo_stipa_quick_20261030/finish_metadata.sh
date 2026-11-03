set -eu
cp /mnt/echo-sd/ECHO_RELEASE.json /mnt/echo-sd/ECHO_RELEASE.json.before-stipa-quick-20261030
cp /mnt/echo-sd/SHA256SUMS /mnt/echo-sd/SHA256SUMS.before-stipa-quick-20261030
wget -q -T 5 -O /mnt/echo-sd/ECHO_RELEASE.json.new http://192.168.77.1:48190/ECHO_RELEASE.json
echo "23b1febfd3fb309ab56f65f3920816d52742c45a0c6e14e4f2cfc784eb9589e6  /mnt/echo-sd/ECHO_RELEASE.json.new" | sha256sum -c -
mv /mnt/echo-sd/ECHO_RELEASE.json.new /mnt/echo-sd/ECHO_RELEASE.json
cd /mnt/echo-sd
sha256sum BOOT.BIN boot.scr system.dtb image.ub ECHO_RELEASE.json >SHA256SUMS.new
mv SHA256SUMS.new SHA256SUMS
sync
echo __QUICK_METADATA_AND_SD_PASS__
for file in /tmp/echo-reg-http.pid /tmp/echo-sd-http.pid; do
 pid=$(cat "$file")
 case "$(tr '\000' ' ' </proc/$pid/cmdline 2>/dev/null)" in *httpd*4809[23]*) kill "$pid";; esac
done
