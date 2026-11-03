$ErrorActionPreference = 'Stop'
$phaseRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Set-Location -LiteralPath $phaseRoot
& xvlog --sv rtl/sensors/air_sound_speed.sv rtl/sensors/i2c_transaction_master.sv rtl/sensors/sensor_i2c_hub.sv rtl/sensors/environment_frame_snapshot.sv rtl/sensors/sixmic_sensor_subsystem.sv tests/sensors/tb_environment_frame_snapshot.sv *> tests/sensors/compile.log
if ($LASTEXITCODE -ne 0) { throw 'Sensor compile failed' }
& xelab tb_environment_frame_snapshot -s sensor_snapshot_sim *> tests/sensors/elaborate.log
if ($LASTEXITCODE -ne 0) { throw 'Sensor elaborate failed' }
& xsim sensor_snapshot_sim --runall *> tests/sensors/simulate.log
if ($LASTEXITCODE -ne 0) { throw 'Sensor simulation failed' }
if (!(Select-String -LiteralPath tests/sensors/simulate.log -Pattern 'PASS ENVIRONMENT_SNAPSHOT' -Quiet)) { throw 'PASS marker missing' }
Get-Content tests/sensors/simulate.log -Tail 8
