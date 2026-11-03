$ErrorActionPreference='Stop'
$runRoot=Join-Path $PSScriptRoot 'cache/lease'
New-Item -ItemType Directory -Force -Path $runRoot | Out-Null
$original=Get-Location
try {
    Set-Location $runRoot
    & 'D:/2025.2/Vivado/bin/xvlog.bat' --sv (Join-Path $PSScriptRoot 'frontend_lease.sv') (Join-Path $PSScriptRoot 'tb_frontend_lease.sv') *> compile.log
    if($LASTEXITCODE -ne 0){throw 'lease compile failed'}
    & 'D:/2025.2/Vivado/bin/xelab.bat' tb_frontend_lease -s frontend_lease_test -debug typical *> elaborate.log
    if($LASTEXITCODE -ne 0){throw 'lease elaboration failed'}
    & 'D:/2025.2/Vivado/bin/xsim.bat' frontend_lease_test -runall *> simulate.log
    if($LASTEXITCODE -ne 0){throw 'lease simulation failed'}
    $result=Get-Content -LiteralPath simulate.log -Raw
    if($result -notmatch 'FRONTEND_LEASE_PASS checks=(\d+)'){throw 'lease PASS marker missing'}
    Write-Output "FRONTEND_LEASE_PASS checks=$($Matches[1])"
} finally {Set-Location $original}
