#Requires -Version 5.1
<#
.SYNOPSIS
    Build + verify the supplementary portable ZIP for echo.

.DESCRIPTION
    The handoff brief allows a portable ZIP as a supplement to the installer
    (not a replacement). This script packages the verified onedir GUI bundle plus
    the BackendCheck diagnostic bundle and the license texts, then verifies the
    ZIP by extracting it to a throw-away directory and running:
      * echo.exe --self-test                    (windowed exe, captured via the
                                                 opt-in packaging runtime hook)
      * echo.exe --smoke-gui 3                  (offscreen GUI startup)
      * SixMic3D-BackendCheck.exe --self-test   (installed-layout protocol data)
    All child processes run with a scrubbed PATH, throw-away cwd/TEMP and a
    workspace SIXMIC_USER_DATA_DIR override.

    This is supplementary deployment evidence; it is NOT a substitute for the
    Windows installer or for a clean-VM test.

    Exit codes: 0 = portable ZIP built and verified; 1 = verification failed;
                2 = missing inputs.
#>
[CmdletBinding()]
param(
    [string]$LogRoot,
    [string]$Version,
    [switch]$SkipVerify,
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$ScriptDir = $PSScriptRoot
$AppDir = Split-Path -Parent $ScriptDir
$VenvPython = Join-Path $AppDir '.venv\Scripts\python.exe'
$DistRoot = Join-Path $AppDir 'dist'
$DesktopBundle = Join-Path $DistRoot 'echo'
$BackendBundle = Join-Path $DistRoot 'SixMic3D-BackendCheck'
$LicenseDir = Join-Path $ScriptDir 'licenses'
$UiMarkerTool = Join-Path $ScriptDir 'tools\ui_marker.py'
$PortableOutDir = Join-Path $DistRoot 'portable'
if (-not $Version -or $Version.Trim().Length -eq 0) { $Version = (Get-Content -LiteralPath (Join-Path $ScriptDir 'VERSION') -Raw).Trim() }
$ZipName = 'echo-Portable-x64-' + $Version + '.zip'
$ZipPath = Join-Path $PortableOutDir $ZipName
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
if (-not $LogRoot -or $LogRoot.Trim().Length -eq 0) { $LogRoot = Join-Path $ScriptDir 'build-logs' }
$LogDir = Join-Path $LogRoot ($Stamp + '-portable')
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$BuildLog = Join-Path $LogDir 'build_portable_zip.log'
$script:BuildLogPath = $BuildLog

function Write-Log { param([string]$Message, [string]$Color = 'Gray') Write-Host $Message -ForegroundColor $Color; Add-Content -LiteralPath $script:BuildLogPath -Value $Message -Encoding utf8 }
function Write-Step { param([string]$M) Write-Log -Message ''; Write-Log -Message ('=== ' + $M + ' ===') -Color Cyan }
function Write-Pass { param([string]$M) Write-Log -Message ('PASS  ' + $M) -Color Green }
function Write-Warn2 { param([string]$M) Write-Log -Message ('WARN  ' + $M) -Color Yellow }
function Write-Fail { param([string]$M) Write-Log -Message ('FAIL  ' + $M) -Color Red }
function Write-Info2 { param([string]$M) Write-Log -Message ('      ' + $M) }

function Invoke-CapturedProcess {
    param([string]$FilePath, [string]$Arguments, [string]$WorkingDirectory, [string]$StdoutPath, [string]$StderrPath, [int]$TimeoutMs)
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $psi.Arguments = $Arguments
    $psi.WorkingDirectory = $WorkingDirectory
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $proc = [System.Diagnostics.Process]::Start($psi)
    $stdout = $proc.StandardOutput.ReadToEnd()
    $stderr = $proc.StandardError.ReadToEnd()
    $timedOut = -not $proc.WaitForExit($TimeoutMs)
    if ($timedOut -and -not $proc.HasExited) { try { $proc.Kill() } catch { }; try { $proc.WaitForExit() } catch { } }
    try { $proc.WaitForExit() } catch { }
    $exitCode = $null
    if ($proc.HasExited) { $exitCode = $proc.ExitCode }
    if ($StdoutPath) { Set-Content -LiteralPath $StdoutPath -Value $stdout -Encoding utf8 }
    if ($StderrPath) { Set-Content -LiteralPath $StderrPath -Value $stderr -Encoding utf8 }
    return [pscustomobject]@{ ExitCode = $exitCode; TimedOut = $timedOut }
}

function Read-TextFileSafe {
    param([string]$Path)
    if (-not $Path) { return '' }
    if (-not (Test-Path -LiteralPath $Path)) { return '' }
    try { return (Get-Content -LiteralPath $Path -Raw -Encoding utf8) } catch { return '' }
}

$script:QmlErrorPattern = '(QQmlApplicationEngine failed|Failed to load component|QML_LOAD_FAILED|ReferenceError|TypeError:|is not a type|is not defined|Cannot assign|Unable to assign|QML module not found|module "[^"]+" is not installed|Cannot load library|file:///[^\s]*\.qml:[0-9]+)'
function Find-QmlErrors {
    param([string[]]$Texts)
    $found = New-Object System.Collections.Generic.List[string]
    foreach ($text in $Texts) {
        if (-not $text) { continue }
        foreach ($line in ($text -split '[\r\n]+')) {
            if ($line.Trim().Length -eq 0) { continue }
            if ([regex]::IsMatch($line, $script:QmlErrorPattern, 'IgnoreCase')) {
                if (-not $found.Contains($line.Trim())) { $found.Add($line.Trim()) }
            }
        }
    }
    return $found
}

$report = [ordered]@{
    artifact = $ZipName
    status = 'RUNNING'
    startedAtLocal = (Get-Date -Format 'o')
    finishedAtLocal = $null
    version = $Version
    logDir = $LogDir
    logFile = $BuildLog
    zip = $null
    contents = $null
    verification = $null
    checks = @()
    unverifiedItems = @()
    errors = @()
}

function Add-Check {
    param([string]$Name, [bool]$Ok, [string]$Detail, [switch]$Warning)
    $status = 'PASS'
    if (-not $Ok) { $status = 'FAIL' }
    if ($Warning) { $status = 'WARN' }
    $script:report.checks += [ordered]@{ name = $Name; status = $status; detail = $Detail }
    if ($status -eq 'FAIL') { Write-Fail ($Name + ': ' + $Detail) } elseif ($status -eq 'WARN') { Write-Warn2 ($Name + ': ' + $Detail) } else { Write-Pass ($Name + ': ' + $Detail) }
}

function Complete-Report {
    param([string]$Status, [int]$ExitCode)
    $report.status = $Status
    $report.finishedAtLocal = (Get-Date -Format 'o')
    $reportPath = Join-Path $LogDir 'build_portable_zip.json'
    $report | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $reportPath -Encoding utf8
    Write-Log -Message ''
    Write-Log -Message ('SUMMARY: ' + $Status)
    Write-Log -Message ('  report json : ' + $reportPath)
    Write-Log -Message ('  build log   : ' + $BuildLog)
    Write-Log -Message ('  portable zip: ' + $ZipPath)
    exit $ExitCode
}

Write-Log -Message ('echo portable ZIP - ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz'))
Write-Log -Message ('log dir: ' + $LogDir)

