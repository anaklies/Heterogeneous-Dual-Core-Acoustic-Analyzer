param([Parameter(Mandatory=$true)][string]$Vivado)
$ErrorActionPreference='Stop'
$pkg=Split-Path $PSScriptRoot -Parent
$work=Join-Path $PSScriptRoot 'work/pl'
if(Test-Path $work){throw 'Use a new work directory; existing build is preserved.'}
Expand-Archive -LiteralPath (Join-Path $pkg 'board/project/recoverable_project.zip') -DestinationPath $work
$project=Join-Path $work 'instrument_board'
Copy-Item -Path (Join-Path $pkg 'src/pl_project/*') -Destination $project -Recurse -Force
& $Vivado -mode batch -source (Join-Path $PSScriptRoot 'rebuild_pl.tcl') -tclargs $project (Join-Path $PSScriptRoot 'out/pl')
if($LASTEXITCODE -ne 0){throw 'Vivado failed; preserve logs.'}
