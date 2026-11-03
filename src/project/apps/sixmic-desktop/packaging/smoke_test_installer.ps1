#Requires -Version 5.1
<#
.SYNOPSIS
    Install echo-Setup-x64.exe to a throw-away directory, verify it, uninstall.

.DESCRIPTION
    End-to-end smoke test of an already compiled installer:
      1. locate dist/installer/echo-Setup-x64.exe (or -InstallerPath)
      2. install to a fresh scratch directory with /VERYSILENT /DIR=...
      3. verify installed files (echo.exe, BackendCheck exe, protocol data,
         licenses, Qt platform plugin + QML dir when present)
      4. verify start-menu shortcut and the uninstall registry entry exist
      5. run the installed Headless BackendCheck.exe --self-test from a clean
         directory with the dev PATH scrubbed; require exit code 0 and final
         stdout line exactly "SELF-TEST PASS"; verify user data dir behaviour
      6. launch the installed windowed echo.exe offscreen
         (QT_QPA_PLATFORM=offscreen, QT_QUICK_BACKEND=software, scrubbed PATH,
         throw-away cwd, SIXMIC_USER_DATA_DIR override) with --smoke-gui 3;
         require exit 0 (window + QML root loaded) and no QML/Qt error lines in
         the opt-in capture log (packaging runtime hook rth_gui_log.py)
      7. verify the installation directory is not written to at runtime
      8. uninstall silently and prove user data under %LOCALAPPDATA%\echo is
         preserved (a marker file created by this script is kept; marker removed
         afterwards by this script, never by the product)
      9. remove the scratch installation, write a JSON report + logs

    If ISCC.exe (Inno Setup 6) is not installed and therefore no installer
    exists, the result is explicitly NOT_VERIFIED with that reason (exit 3).
    This session cannot install Inno Setup (no silent tool downloads).

    No final echo GUI acceptance is claimed: the desktop GUI is not launched
    or visually verified here (main-agent UI merge pending). The script reports
    exactly what it exercised.

.PARAMETER InstallerPath
    Installer exe to test. Default: apps/sixmic-desktop/dist/installer/echo-Setup-x64.exe

.PARAMETER InstallDir
    Throw-away installation directory. Default: <build-logs>/<timestamp>/install-target

.PARAMETER KeepInstallation
    Do not uninstall at the end (leaves the test installation in place).

.PARAMETER SkipUserDataMarker
    Do not create/verify the %LOCALAPPDATA%\echo preservation marker.

.NOTES
    Exit codes:
      0 = smoke test PASS
      1 = smoke test FAIL
      3 = NOT VERIFIED (installer missing / Inno Setup 6 not installed / prerequisites absent)
#>
[CmdletBinding()]
param(
    [string]$InstallerPath,
    [string]$InstallDir,
    [string]$LogRoot,
    [switch]$KeepInstallation,
    [switch]$SkipUserDataMarker,
    [int]$TimeoutSeconds = 300
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$ScriptDir = $PSScriptRoot
$AppDir = Split-Path -Parent $ScriptDir
$DistRoot = Join-Path $AppDir 'dist'
$DefaultInstaller = Join-Path $DistRoot 'installer\echo-Setup-x64.exe'
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
if (-not $LogRoot -or $LogRoot.Trim().Length -eq 0) { $LogRoot = Join-Path $ScriptDir 'build-logs' }
$LogDir = Join-Path $LogRoot $Stamp
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$SmokeLog = Join-Path $LogDir 'smoke_test_installer.log'
$script:BuildLogPath = $SmokeLog

function Write-Log {
    param([string]$Message, [string]$Color = 'Gray')
    Write-Host $Message -ForegroundColor $Color
    Add-Content -LiteralPath $script:BuildLogPath -Value $Message -Encoding utf8
}
function Write-Step { param([string]$M) Write-Log -Message ''; Write-Log -Message ('=== ' + $M + ' ===') -Color Cyan }
function Write-Pass { param([string]$M) Write-Log -Message ('PASS  ' + $M) -Color Green }
function Write-Warn2 { param([string]$M) Write-Log -Message ('WARN  ' + $M) -Color Yellow }
function Write-Fail { param([string]$M) Write-Log -Message ('FAIL  ' + $M) -Color Red }
function Write-Info2 { param([string]$M) Write-Log -Message ('      ' + $M) }

function Find-IsccSimple {
    $candidates = New-Object System.Collections.Generic.List[string]
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) { $candidates.Add($cmd.Source) }
    $pfx86 = [System.Environment]::GetEnvironmentVariable('ProgramFiles(x86)')
    $roots = @($env:ProgramFiles, $pfx86, (Join-Path $env:LOCALAPPDATA 'Programs'), $env:LOCALAPPDATA, 'C:\Program Files', 'C:\Program Files (x86)')
    foreach ($root in $roots) {
        if (-not $root) { continue }
        foreach ($sub in @('Inno Setup 6', 'Inno Setup 6 (x64)')) {
            $candidates.Add((Join-Path (Join-Path $root $sub) 'ISCC.exe'))
        }
    }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    return $null
}

