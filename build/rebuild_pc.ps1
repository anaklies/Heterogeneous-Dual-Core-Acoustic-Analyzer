param([Parameter(Mandatory=$true)][string]$PythonExecutable)
$ErrorActionPreference='Stop'
$pkg=Split-Path $PSScriptRoot -Parent
$app=Join-Path $pkg 'src/project/apps/sixmic-desktop'
& (Join-Path $app 'packaging/build_desktop.ps1') -PythonExecutable $PythonExecutable -OutputRoot (Join-Path $PSScriptRoot 'out/pc') -TempRoot (Join-Path $pkg 'src/project/tmp/pc-build')
if($LASTEXITCODE -ne 0){throw 'Desktop build failed'}
