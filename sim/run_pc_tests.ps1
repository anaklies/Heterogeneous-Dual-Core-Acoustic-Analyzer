param([Parameter(Mandatory=$true)][string]$PythonExecutable)
$pkg=Split-Path $PSScriptRoot -Parent
Push-Location (Join-Path $pkg 'src/project/apps/sixmic-desktop')
try { & $PythonExecutable -m pytest tests; exit $LASTEXITCODE } finally {Pop-Location}
