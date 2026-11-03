param([Parameter(Mandatory=$true)][string]$Bootgen)
$ErrorActionPreference='Stop'
$pkg=Split-Path $PSScriptRoot -Parent
$dest=Join-Path $PSScriptRoot 'out/boot'
New-Item -ItemType Directory -Force $dest | Out-Null
Push-Location (Join-Path $pkg 'board/boot_components')
try { & $Bootgen -arch zynq -image boot.bif -o (Join-Path $dest 'BOOT.BIN') -w on; if($LASTEXITCODE -ne 0){throw 'bootgen failed'} } finally {Pop-Location}