function Find-UninstallEntry {
    $roots = @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'
    )
    foreach ($root in $roots) {
        $keys = Get-ChildItem -LiteralPath $root -ErrorAction SilentlyContinue
        foreach ($key in $keys) {
            $props = Get-ItemProperty -LiteralPath $key.PSPath -ErrorAction SilentlyContinue
            # StrictMode-safe: registry keys may have no DisplayName value at all.
            if ($null -eq $props) { continue }
            $names = @($props.PSObject.Properties | ForEach-Object { $_.Name })
            # Product display name is 'echo' (all shipped artefact names are echo now).
            if (($names -contains 'DisplayName') -and ($props.DisplayName -eq 'echo')) { return $key.PSPath }
        }
    }
    return $null
}

function Get-MetadataInventoryHash {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return 'ABSENT' }
    $entries = Get-ChildItem -LiteralPath $Path -Recurse -File -ErrorAction SilentlyContinue | Sort-Object FullName | ForEach-Object {
        $_.FullName.Substring($Path.Length) + '|' + $_.Length + '|' + $_.LastWriteTimeUtc.Ticks
    }
    $dump = Join-Path $LogDir ('inventory-' + [guid]::NewGuid().ToString('N') + '.txt')
    Set-Content -LiteralPath $dump -Value ($entries -join [Environment]::NewLine) -Encoding utf8
    $hash = (Get-FileHash -LiteralPath $dump -Algorithm SHA256).Hash.ToLowerInvariant()
    Remove-Item -LiteralPath $dump -Force
    return $hash
}

