param([Parameter(Mandatory=$true)][string]$SdRoot)
$ErrorActionPreference='Stop'
if(!(Test-Path -LiteralPath $SdRoot -PathType Container)){throw 'Choose the mounted SD volume.'}
if([IO.Path]::GetPathRoot($SdRoot) -eq [IO.Path]::GetPathRoot($env:SystemRoot)){throw 'System drive rejected.'}
Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'sd') -File | Copy-Item -Destination $SdRoot -Force
Write-Host 'SD files copied. No formatting, QSPI or eMMC writes were performed.'