if (-not (Test-Path -LiteralPath (Join-Path $DesktopBundle 'echo.exe'))) { Write-Fail ('desktop bundle missing: ' + $DesktopBundle); Complete-Report -Status 'MISSING_INPUTS' -ExitCode 2 }
$residueDir = Join-Path $DesktopBundle '_internal\user-data'
if (Test-Path -LiteralPath $residueDir) { Write-Fail ('refusing to package bundle test residue: ' + $residueDir); Complete-Report -Status 'MISSING_INPUTS' -ExitCode 2 }

Write-Step '1/5 stage portable tree'
$staging = Join-Path $LogDir 'staging'
if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
New-Item -ItemType Directory -Force -Path $staging | Out-Null
$stageApp = Join-Path $staging 'echo'
Copy-Item -LiteralPath $DesktopBundle -Destination $stageApp -Recurse -Force
$stageBackend = Join-Path $staging 'BackendCheck'
if (Test-Path -LiteralPath $BackendBundle) { Copy-Item -LiteralPath $BackendBundle -Destination $stageBackend -Recurse -Force }
$stageLicenses = Join-Path $staging 'licenses'
Copy-Item -LiteralPath $LicenseDir -Destination $stageLicenses -Recurse -Force

$uiMarkerJson = & $VenvPython $UiMarkerTool '--json' 2>&1
$uiMarker = $null
try { $uiMarker = ($uiMarkerJson | Out-String) | ConvertFrom-Json } catch { $uiMarker = $null }
$uiSha = 'UNKNOWN'
if ($uiMarker) { $uiSha = [string]$uiMarker.uiSha256 }
$report.unverifiedItems += 'Portable ZIP is a supplementary deliverable; the installer remains the primary distribution form and no clean-VM test was performed.'