function Invoke-Scrubbed {
    param(
        [string]$ExePath,
        [string]$WorkDir,
        [string]$TempDir,
        [string]$StdoutPath,
        [string]$StderrPath,
        [string]$ProtocolDir,
        [string]$UserDataDir
    )
    $saved = @{
        PATH = $env:PATH; PYTHONPATH = $env:PYTHONPATH; PYTHONHOME = $env:PYTHONHOME
        VIRTUAL_ENV = $env:VIRTUAL_ENV; QT_PLUGIN_PATH = $env:QT_PLUGIN_PATH
        QML2_IMPORT_PATH = $env:QML2_IMPORT_PATH; QML_IMPORT_PATH = $env:QML_IMPORT_PATH
        SIXMIC_USER_DATA_DIR = $env:SIXMIC_USER_DATA_DIR; TEMP = $env:TEMP; TMP = $env:TMP
    }
    $minPath = (@(
            (Join-Path $env:SystemRoot 'System32'), $env:SystemRoot,
            (Join-Path $env:SystemRoot 'System32\Wbem'),
            (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0')
        ) | Where-Object { Test-Path -LiteralPath $_ }) -join ';'
    $result = [ordered]@{ exitCode = $null; lastLine = ''; markerPass = $false; pythonOnPath = $false; timedOut = $false; dataDirCreated = $false; evidenceFile = $null; permissionDenied = $false }
    try {
        $env:PATH = $minPath
        foreach ($name in @('PYTHONPATH','PYTHONHOME','VIRTUAL_ENV','QT_PLUGIN_PATH','QML2_IMPORT_PATH','QML_IMPORT_PATH')) {
            Remove-Item -Path ('Env:' + $name) -ErrorAction SilentlyContinue
        }
        $env:TEMP = $TempDir
        $env:TMP = $TempDir
        $env:PYTHONIOENCODING = 'utf-8'
        if ($UserDataDir) { $env:SIXMIC_USER_DATA_DIR = $UserDataDir }
        else { Remove-Item -Path 'Env:SIXMIC_USER_DATA_DIR' -ErrorAction SilentlyContinue }
        $result.pythonOnPath = $null -ne (Get-Command python -ErrorAction SilentlyContinue)
        $arguments = '--self-test'
        if ($ProtocolDir) { $arguments = '--self-test --protocol-dir "' + $ProtocolDir + '"' }
        $run = Invoke-CapturedProcess -FilePath $ExePath -Arguments $arguments -WorkingDirectory $WorkDir -StdoutPath $StdoutPath -StderrPath $StderrPath -TimeoutMs ($TimeoutSeconds * 1000)
        $result.timedOut = $run.TimedOut
        if ($null -ne $run.ExitCode) { $result.exitCode = [int]$run.ExitCode }
        else { $result.exitCode = -1 }
    } finally {
        foreach ($key in $saved.Keys) {
            $value = $saved[$key]
            if ($null -eq $value) { Remove-Item -Path ('Env:' + $key) -ErrorAction SilentlyContinue }
            else { Set-Item -Path ('Env:' + $key) -Value $value }
        }
    }
    if (Test-Path -LiteralPath $StdoutPath) {
        $lines = Get-Content -LiteralPath $StdoutPath -Encoding utf8 | Where-Object { $_.Trim().Length -gt 0 }
        if ($lines -and $lines.Count -gt 0) { $result.lastLine = [string]($lines[$lines.Count - 1]).Trim() }
        $text = Get-Content -LiteralPath $StdoutPath -Raw -Encoding utf8
        $result.markerPass = ($result.lastLine -ceq 'SELF-TEST PASS')
        if ($text -match 'WinError 5' -or $text -match 'PermissionError') { $result.permissionDenied = $true }
    }
    if (Test-Path -LiteralPath $StderrPath) {
        $errText = Get-Content -LiteralPath $StderrPath -Raw -Encoding utf8
        if ($errText -match 'WinError 5' -or $errText -match 'PermissionError') { $result.permissionDenied = $true }
    }
    if ($UserDataDir) {
        $result.dataDirCreated = Test-Path -LiteralPath $UserDataDir
        $candidateEvidence = Join-Path $UserDataDir 'evidence\backend-selftest.json'
        if (Test-Path -LiteralPath $candidateEvidence) { $result.evidenceFile = $candidateEvidence }
    }
    return [pscustomobject]$result
}

function Invoke-CapturedProcess {
    param(
        [string]$FilePath,
        [string]$Arguments,
        [string]$WorkingDirectory,
        [string]$StdoutPath,
        [string]$StderrPath,
        [int]$TimeoutMs
    )
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
    if ($timedOut -and -not $proc.HasExited) {
        try { $proc.Kill() } catch { }
        try { $proc.WaitForExit() } catch { }
    }
    try { $proc.WaitForExit() } catch { }
    $exitCode = $null
    if ($proc.HasExited) { $exitCode = $proc.ExitCode }
    if ($StdoutPath) { Set-Content -LiteralPath $StdoutPath -Value $stdout -Encoding utf8 }
    if ($StderrPath) { Set-Content -LiteralPath $StderrPath -Value $stderr -Encoding utf8 }
    return [pscustomobject]@{ ExitCode = $exitCode; TimedOut = $timedOut }
}

$script:QmlErrorPattern = '(QQmlApplicationEngine failed|Failed to load component|QML_LOAD_FAILED|ReferenceError|TypeError:|is not a type|is not defined|Cannot assign|Unable to assign|QML module not found|module "[^"]+" is not installed|Cannot load library|file:///[^\s]*\.qml:[0-9]+)'

function Read-TextFileSafe {
    param([string]$Path)
    if (-not $Path) { return '' }
    if (-not (Test-Path -LiteralPath $Path)) { return '' }
    try { return (Get-Content -LiteralPath $Path -Raw -Encoding utf8) } catch { return '' }
}

function Find-QmlErrors {
    param([string[]]$Texts)
    $found = New-Object System.Collections.Generic.List[string]
    foreach ($text in $Texts) {
        if (-not $text) { continue }
        foreach ($line in ($text -split "[\r\n]+")) {
            if ($line.Trim().Length -eq 0) { continue }
            if ([regex]::IsMatch($line, $script:QmlErrorPattern, 'IgnoreCase')) {
                if (-not $found.Contains($line.Trim())) { $found.Add($line.Trim()) }
            }
        }
    }
    return $found
}

function Invoke-ScrubbedGui {
    param(
        [string]$ExePath,
        [string]$WorkDir,
        [string]$TempDir,
        [string]$UserDataDir,
        [string]$CapturePath,
        [string]$StdoutPath,
        [string]$StderrPath,
        [double]$Seconds,
        [int]$TimeoutSeconds
    )
    $saved = @{
        PATH = $env:PATH; PYTHONPATH = $env:PYTHONPATH; PYTHONHOME = $env:PYTHONHOME
        VIRTUAL_ENV = $env:VIRTUAL_ENV; QT_PLUGIN_PATH = $env:QT_PLUGIN_PATH
        QML2_IMPORT_PATH = $env:QML2_IMPORT_PATH; QML_IMPORT_PATH = $env:QML_IMPORT_PATH
        TEMP = $env:TEMP; TMP = $env:TMP; SIXMIC_USER_DATA_DIR = $env:SIXMIC_USER_DATA_DIR
        QT_QPA_PLATFORM = $env:QT_QPA_PLATFORM; QT_QUICK_BACKEND = $env:QT_QUICK_BACKEND
        QT_ASSUME_STDERR_HAS_CONSOLE = $env:QT_ASSUME_STDERR_HAS_CONSOLE
        SIXMIC_PACKAGING_GUI_LOG = $env:SIXMIC_PACKAGING_GUI_LOG
    }
    $minPath = (@(
            (Join-Path $env:SystemRoot 'System32'), $env:SystemRoot,
            (Join-Path $env:SystemRoot 'System32\Wbem'),
            (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0')
        ) | Where-Object { Test-Path -LiteralPath $_ }) -join ';'
    $result = [ordered]@{
        exitCode = $null; timedOut = $false; qmlErrors = @(); marker = $null
        userDataDir = $UserDataDir; userDataDirCreated = $false; userDataHasUiDir = $false
        capture = $CapturePath; stdout = $StdoutPath; stderr = $StderrPath; pythonOnPath = $false
    }
    try {
        $env:PATH = $minPath
        foreach ($name in @('PYTHONPATH','PYTHONHOME','VIRTUAL_ENV','QT_PLUGIN_PATH','QML2_IMPORT_PATH','QML_IMPORT_PATH')) {
            Remove-Item -Path ('Env:' + $name) -ErrorAction SilentlyContinue
        }
        $env:TEMP = $TempDir
        $env:TMP = $TempDir
        $env:SIXMIC_USER_DATA_DIR = $UserDataDir
        $env:SIXMIC_PACKAGING_GUI_LOG = $CapturePath
        $env:QT_QPA_PLATFORM = 'offscreen'
        $env:QT_QUICK_BACKEND = 'software'
        $env:QT_ASSUME_STDERR_HAS_CONSOLE = '1'
        $result.pythonOnPath = $null -ne (Get-Command python -ErrorAction SilentlyContinue)
        $secondsInvariant = $Seconds.ToString([System.Globalization.CultureInfo]::InvariantCulture)
        $run = Invoke-CapturedProcess -FilePath $ExePath -Arguments ('--smoke-gui ' + $secondsInvariant) -WorkingDirectory $WorkDir -StdoutPath $StdoutPath -StderrPath $StderrPath -TimeoutMs ($TimeoutSeconds * 1000)
        $result.timedOut = $run.TimedOut
        if ($null -ne $run.ExitCode) { $result.exitCode = [int]$run.ExitCode } else { $result.exitCode = -1 }
    } finally {
        foreach ($key in $saved.Keys) {
            if ($null -eq $saved[$key]) { Remove-Item -Path ('Env:' + $key) -ErrorAction SilentlyContinue }
            else { Set-Item -Path ('Env:' + $key) -Value $saved[$key] }
        }
    }
    $captured = Read-TextFileSafe -Path $CapturePath
    $stdout = Read-TextFileSafe -Path $StdoutPath
    $stderr = Read-TextFileSafe -Path $StderrPath
    $result.qmlErrors = @(Find-QmlErrors -Texts @($captured, $stdout, $stderr))
    if ($captured -match 'SMOKE_GUI_OK') { $result.marker = 'SMOKE_GUI_OK' }
    elseif ($captured -match 'SMOKE_GUI_WARNINGS') { $result.marker = 'SMOKE_GUI_WARNINGS' }
    elseif ($stdout -match 'SMOKE_GUI_OK') { $result.marker = 'SMOKE_GUI_OK' }
    elseif ($stdout -match 'SMOKE_GUI_WARNINGS') { $result.marker = 'SMOKE_GUI_WARNINGS' }
    $result.userDataDirCreated = Test-Path -LiteralPath $UserDataDir
    $result.userDataHasUiDir = Test-Path -LiteralPath (Join-Path $UserDataDir 'ui')
    return [pscustomobject]$result
}

function Find-NativeExe {
    param([string]$Root, [string]$Name)
    $direct = Join-Path $Root $Name
    if (Test-Path -LiteralPath $direct) { return $direct }
    $found = Get-ChildItem -LiteralPath $Root -Recurse -File -Filter $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { return $found.FullName }
    return $null
}

# ------------------------------------------------------------------ report helpers
$report = [ordered]@{
    artifact = 'echo-Setup-x64.exe'
    status = 'RUNNING'
    startedAtLocal = (Get-Date -Format 'o')
    finishedAtLocal = $null
    logDir = $LogDir
    logFile = $SmokeLog
    installer = $null
    install = $null
    runtime = $null
    guiSmoke = $null
    uninstall = $null
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
    if ($status -eq 'FAIL') { Write-Fail ($Name + ': ' + $Detail) }
    elseif ($status -eq 'WARN') { Write-Warn2 ($Name + ': ' + $Detail) }
    else { Write-Pass ($Name + ': ' + $Detail) }
}

function Complete-Report {
    param([string]$Status, [int]$ExitCode)
    $report.status = $Status
    $report.finishedAtLocal = (Get-Date -Format 'o')
    $reportPath = Join-Path $LogDir 'smoke_test_installer.json'
    $report | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $reportPath -Encoding utf8
    Write-Log -Message ''
    Write-Log -Message ('SUMMARY: ' + $Status)
    Write-Log -Message ('  report json : ' + $reportPath)
    Write-Log -Message ('  smoke log   : ' + $SmokeLog)
    exit $ExitCode
}

# ------------------------------------------------------------------ main
Write-Log -Message ('echo installer smoke test - ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz'))
Write-Log -Message ('log dir: ' + $LogDir)

if (-not $InstallerPath -or $InstallerPath.Trim().Length -eq 0) { $InstallerPath = $DefaultInstaller }
$resolvedInstaller = $null
if (Test-Path -LiteralPath $InstallerPath -PathType Leaf) { $resolvedInstaller = (Resolve-Path -LiteralPath $InstallerPath).Path }
$report.installer = [ordered]@{ path = $InstallerPath; exists = ($null -ne $resolvedInstaller) }

if (-not $resolvedInstaller) {
    $iscc = Find-IsccSimple
    if (-not $iscc) {
        Write-Fail 'NOT VERIFIED: installer missing and Inno Setup 6 (ISCC.exe) is not installed on this machine.'
        Write-Info2 ('installer path checked: ' + $InstallerPath)
        Write-Info2 'Reason: Inno Setup 6 is not installed, so build_installer.ps1 reported NOT_BUILT_MISSING_TOOL and no installer was produced.'
        Write-Info2 'Manual prerequisite: install Inno Setup 6.3+ from https://jrsoftware.org/isdl.php, then run build_backend_check.ps1, build_desktop.ps1, build_installer.ps1, and this script.'
        Write-Info2 'This script never downloads or installs third-party tools.'
        $report.unverifiedItems += 'Installer smoke test NOT VERIFIED: Inno Setup 6 (ISCC.exe) not installed; no installer was built by this environment.'
        Complete-Report -Status 'NOT_VERIFIED_MISSING_INNO_SETUP' -ExitCode 3
    }
    Write-Fail ('NOT VERIFIED: installer not built although ISCC.exe exists at ' + $iscc)
    Write-Info2 'Run build_installer.ps1 first (and build_desktop.ps1 if dist/echo is missing).'
    $report.unverifiedItems += 'Installer smoke test NOT VERIFIED: installer exe missing (run build_installer.ps1).'
    Complete-Report -Status 'NOT_VERIFIED_INSTALLER_MISSING' -ExitCode 3
}

$installerHash = (Get-FileHash -LiteralPath $resolvedInstaller -Algorithm SHA256).Hash.ToLowerInvariant()
$report.installer.sha256 = $installerHash
$report.installer.bytes = (Get-Item -LiteralPath $resolvedInstaller).Length
Write-Info2 ('installer: ' + $resolvedInstaller)
Write-Info2 ('sha256   : ' + $installerHash)

if (-not $InstallDir -or $InstallDir.Trim().Length -eq 0) { $InstallDir = Join-Path $LogDir 'install-target' }
$InstallDir = [System.IO.Path]::GetFullPath($InstallDir)
if (Test-Path -LiteralPath $InstallDir) { throw ('refusing to install into existing directory: ' + $InstallDir) }
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$scopedTemp = Join-Path $LogDir 'temp'
New-Item -ItemType Directory -Force -Path $scopedTemp | Out-Null
$env:TEMP = $scopedTemp
$env:TMP = $scopedTemp

$realAppData = Join-Path $env:LOCALAPPDATA 'echo'
$legacyAppData = Join-Path $env:LOCALAPPDATA 'SixMic3D'
$userDataHashBefore = Get-MetadataInventoryHash -Path $realAppData
$userDataExistedBefore = Test-Path -LiteralPath $realAppData
if (-not $SkipUserDataMarker) {
    New-Item -ItemType Directory -Force -Path $realAppData | Out-Null
    $markerPath = Join-Path $realAppData '.smoke-test-preserve-marker'
    Set-Content -LiteralPath $markerPath -Value ('smoke test ' + (Get-Date -Format 'o')) -Encoding utf8
    Write-Info2 ('created user-data preservation marker: ' + $markerPath)
}

try {
    # ---------------------------------------------------------- install
    Write-Step '1/7 silent install to throw-away directory'
    $setupLog = Join-Path $LogDir 'installer-setup.log'
    $setupArgs = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="' + $InstallDir + '" /LOG="' + $setupLog + '"'
    Write-Info2 ('command: ' + $resolvedInstaller + ' ' + $setupArgs)
    $setupStart = Get-Date
    $setup = Start-Process -FilePath $resolvedInstaller -ArgumentList $setupArgs -Wait -PassThru -NoNewWindow
    $setupSeconds = [math]::Round(((Get-Date) - $setupStart).TotalSeconds, 1)
    $report.install = [ordered]@{ installDir = $InstallDir; exitCode = $setup.ExitCode; durationSeconds = $setupSeconds; setupLog = $setupLog }
    Add-Check -Name 'installer-exit-code' -Ok ($setup.ExitCode -eq 0) -Detail ('exit=' + $setup.ExitCode + ' duration=' + $setupSeconds + 's')

    # ---------------------------------------------------------- installed files
    Write-Step '2/7 installed files'
    $appExe = Join-Path $InstallDir 'echo.exe'
    Add-Check -Name 'echo.exe-present' -Ok (Test-Path -LiteralPath $appExe) -Detail $appExe
    $backendExe = Join-Path $InstallDir 'BackendCheck\SixMic3D-BackendCheck.exe'
    Add-Check -Name 'BackendCheck-exe-present' -Ok (Test-Path -LiteralPath $backendExe) -Detail $backendExe
    $protocolCheck = Join-Path $InstallDir 'BackendCheck\protocol\errors\ERROR_CATALOG.json'
    Add-Check -Name 'backend-protocol-data-present' -Ok (Test-Path -LiteralPath $protocolCheck) -Detail $protocolCheck
    $licenseCheck = Join-Path $InstallDir 'licenses\THIRD_PARTY_LICENSES.txt'
    Add-Check -Name 'licenses-present' -Ok (Test-Path -LiteralPath $licenseCheck) -Detail $licenseCheck
    $platformPlugin = Find-NativeExe -Root $InstallDir -Name 'qwindows.dll'
    Add-Check -Name 'qt-platform-plugin-present' -Ok ($null -ne $platformPlugin) -Detail ([string]$platformPlugin)
    $qmlDir = Get-ChildItem -LiteralPath $InstallDir -Recurse -Directory -Filter 'qml' -ErrorAction SilentlyContinue | Select-Object -First 1
    $qmlDetail = 'none'
    if ($qmlDir) { $qmlDetail = [string]$qmlDir.FullName }
    Add-Check -Name 'qt-qml-modules-present' -Ok ($null -ne $qmlDir) -Detail $qmlDetail
    $internalDir = Join-Path $InstallDir '_internal'
    Add-Check -Name 'pyinstaller-internal-present' -Ok (Test-Path -LiteralPath $internalDir) -Detail $internalDir

    # ---------------------------------------------------------- shortcuts + registry
    Write-Step '3/7 start menu shortcut + uninstall entry'
    $startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\echo'
    $shortcuts = @(Get-ChildItem -LiteralPath $startMenu -Filter '*.lnk' -ErrorAction SilentlyContinue)
    Add-Check -Name 'start-menu-shortcuts' -Ok ($shortcuts.Count -gt 0) -Detail ($startMenu + ' (' + $shortcuts.Count + ' .lnk)')
    $uninstallKey = Find-UninstallEntry
    Add-Check -Name 'uninstall-registry-entry' -Ok ($null -ne $uninstallKey) -Detail ([string]$uninstallKey)

    # ---------------------------------------------------------- runtime self-test
    Write-Step '4/7 installed BackendCheck --self-test (scrubbed PATH)'
    $runtimeCwd = Join-Path $LogDir 'runtime-cwd'
    $runtimeTemp = Join-Path $LogDir 'runtime-temp'
    New-Item -ItemType Directory -Force -Path $runtimeCwd | Out-Null
    New-Item -ItemType Directory -Force -Path $runtimeTemp | Out-Null
    $installInventoryBefore = Get-MetadataInventoryHash -Path $InstallDir
    $backendProtocolDir = Join-Path $InstallDir 'BackendCheck\protocol'
    $stdout1 = Join-Path $LogDir 'runtime-selftest.stdout.log'
    $stderr1 = Join-Path $LogDir 'runtime-selftest.stderr.log'
    $attempt1 = Invoke-Scrubbed -ExePath $backendExe -WorkDir $runtimeCwd -TempDir $runtimeTemp -StdoutPath $stdout1 -StderrPath $stderr1 -ProtocolDir $backendProtocolDir -UserDataDir $null
    $runtime = [ordered]@{ attempts = @(); verifiedBy = $null; installDirUnchanged = $null }
    $runtime.attempts += [ordered]@{ label = 'default-localappdata'; exitCode = $attempt1.exitCode; lastLine = $attempt1.lastLine; markerPass = $attempt1.markerPass; timedOut = $attempt1.timedOut; pythonOnPath = $attempt1.pythonOnPath; dataDirCreated = $attempt1.dataDirCreated; evidenceFile = $attempt1.evidenceFile; permissionDenied = $attempt1.permissionDenied }
    if (-not ($attempt1.markerPass -and $attempt1.exitCode -eq 0)) {
        Write-Warn2 ('default %LOCALAPPDATA% run did not pass (exit=' + $attempt1.exitCode + '); retrying with SIXMIC_USER_DATA_DIR scratch override')
        $overrideDir = Join-Path $LogDir 'runtime-userdata'
        $stdout2 = Join-Path $LogDir 'runtime-selftest.override.stdout.log'
        $stderr2 = Join-Path $LogDir 'runtime-selftest.override.stderr.log'
        $attempt2 = Invoke-Scrubbed -ExePath $backendExe -WorkDir $runtimeCwd -TempDir $runtimeTemp -StdoutPath $stdout2 -StderrPath $stderr2 -ProtocolDir $backendProtocolDir -UserDataDir $overrideDir
        $runtime.attempts += [ordered]@{ label = 'override-scratch'; exitCode = $attempt2.exitCode; lastLine = $attempt2.lastLine; markerPass = $attempt2.markerPass; timedOut = $attempt2.timedOut; pythonOnPath = $attempt2.pythonOnPath; dataDirCreated = $attempt2.dataDirCreated; evidenceFile = $attempt2.evidenceFile; permissionDenied = $attempt2.permissionDenied }
    }
    $passing = @($runtime.attempts | Where-Object { $_.markerPass -and $_.exitCode -eq 0 })
    Add-Check -Name 'installed-backendcheck-selftest' -Ok ($passing.Count -gt 0) -Detail (($runtime.attempts | ForEach-Object { $_.label + ':exit=' + $_.exitCode + ',marker=[' + $_.lastLine + ']' }) -join '; ')
    if ($passing.Count -gt 0) {
        $runtime.verifiedBy = $passing[0].label
        Add-Check -Name 'selftest-no-dev-python-on-PATH' -Ok (-not $passing[0].pythonOnPath) -Detail ('python-on-scrubbed-PATH=' + $passing[0].pythonOnPath)
        Add-Check -Name 'selftest-user-data-dir-created' -Ok $passing[0].dataDirCreated -Detail ([string]$passing[0].evidenceFile)
        if (-not ($passing[0].label -eq 'default-localappdata')) {
            $report.unverifiedItems += 'real %LOCALAPPDATA%\echo creation was not verified in this environment (child writes to %LOCALAPPDATA% denied by harness sandbox); self-test verified through SIXMIC_USER_DATA_DIR override. Re-check on a clean Windows VM. The installed BackendCheck diagnostic is a frozen backend artifact whose own default data dir remains %LOCALAPPDATA%\SixMic3D; the GUI product uses echo (runtime hook preference/migration).'
        }
    }
    $installInventoryAfter = Get-MetadataInventoryHash -Path $InstallDir
    $runtime.installDirUnchanged = ($installInventoryBefore -eq $installInventoryAfter)
    Add-Check -Name 'install-dir-not-written-at-runtime' -Ok ($installInventoryBefore -eq $installInventoryAfter) -Detail 'metadata inventory before/after self-test'
    $report.runtime = $runtime

    # ---------------------------------------------------------- installed GUI offscreen smoke
    Write-Step '5/7 installed GUI offscreen smoke (window/QML load, scrubbed PATH)'
    $guiCwd = Join-Path $LogDir 'gui-cwd'
    $guiTemp = Join-Path $LogDir 'gui-temp'
    $guiUserData = Join-Path $LogDir 'gui-userdata'
    foreach ($dir in @($guiCwd, $guiTemp)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $installInventoryBeforeGui = Get-MetadataInventoryHash -Path $InstallDir
    $guiSmoke = Invoke-ScrubbedGui -ExePath $appExe -WorkDir $guiCwd -TempDir $guiTemp -UserDataDir $guiUserData -CapturePath (Join-Path $LogDir 'gui-smoke.capture.log') -StdoutPath (Join-Path $LogDir 'gui-smoke.stdout.log') -StderrPath (Join-Path $LogDir 'gui-smoke.stderr.log') -Seconds 3 -TimeoutSeconds $TimeoutSeconds
    $installInventoryAfterGui = Get-MetadataInventoryHash -Path $InstallDir
    $report.guiSmoke = [ordered]@{
        exe = $appExe; exitCode = $guiSmoke.exitCode; timedOut = $guiSmoke.timedOut
        qmlErrors = @($guiSmoke.qmlErrors); marker = $guiSmoke.marker
        userDataDir = $guiSmoke.userDataDir; userDataDirCreated = $guiSmoke.userDataDirCreated; userDataHasUiDir = $guiSmoke.userDataHasUiDir
        pythonOnPath = $guiSmoke.pythonOnPath; installDirUnchanged = ($installInventoryBeforeGui -eq $installInventoryAfterGui)
        capture = $guiSmoke.capture; stdout = $guiSmoke.stdout; stderr = $guiSmoke.stderr
    }
    $qmlErrorDetail = @($guiSmoke.qmlErrors) -join ' | '
    if (-not $qmlErrorDetail) { $qmlErrorDetail = 'none' }
    Add-Check -Name 'gui-offscreen-smoke-exit' -Ok ($guiSmoke.exitCode -eq 0 -and -not $guiSmoke.timedOut) -Detail ('exit=' + $guiSmoke.exitCode + ' timedOut=' + $guiSmoke.timedOut + ' marker=' + [string]$guiSmoke.marker)
    Add-Check -Name 'gui-no-dev-python-on-PATH' -Ok (-not $guiSmoke.pythonOnPath) -Detail ('python-on-scrubbed-PATH=' + $guiSmoke.pythonOnPath)
    Add-Check -Name 'gui-no-qml-errors' -Ok (@($guiSmoke.qmlErrors).Count -eq 0) -Detail $qmlErrorDetail
    Add-Check -Name 'gui-user-data-dir-created' -Ok $guiSmoke.userDataDirCreated -Detail ([string]$guiSmoke.userDataDir + ' hasUiDir=' + $guiSmoke.userDataHasUiDir)
    Add-Check -Name 'gui-install-dir-not-written-at-runtime' -Ok ($installInventoryBeforeGui -eq $installInventoryAfterGui) -Detail 'metadata inventory before/after GUI offscreen smoke'
    if (-not (Test-Path -LiteralPath $guiSmoke.capture)) {
        $report.unverifiedItems += 'GUI smoke capture log was not created by the windowed exe (opt-in runtime hook); exit code 0 stands as the window/QML-loaded evidence.'
    }
    if (-not $guiSmoke.userDataHasUiDir) {
        $report.unverifiedItems += 'GUI smoke created the SIXMIC_USER_DATA_DIR override but not its ui/ subdirectory.'
    }

    # ---------------------------------------------------------- uninstall
    Write-Step '6/7 silent uninstall'
    if ($KeepInstallation) {
        Write-Warn2 '-KeepInstallation set: skipping uninstall (smoke test incomplete without it)'
        Add-Check -Name 'uninstall-skipped' -Ok $false -Detail '-KeepInstallation' -Warning
    } else {
        $uninstaller = Find-NativeExe -Root $InstallDir -Name 'unins000.exe'
        Add-Check -Name 'uninstaller-present' -Ok ($null -ne $uninstaller) -Detail ([string]$uninstaller)
        if ($uninstaller) {
            $uninstallArgs = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART'
            Write-Info2 ('command: ' + $uninstaller + ' ' + $uninstallArgs)
            $uninstall = Start-Process -FilePath $uninstaller -ArgumentList $uninstallArgs -Wait -PassThru -NoNewWindow
            Add-Check -Name 'uninstall-exit-code' -Ok ($uninstall.ExitCode -eq 0) -Detail ('exit=' + $uninstall.ExitCode)
            Start-Sleep -Seconds 2
            $appExeAfter = Test-Path -LiteralPath $appExe
            Add-Check -Name 'install-dir-removed' -Ok (-not $appExeAfter) -Detail ('echo.exe still present=' + $appExeAfter)
            $shortcutsAfter = @(Get-ChildItem -LiteralPath $startMenu -Filter '*.lnk' -ErrorAction SilentlyContinue)
            Add-Check -Name 'start-menu-shortcuts-removed' -Ok ($shortcutsAfter.Count -eq 0) -Detail (($shortcutsAfter | ForEach-Object { $_.Name }) -join ', ')
            $uninstallKeyAfter = Find-UninstallEntry
            Add-Check -Name 'uninstall-registry-entry-removed' -Ok ($null -eq $uninstallKeyAfter) -Detail ([string]$uninstallKeyAfter)
            $report.uninstall = [ordered]@{ uninstaller = $uninstaller; exitCode = $uninstall.ExitCode; installDirRemaining = (Test-Path -LiteralPath $InstallDir) }
        }
    }

    # ---------------------------------------------------------- user data preservation
    Write-Step '7/7 user data preservation'
    $userDataHashAfter = Get-MetadataInventoryHash -Path $realAppData
    $markerPath = Join-Path $realAppData '.smoke-test-preserve-marker'
    $markerPreserved = -not $SkipUserDataMarker -and (Test-Path -LiteralPath $markerPath)
    $preserved = $true
    if (-not $SkipUserDataMarker) { $preserved = $markerPreserved }
    Add-Check -Name 'user-data-preserved-after-uninstall' -Ok $preserved -Detail ('%LOCALAPPDATA%\echo marker preserved=' + $markerPreserved + ' dataExistedBefore=' + $userDataExistedBefore + ' hashBefore=' + $userDataHashBefore + ' hashAfter=' + $userDataHashAfter + ' legacySixMic3DExists=' + (Test-Path -LiteralPath $legacyAppData))
    if (-not $userDataExistedBefore) {
        $report.unverifiedItems += 'user data dir did not exist before this smoke test; preservation proof relies on the script-created marker file only.'
    }
} finally {
    if (-not $SkipUserDataMarker) {
        $cleanupMarker = Join-Path $realAppData '.smoke-test-preserve-marker'
        if (Test-Path -LiteralPath $cleanupMarker) { Remove-Item -LiteralPath $cleanupMarker -Force }
    }
    if (-not $KeepInstallation) {
        if ((Test-Path -LiteralPath $InstallDir) -and (Test-Path -LiteralPath (Join-Path $InstallDir 'unins000.exe'))) {
            Write-Warn2 'installation directory still contains an uninstaller; leaving it for manual inspection: ' + $InstallDir
        } elseif (Test-Path -LiteralPath $InstallDir) {
            $leftover = @(Get-ChildItem -LiteralPath $InstallDir -Force -ErrorAction SilentlyContinue)
            if ($leftover.Count -eq 0) { Remove-Item -LiteralPath $InstallDir -Force -Recurse -ErrorAction SilentlyContinue }
        }
    }
}

$failures = @($report.checks | Where-Object { $_.status -eq 'FAIL' })
$report.unverifiedItems += 'echo GUI visual/functional acceptance is NOT claimed from this smoke test: the installed GUI was launched offscreen and had to load its window/QML without errors, but visual review, interaction walk-through and a clean Windows VM test remain the frontend acceptance owner.'
$report.unverifiedItems += 'Real desktop compositor / GPU rendering path was not exercised (QT_QPA_PLATFORM=offscreen + QT_QUICK_BACKEND=software).'
$report.unverifiedItems += 'Installer is not code-signed (Authenticode status recorded by build_installer.ps1); SmartScreen reputation unknown.'
if ($failures.Count -gt 0) {
    Write-Fail ('smoke test FAILED: ' + $failures.Count + ' check(s) failed')
    Complete-Report -Status 'FAIL' -ExitCode 1
}
Write-Pass 'installer smoke test PASSED (install -> backend self-test -> GUI offscreen smoke -> uninstall -> user data preserved)'
Complete-Report -Status 'PASS' -ExitCode 0
