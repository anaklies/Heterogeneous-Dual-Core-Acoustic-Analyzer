param(
  [int]$TimeoutSec = 180,
  [int]$SilenceSec = 45,
  [string]$OutFile = 'board_after_serial.txt'
)
# Post-deploy read-only board check. Run after Lead sends go and deploy_board.sh
# finished with __SPATIALOFF_DONE__. Writes the raw serial log that
# post_deploy_verify.py --serial-log parses into POST_DEPLOY.json.
$command = @'
echo AFTER_HASHES
sha256sum /opt/echo/registry/INTERFACE_REGISTRY.json /opt/echo/bin/echo-gateway /mnt/echo-sd/image.ub
echo AFTER_FEATURE_ID_LINES
grep -c '"featureId":' /opt/echo/registry/INTERFACE_REGISTRY.json
echo AFTER_SPATIAL
echo spatial_interface
grep -c spatial_interface /opt/echo/registry/INTERFACE_REGISTRY.json
echo directed_das
grep -c directed_das /opt/echo/registry/INTERFACE_REGISTRY.json
echo full_das
grep -c full_das /opt/echo/registry/INTERFACE_REGISTRY.json
echo band_das
grep -c band_das /opt/echo/registry/INTERFACE_REGISTRY.json
echo spatial_grid
grep -c spatial_grid /opt/echo/registry/INTERFACE_REGISTRY.json
echo spatial_peaks
grep -c spatial_peaks /opt/echo/registry/INTERFACE_REGISTRY.json
echo AFTER_PS
ps | grep echo-gateway | grep -v grep
echo AFTER_SUMS
cat /mnt/echo-sd/SHA256SUMS
echo AFTER_PORTS
netstat -tlnp 2>/dev/null | grep -E 48120
echo AFTER_VER
head -5 /mnt/echo-sd/ECHO_RELEASE.json
'@
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& (Join-Path $PSScriptRoot 'board_serial.ps1') -Command $command -TimeoutSec $TimeoutSec -SilenceSec $SilenceSec -OutFile $OutFile