$portableReadme = @(
    'echo portable (Windows x64)',
    '================================',
    'Version: ' + $Version,
    'UI freeze marker uiSha256: ' + $uiSha,
    '',
    'This portable package contains the same onedir GUI bundle the installer ships.',
    'Unzip anywhere the current user can write and run echo\echo.exe.',
    'Python, Qt or Node do NOT need to be installed.',
    '',
    'Optional headless backend diagnostic:',
    '  BackendCheck\SixMic3D-BackendCheck.exe --self-test',
    '',
    'Writable user data (settings, recordings, logs, export) is stored in',
    '%LOCALAPPDATA%\echo (legacy %LOCALAPPDATA%\SixMic3D data is migrated on',
    'first launch when possible) and never next to the executables.',
    '',
    'Licenses: see licenses\ (LGPL/GPL texts for Qt/PySide6, Python, PyInstaller,',
    'protocol notice). This portable ZIP and its executables are NOT code-signed.',
    '',
    'Generated: ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz'),
    'Source tree: apps/sixmic-desktop (see packaging/README.md for full evidence).'
) -join [string]([char]13) + [string]([char]10)
Set-Content -LiteralPath (Join-Path $staging 'README-PORTABLE.txt') -Value $portableReadme -Encoding utf8

$stagedFiles = @(Get-ChildItem -LiteralPath $staging -Recurse -File)
$stagedBytes = [long](($stagedFiles | Measure-Object -Property Length -Sum).Sum)
Write-Pass ('staged ' + $stagedFiles.Count + ' files, ' + $stagedBytes + ' bytes')

