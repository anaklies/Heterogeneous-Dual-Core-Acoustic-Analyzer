$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
& 'D:/2025.2/Vivado/bin/xvlog.bat' --sv ../../rtl/control/mic_health.sv tb_mic_health.sv *> health_compile.log
if($LASTEXITCODE -ne 0){throw 'microphone health compile failed'}
& 'D:/2025.2/Vivado/bin/xelab.bat' tb_mic_health -s mic_health_check *> health_elaborate.log
if($LASTEXITCODE -ne 0){throw 'microphone health elaboration failed'}
& 'D:/2025.2/Vivado/bin/xsim.bat' mic_health_check -runall -log health_simulate.log *> health_run.log
$log=Get-Content health_simulate.log -Raw
if($LASTEXITCODE -ne 0 -or !$log.Contains('MIC_HEALTH_PASS') -or $log.Contains('Fatal:')){throw 'microphone health test failed'}
Write-Output ($log -split "`n" | Where-Object {$_ -match 'MIC_HEALTH_PASS'})
