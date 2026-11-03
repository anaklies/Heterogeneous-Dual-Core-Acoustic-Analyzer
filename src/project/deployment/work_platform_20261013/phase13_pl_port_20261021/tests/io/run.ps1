$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
& 'D:/2025.2/Vivado/bin/xvlog.bat' --sv ../../rtl/control/pcm_axi_ring_writer.sv tb_pcm_writer.sv *> compile.log
if($LASTEXITCODE -ne 0){throw 'PCM writer compile failed'}
& 'D:/2025.2/Vivado/bin/xelab.bat' tb_pcm_writer -s pcm_writer *> elaborate.log
if($LASTEXITCODE -ne 0){throw 'PCM writer elaboration failed'}
& 'D:/2025.2/Vivado/bin/xsim.bat' pcm_writer -runall -log simulate.log *> run.log
$log=Get-Content simulate.log -Raw
if($LASTEXITCODE -ne 0 -or !$log.Contains('PCM_AXI_WRITER_PASS') -or $log.Contains('Fatal:')){throw 'PCM AXI writer test failed'}
Write-Output ($log -split "`n" | Where-Object {$_ -match 'PCM_AXI_WRITER_PASS'})