Write-Step '2/5 create ZIP'
New-Item -ItemType Directory -Force -Path $PortableOutDir | Out-Null
if (Test-Path -LiteralPath $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory($staging, $ZipPath, [System.IO.Compression.CompressionLevel]::Optimal, $false)
$zipItem = Get-Item -LiteralPath $ZipPath
$zipHash = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
$report.zip = [ordered]@{ path = $ZipPath; bytes = $zipItem.Length; sha256 = $zipHash; fileName = $ZipName }
$report.contents = [ordered]@{ stagedFiles = $stagedFiles.Count; stagedBytes = $stagedBytes; topLevel = @('echo/', 'BackendCheck/', 'licenses/', 'README-PORTABLE.txt'); uiSha256 = $uiSha }
Add-Check -Name 'zip-created' -Ok ($zipItem.Length -gt 0) -Detail ($ZipPath + ' bytes=' + $zipItem.Length + ' sha256=' + $zipHash)
Write-Pass ('portable ZIP: ' + $ZipPath + ' bytes=' + $zipItem.Length + ' sha256=' + $zipHash)

if ($SkipVerify) {
    Write-Warn2 'portable ZIP verification skipped (-SkipVerify)'
    $report.unverifiedItems += 'Portable ZIP extraction/run verification skipped (-SkipVerify).'
    Complete-Report -Status 'BUILT_UNVERIFIED' -ExitCode 0
}

Write-Step '3/5 extract ZIP to throw-away directory'
$extractRoot = Join-Path $LogDir 'portable-extract'
if (Test-Path -LiteralPath $extractRoot) { Remove-Item -LiteralPath $extractRoot -Recurse -Force }
[System.IO.Compression.ZipFile]::ExtractToDirectory($ZipPath, $extractRoot)
$extractedApp = Join-Path $extractRoot 'echo\echo.exe'
$extractedBackend = Join-Path $extractRoot 'BackendCheck\SixMic3D-BackendCheck.exe'
Add-Check -Name 'zip-extracted-gui-exe' -Ok (Test-Path -LiteralPath $extractedApp) -Detail $extractedApp
Add-Check -Name 'zip-extracted-backend-exe' -Ok (Test-Path -LiteralPath $extractedBackend) -Detail $extractedBackend
$extractedFiles = @(Get-ChildItem -LiteralPath $extractRoot -Recurse -File)
Write-Pass ('extracted ' + $extractedFiles.Count + ' files')

Write-Step '4/5 run extracted GUI offscreen + backend self-test'
$verifyCwd = Join-Path $LogDir 'verify-cwd'
$verifyTemp = Join-Path $LogDir 'verify-temp'
$verifyUserData = Join-Path $LogDir 'verify-userdata'
New-Item -ItemType Directory -Force -Path $verifyCwd | Out-Null
New-Item -ItemType Directory -Force -Path $verifyTemp | Out-Null
$minPath = (@((Join-Path $env:SystemRoot 'System32'), $env:SystemRoot, (Join-Path $env:SystemRoot 'System32\Wbem'), (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0')) | Where-Object { Test-Path -LiteralPath $_ }) -join ';'
$savedEnv = @{
    PATH = $env:PATH; PYTHONPATH = $env:PYTHONPATH; PYTHONHOME = $env:PYTHONHOME; VIRTUAL_ENV = $env:VIRTUAL_ENV
    QT_PLUGIN_PATH = $env:QT_PLUGIN_PATH; QML2_IMPORT_PATH = $env:QML2_IMPORT_PATH; QML_IMPORT_PATH = $env:QML_IMPORT_PATH
    TEMP = $env:TEMP; TMP = $env:TMP; SIXMIC_USER_DATA_DIR = $env:SIXMIC_USER_DATA_DIR
    QT_QPA_PLATFORM = $env:QT_QPA_PLATFORM; QT_QUICK_BACKEND = $env:QT_QUICK_BACKEND
    QT_ASSUME_STDERR_HAS_CONSOLE = $env:QT_ASSUME_STDERR_HAS_CONSOLE; SIXMIC_PACKAGING_GUI_LOG = $env:SIXMIC_PACKAGING_GUI_LOG
}
$guiStdout = Join-Path $LogDir 'portable-gui.stdout.log'
$guiStderr = Join-Path $LogDir 'portable-gui.stderr.log'
$guiCapture = Join-Path $LogDir 'portable-gui.capture.log'
$stStdout = Join-Path $LogDir 'portable-selftest.stdout.log'
$stStderr = Join-Path $LogDir 'portable-selftest.stderr.log'
$stCapture = Join-Path $LogDir 'portable-selftest.capture.log'
$beStdout = Join-Path $LogDir 'portable-backend.stdout.log'
$beStderr = Join-Path $LogDir 'portable-backend.stderr.log'
$guiRun = $null
$selfTestRun = $null
$backendRun = $null
try {
    $env:PATH = $minPath
    foreach ($name in @('PYTHONPATH','PYTHONHOME','VIRTUAL_ENV','QT_PLUGIN_PATH','QML2_IMPORT_PATH','QML_IMPORT_PATH')) { Remove-Item -Path ('Env:' + $name) -ErrorAction SilentlyContinue }
    $env:TEMP = $verifyTemp
    $env:TMP = $verifyTemp
    $env:SIXMIC_USER_DATA_DIR = $verifyUserData
    $env:SIXMIC_PACKAGING_GUI_LOG = $stCapture
    $selfTestRun = Invoke-CapturedProcess -FilePath $extractedApp -Arguments '--self-test' -WorkingDirectory $verifyCwd -StdoutPath $stStdout -StderrPath $stStderr -TimeoutMs ($TimeoutSeconds * 1000)
    $env:SIXMIC_PACKAGING_GUI_LOG = $guiCapture
    $env:QT_QPA_PLATFORM = 'offscreen'
    $env:QT_QUICK_BACKEND = 'software'
    $env:QT_ASSUME_STDERR_HAS_CONSOLE = '1'
    $guiRun = Invoke-CapturedProcess -FilePath $extractedApp -Arguments '--smoke-gui 3' -WorkingDirectory $verifyCwd -StdoutPath $guiStdout -StderrPath $guiStderr -TimeoutMs ($TimeoutSeconds * 1000)
    if (Test-Path -LiteralPath $extractedBackend) {
        $env:SIXMIC_PACKAGING_GUI_LOG = ''
        $portableProtocol = Join-Path $extractRoot 'BackendCheck\protocol'
        $backendArgs = '--self-test --protocol-dir "' + $portableProtocol + '"'
        $backendRun = Invoke-CapturedProcess -FilePath $extractedBackend -Arguments $backendArgs -WorkingDirectory $verifyCwd -StdoutPath $beStdout -StderrPath $beStderr -TimeoutMs ($TimeoutSeconds * 1000)
    }
} finally {
    foreach ($key in $savedEnv.Keys) {
        if ($null -eq $savedEnv[$key]) { Remove-Item -Path ('Env:' + $key) -ErrorAction SilentlyContinue }
        else { Set-Item -Path ('Env:' + $key) -Value $savedEnv[$key] }
    }
}
$guiText = Read-TextFileSafe -Path $guiCapture
$guiOut = Read-TextFileSafe -Path $guiStdout
$guiErr = Read-TextFileSafe -Path $guiStderr
$qmlErrors = @(Find-QmlErrors -Texts @($guiText, $guiOut, $guiErr))
$guiMarker = ''
if ($guiText -match 'SMOKE_GUI_OK' -or $guiOut -match 'SMOKE_GUI_OK') { $guiMarker = 'SMOKE_GUI_OK' }
elseif ($guiText -match 'SMOKE_GUI_WARNINGS' -or $guiOut -match 'SMOKE_GUI_WARNINGS') { $guiMarker = 'SMOKE_GUI_WARNINGS' }
$stText = Read-TextFileSafe -Path $stCapture
$beText = Read-TextFileSafe -Path $beStdout
$bePass = [bool]($beText -match 'SELF-TEST PASS')
$report.verification = [ordered]@{
    extractRoot = $extractRoot
    guiExitCode = $guiRun.ExitCode
    guiTimedOut = $guiRun.TimedOut
    guiMarker = $guiMarker
    qmlErrors = @($qmlErrors)
    selfTestExitCode = $selfTestRun.ExitCode
    selfTestPassMarker = [bool]($stText -match 'SELF-TEST PASS')
    backendSelfTestExitCode = $null
    backendSelfTestPassMarker = $bePass
    logs = [ordered]@{ guiCapture = $guiCapture; guiStdout = $guiStdout; guiStderr = $guiStderr; selfTestCapture = $stCapture; backendStdout = $beStdout; backendStderr = $beStderr }
}
if ($null -ne $backendRun) { $report.verification.backendSelfTestExitCode = $backendRun.ExitCode }
$qmlErrorDetail = @($qmlErrors) -join ' | '
if (-not $qmlErrorDetail) { $qmlErrorDetail = 'none' }
Add-Check -Name 'portable-self-test' -Ok (($selfTestRun.ExitCode -eq 0) -and ([bool]($stText -match 'SELF-TEST PASS'))) -Detail ('exit=' + $selfTestRun.ExitCode + ' marker=' + [string]($stText -match 'SELF-TEST PASS'))
Add-Check -Name 'portable-offscreen-gui' -Ok (($guiRun.ExitCode -eq 0) -and -not $guiRun.TimedOut) -Detail ('exit=' + $guiRun.ExitCode + ' marker=' + $guiMarker)
Add-Check -Name 'portable-no-qml-errors' -Ok (@($qmlErrors).Count -eq 0) -Detail $qmlErrorDetail
if ($null -ne $backendRun) { Add-Check -Name 'portable-backend-self-test' -Ok (($backendRun.ExitCode -eq 0) -and $bePass) -Detail ('exit=' + $backendRun.ExitCode + ' marker=' + [string]$bePass) }

Write-Step '5/5 evidence'
$userDataCreated = Test-Path -LiteralPath $verifyUserData
Add-Check -Name 'portable-user-data-override-created' -Ok $userDataCreated -Detail ('SIXMIC_USER_DATA_DIR=' + $verifyUserData)
$report.unverifiedItems += 'Portable ZIP was verified by extracting and running it offscreen; real desktop compositor/GPU rendering and interactive UI acceptance are out of scope here.'
$report.unverifiedItems += 'No clean Windows VM test; only the current Windows 11 host was used.'
foreach ($item in $report.unverifiedItems) { Write-Warn2 ('- ' + $item) }
$failures = @($report.checks | Where-Object { $_.status -eq 'FAIL' })
if ($failures.Count -gt 0) { Complete-Report -Status 'FAIL' -ExitCode 1 }
Complete-Report -Status 'BUILT_VERIFIED_OFFSCREEN' -ExitCode 0
