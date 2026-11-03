$ErrorActionPreference='Stop'
$phaseRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$runRoot=Join-Path $phaseRoot ('cache/control_'+[DateTime]::UtcNow.ToString('yyyyMMdd_HHmmss_ffff'))
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null
$source=Join-Path $phaseRoot 'rtl/control/profile_scheduler.sv'
$test=Join-Path $PSScriptRoot 'tb_profile_scheduler.sv'
$oldLocation=Get-Location
try {
    Set-Location $runRoot
    & xvlog --sv $source $test *> compile.log
    if($LASTEXITCODE -ne 0){throw 'xvlog failed; inspect compile.log'}
    & xelab tb_profile_scheduler -s control_scheduler -debug typical *> elaborate.log
    if($LASTEXITCODE -ne 0){throw 'xelab failed; inspect elaborate.log'}
    $runTcl=(Join-Path $PSScriptRoot 'run_control.tcl').Replace('\','/')
    & xsim control_scheduler -tclbatch $runTcl *> simulate.log
    if($LASTEXITCODE -ne 0){throw 'xsim failed; inspect simulate.log'}
    $simulation=[IO.File]::ReadAllText((Join-Path $runRoot 'simulate.log'))
    if($simulation -notmatch 'CONTROL_SCHEDULER_PASS checks=(\d+)'){throw 'Missing PASS marker; inspect simulate.log'}
    $count=[int]$Matches[1]
    $receipt=@{
        status='PASS';checks=$count;scope='scheduler control RTL only; not algorithms or whole board';
        sourceSHA256=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLower();
        testSHA256=(Get-FileHash -LiteralPath $test -Algorithm SHA256).Hash.ToLower();
        runDirectory=$runRoot;source=$source;testbench=$test;
        noSynthesis=$true;hardwareValidated=$false
    }
    $receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $phaseRoot 'CONTROL_TEST_ACCEPTANCE.json') -Encoding utf8
    Write-Output "CONTROL_SCHEDULER_PASS checks=$count run=$runRoot"
} finally {
    Set-Location $oldLocation
}
