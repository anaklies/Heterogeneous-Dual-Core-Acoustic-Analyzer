$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
& 'D:/2025.2/Vivado/bin/xvlog.bat' --sv ../../rtl/control/analysis_axi_control.sv tb_analysis_axi.sv *> axi_compile.log
if($LASTEXITCODE -ne 0){throw 'analysis AXI compile failed'}
& 'D:/2025.2/Vivado/bin/xelab.bat' tb_analysis_axi -s analysis_axi *> axi_elaborate.log
if($LASTEXITCODE -ne 0){throw 'analysis AXI elaboration failed'}
& 'D:/2025.2/Vivado/bin/xsim.bat' analysis_axi -runall -log axi_simulate.log *> axi_run.log
$log=Get-Content axi_simulate.log -Raw
if($LASTEXITCODE -ne 0 -or !$log.Contains('ANALYSIS_AXI_PASS') -or $log.Contains('Fatal:')){throw 'analysis AXI numerical test failed'}
Write-Output ($log -split "`n" | Where-Object {$_ -match 'ANALYSIS_AXI_PASS'})
