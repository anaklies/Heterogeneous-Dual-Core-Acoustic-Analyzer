param(
  [Parameter(Mandatory=$true)][string]$Bundle,
  [string]$Target = 'D:\echo'
)
$ErrorActionPreference='Stop'
$report = @{}
function Sha256([string]$p){ (Get-FileHash -Algorithm SHA256 -LiteralPath $p).Hash.ToLowerInvariant() }
$exe = Join-Path $Bundle 'echo.exe'
if(-not (Test-Path $exe)){ throw "missing bundle exe: $exe" }
$proc = Get-Process -Name echo -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$Target\*" }
if($proc){
  $report['stoppedProcesses'] = @($proc | ForEach-Object { $_.Id })
  $proc | Stop-Process -Force
  Start-Sleep -Milliseconds 800
}
$robocopy = Start-Process -FilePath 'robocopy.exe' -ArgumentList @($Bundle,$Target,'/MIR','/NFL','/NDL','/NJH','/NJS','/R:2','/W:1') -Wait -PassThru
$report['robocopyExit'] = $robocopy.ExitCode
if($robocopy.ExitCode -ge 8){ throw "robocopy failed: $($robocopy.ExitCode)" }
$srcFiles = Get-ChildItem -LiteralPath $Bundle -Recurse -File
$dstFiles = Get-ChildItem -LiteralPath $Target -Recurse -File
$report['sourceFileCount'] = $srcFiles.Count
$report['targetFileCount'] = $dstFiles.Count
$report['exeSHA256'] = Sha256 (Join-Path $Target 'echo.exe')
$report['expectedExeSHA256'] = Sha256 $exe
if($report['exeSHA256'] -ne $report['expectedExeSHA256']){ throw 'installed echo.exe hash mismatch' }
$started = Start-Process -FilePath (Join-Path $Target 'echo.exe') -WorkingDirectory $Target -PassThru
$report['startedProcessId'] = $started.Id
$report['target'] = $Target
$out = Join-Path (Split-Path -Parent $Bundle) 'PC_INSTALL.json'
($report | ConvertTo-Json -Depth 4) | Set-Content -LiteralPath $out -Encoding UTF8
Write-Output ($report | ConvertTo-Json -Depth 4)
