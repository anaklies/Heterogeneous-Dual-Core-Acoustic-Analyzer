#Requires -Version 5.1
<#
.SYNOPSIS
    Verify packaged echo startup robustness (the reported crash fix).

.DESCRIPTION
    Regression test for the reported packaged-exe crash
        "Unhandled exception ... [WinError 5] ... AppData\Local\SixMic3D\logs"
    main.py now picks a writable user-data directory before any component starts
    (packaging runtime hook rth_sixmic_paths.py -> prefers %LOCALAPPDATA%\echo with
    legacy SixMic3D fallback/migration; then main.py chain: <app>/user-data ->
    %TEMP%/echo -> cwd/echo-user-data -> ~/echo).

    This script runs the PACKAGED windowed exe with a scrubbed environment and
    checks, in order:
      A. --smoke-gui 3 with SIXMIC_USER_DATA_DIR UNSET: must exit 0, print
         SMOKE_GUI_OK, log no QML errors and no PermissionError; records which
         fallback directory was chosen;
      B. --smoke-gui 3 with a deliberately UNWRITABLE SIXMIC_USER_DATA_DIR:
         must fall back to a writable candidate, exit 0, SMOKE_GUI_OK;
      C. --self-test with SIXMIC_USER_DATA_DIR UNSET: exit 0 + SELF-TEST PASS;
      D. static guard check: main.py contains the pre-startup data-dir
         preparation, the APP_INIT_FAILED wrapper, the crash-log/QMessageBox
         guard and return code 4 (the interactive error-dialog path itself can
         only be triggered when all six candidates are unwritable, which cannot
         be forced safely on this host; it is therefore code-verified here).

    Exit codes: 0 = all startup checks pass; 1 = FAIL; 2 = missing inputs.
#>
[CmdletBinding()]
param(
    [string]$ExePath,
    [string]$LogRoot,
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$ScriptDir = $PSScriptRoot
$AppDir = Split-Path -Parent $ScriptDir
$VenvPython = Join-Path $AppDir '.venv\Scripts\python.exe'
$DefaultExe = Join-Path $AppDir 'dist\echo\echo.exe'
$UiMarkerTool = Join-Path $ScriptDir 'tools\ui_marker.py'
$MainPy = Join-Path $AppDir 'main.py'
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
if (-not $LogRoot -or $LogRoot.Trim().Length -eq 0) { $LogRoot = Join-Path $ScriptDir 'build-logs' }
$LogDir = Join-Path $LogRoot ($Stamp + '-startup-robustness')
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$VerifyLog = Join-Path $LogDir 'verify_packaged_startup.log'
$script:BuildLogPath = $VerifyLog

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
    artifact = 'echo.exe startup robustness'
    status = 'RUNNING'
    startedAtLocal = (Get-Date -Format 'o')
    finishedAtLocal = $null
    logDir = $LogDir
    logFile = $VerifyLog
    uiSha256 = $null
    exe = $null
    noOverrideStartup = $null
    unwritableOverrideStartup = $null
    noOverrideSelfTest = $null
    staticGuard = $null
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
    $reportPath = Join-Path $LogDir 'packaged_startup_verification.json'
    $report | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $reportPath -Encoding utf8
    Write-Log -Message ''
    Write-Log -Message ('SUMMARY: ' + $Status)
    Write-Log -Message ('  report json : ' + $reportPath)
    Write-Log -Message ('  verify log  : ' + $VerifyLog)
    exit $ExitCode
}

if (-not $ExePath -or $ExePath.Trim().Length -eq 0) { $ExePath = $DefaultExe }
if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) { Write-Fail ('packaged exe not found: ' + $ExePath); Complete-Report -Status 'MISSING_EXE' -ExitCode 2 }
$resolvedExe = (Resolve-Path -LiteralPath $ExePath).Path
$exeItem = Get-Item -LiteralPath $resolvedExe
$exeHash = (Get-FileHash -LiteralPath $resolvedExe -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Log -Message ('echo packaged startup robustness verification - ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz'))
Write-Log -Message ('exe     : ' + $resolvedExe)
Write-Log -Message ('log dir : ' + $LogDir)

Write-Step '1/5 inputs + UI freeze marker'
$uiMarker = $null
if (Test-Path -LiteralPath $UiMarkerTool) {
    $uiOut = & $VenvPython $UiMarkerTool '--json' 2>&1
    try { $uiMarker = ($uiOut | Out-String) | ConvertFrom-Json } catch { $uiMarker = $null }
}
if ($uiMarker) { $report.uiSha256 = [string]$uiMarker.uiSha256 }
$report.exe = [ordered]@{ path = $resolvedExe; bytes = $exeItem.Length; sha256 = $exeHash; version = [string]$exeItem.VersionInfo.FileVersion; authenticodeStatus = [string](Get-AuthenticodeSignature -LiteralPath $resolvedExe).Status }
Add-Check -Name 'exe-present' -Ok $true -Detail ($resolvedExe + ' bytes=' + $exeItem.Length + ' sha256=' + $exeHash)
if ($uiMarker) { Write-Pass ('UI marker = ' + $uiMarker.uiSha256) } else { Write-Warn2 'ui marker tool unavailable; continuing' }

Write-Step '2/5 static guard check of main.py robustness code'
$mainText = Read-TextFileSafe -Path $MainPy
$guards = [ordered]@{
    prepare_user_data_dir = [bool]($mainText -match 'def prepare_user_data_dir\(')
    localappdata_candidate = [bool]($mainText -match 'LOCALAPPDATA')
    echo_candidate = [bool]($mainText -match 'Path\(local\) / "echo"')
    legacy_fallback = [bool]($mainText -match '"SixMic3D"')
    legacy_migration = [bool]($mainText -match 'copytree')
    app_dir_candidate = [bool]($mainText -match 'APP_ROOT / "user-data"')
    temp_candidate = [bool]($mainText -match 'gettempdir\(\)\) / "echo"')
    exported_env = [bool]($mainText -match 'os\.environ\["SIXMIC_USER_DATA_DIR"\] = str\(candidate\)')
    app_init_failed = [bool]($mainText -match 'APP_INIT_FAILED')
    crash_log = [bool]($mainText -match 'echo-crash\.log')
    startup_error_log = [bool]($mainText -match 'echo-startup-error\.log')
    dialog_title = [bool]($mainText -match 'QMessageBox\.critical\(None, "echo"')
    startup_error_dialog = [bool]($mainText -match 'def show_startup_error\(')
    return_code_4 = [bool]($mainText -match 'return 4')
}
$report.staticGuard = $guards
$guardFailures = @($guards.Keys | Where-Object { -not $guards[$_] })
Add-Check -Name 'main-py-robustness-guards' -Ok ($guardFailures.Count -eq 0) -Detail (($guards.Keys | ForEach-Object { $_ + '=' + $guards[$_] }) -join ', ')
$report.unverifiedItems += 'The interactive startup error dialog (QMessageBox) path is code-verified only: it triggers only when all user-data candidates are unwritable, which cannot be forced safely on this host.'
$report.unverifiedItems += 'Echo user-data selection/migration is exercised with a redirected writable %LOCALAPPDATA%; the real user-profile primary path remains sandbox-denied for unsigned exes here (fallback verified instead).'

# The echo user-data preference, legacy fallback and one-time migration are owned by
# main.py itself (frozen UI marker a6e8d1b3); no packaging runtime hook is shipped.
$report.echoUserDataOwnership = 'main.py prepare_user_data_dir() (preferred %LOCALAPPDATA%\echo, legacy SixMic3D fallback, one-time copytree migration, SIXMIC_USER_DATA_DIR export)'
Add-Check -Name 'echo-userdata-owned-by-main-py' -Ok ($guards.echo_candidate -and $guards.legacy_fallback -and $guards.legacy_migration) -Detail ('echo_candidate=' + $guards.echo_candidate + ' legacy_fallback=' + $guards.legacy_fallback + ' migration=' + $guards.legacy_migration)

$minPath = (@((Join-Path $env:SystemRoot 'System32'), $env:SystemRoot, (Join-Path $env:SystemRoot 'System32\Wbem'), (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0')) | Where-Object { Test-Path -LiteralPath $_ }) -join ';'
$runCwd = Join-Path $LogDir 'cwd'
$runTemp = Join-Path $LogDir 'temp'
New-Item -ItemType Directory -Force -Path $runCwd | Out-Null
New-Item -ItemType Directory -Force -Path $runTemp | Out-Null
$bundleRoot = Split-Path -Parent $resolvedExe
$fallbackCandidates = @(
    (Join-Path $bundleRoot '_internal\user-data'),
    (Join-Path $bundleRoot 'user-data'),
    (Join-Path $env:LOCALAPPDATA 'echo'),
    (Join-Path $env:LOCALAPPDATA 'SixMic3D'),
    (Join-Path $runTemp 'echo'),
    (Join-Path $runTemp 'SixMic3D'),
    (Join-Path $runCwd 'echo-user-data'),
    (Join-Path $runCwd 'SixMic3D-user-data'),
    (Join-Path $env:USERPROFILE 'echo'),
    (Join-Path $env:USERPROFILE 'SixMic3D')
)

$caseC = $null
$caseM = $null
$scratchLocal = ''
$legacyScratch = ''

function Find-ChosenFallbackDir {
    $now = Get-Date
    foreach ($candidate in $fallbackCandidates) {
        $logs = Join-Path $candidate 'logs'
        if (-not (Test-Path -LiteralPath $logs)) { continue }
        try {
            $stamp = (Get-Item -LiteralPath $logs).LastWriteTime
            if ($stamp -ge $now.AddMinutes(-10)) { return $candidate }
        } catch { }
    }
    foreach ($candidate in $fallbackCandidates) {
        if (Test-Path -LiteralPath (Join-Path $candidate 'logs')) { return $candidate }
    }
    return ''
}

function Invoke-SmokeCase {
    param([string]$Label, [string]$OverrideValue, [string]$Arguments)
    $stdout = Join-Path $LogDir ($Label + '.stdout.log')
    $stderr = Join-Path $LogDir ($Label + '.stderr.log')
    $capture = Join-Path $LogDir ($Label + '.capture.log')
    $previousUserData = $env:SIXMIC_USER_DATA_DIR
    $previousLog = $env:SIXMIC_PACKAGING_GUI_LOG
    try {
        if ($OverrideValue) { $env:SIXMIC_USER_DATA_DIR = $OverrideValue } else { Remove-Item -Path 'Env:SIXMIC_USER_DATA_DIR' -ErrorAction SilentlyContinue }
        $env:SIXMIC_PACKAGING_GUI_LOG = $capture
        $run = Invoke-CapturedProcess -FilePath $resolvedExe -Arguments $Arguments -WorkingDirectory $runCwd -StdoutPath $stdout -StderrPath $stderr -TimeoutMs ($TimeoutSeconds * 1000)
    } finally {
        if ($null -eq $previousUserData) { Remove-Item -Path 'Env:SIXMIC_USER_DATA_DIR' -ErrorAction SilentlyContinue } else { $env:SIXMIC_USER_DATA_DIR = $previousUserData }
        if ($null -eq $previousLog) { Remove-Item -Path 'Env:SIXMIC_PACKAGING_GUI_LOG' -ErrorAction SilentlyContinue } else { $env:SIXMIC_PACKAGING_GUI_LOG = $previousLog }
    }
    $captured = Read-TextFileSafe -Path $capture
    $outText = Read-TextFileSafe -Path $stdout
    $errText = Read-TextFileSafe -Path $stderr
    $combined = $captured + [string]([char]10) + $outText + [string]([char]10) + $errText
    $qmlIssues = @(Find-QmlErrors -Texts @($captured, $outText, $errText))
    $marker = ''
    if ($captured -match 'SMOKE_GUI_OK' -or $outText -match 'SMOKE_GUI_OK') { $marker = 'SMOKE_GUI_OK' }
    elseif ($captured -match 'SMOKE_GUI_WARNINGS' -or $outText -match 'SMOKE_GUI_WARNINGS') { $marker = 'SMOKE_GUI_WARNINGS' }
    $selfTestPass = [bool]($captured -match 'SELF-TEST PASS' -or $outText -match 'SELF-TEST PASS')
    $permissionError = [bool]($combined -match 'PermissionError|WinError 5|Access is denied')
    $traceback = [bool]($combined -match 'Traceback \(most recent call last\)|Unhandled exception')
    $chosenFallback = Find-ChosenFallbackDir
    return [ordered]@{
        label = $Label
        arguments = $Arguments
        override = $OverrideValue
        exitCode = $run.ExitCode
        timedOut = $run.TimedOut
        marker = $marker
        selfTestPass = $selfTestPass
        qmlErrors = @($qmlIssues)
        permissionError = $permissionError
        pythonTraceback = $traceback
        fallbackUserDataDir = $chosenFallback
        fallbackUserDataInsideBundle = [bool]($chosenFallback -and $chosenFallback.StartsWith($bundleRoot, [System.StringComparison]::OrdinalIgnoreCase))
        capture = $capture
        stdout = $stdout
        stderr = $stderr
    }
}

$previousPath = $env:PATH
$previousTemp = $env:TEMP
$previousTmp = $env:TMP
$previousPlatform = $env:QT_QPA_PLATFORM
$previousBackend = $env:QT_QUICK_BACKEND
$previousConsole = $env:QT_ASSUME_STDERR_HAS_CONSOLE
try {
    $env:PATH = $minPath
    foreach ($name in @('PYTHONPATH','PYTHONHOME','VIRTUAL_ENV','QT_PLUGIN_PATH','QML2_IMPORT_PATH','QML_IMPORT_PATH')) { Remove-Item -Path ('Env:' + $name) -ErrorAction SilentlyContinue }
    $env:TEMP = $runTemp
    $env:TMP = $runTemp
    $env:QT_QPA_PLATFORM = 'offscreen'
    $env:QT_QUICK_BACKEND = 'software'
    $env:QT_ASSUME_STDERR_HAS_CONSOLE = '1'
    Write-Step '3/6 packaged startup WITHOUT SIXMIC_USER_DATA_DIR (reported-crash regression)'
    $caseA = Invoke-SmokeCase -Label 'no-override' -OverrideValue '' -Arguments '--smoke-gui 3'
    $caseD = Invoke-SmokeCase -Label 'no-override-selftest' -OverrideValue '' -Arguments '--self-test'
    Write-Step '4/6 packaged startup with deliberately UNWRITABLE SIXMIC_USER_DATA_DIR'
    $unwritable = Join-Path $env:SystemRoot 'System32\echo-unwritable-userdata'
    $caseB = Invoke-SmokeCase -Label 'unwritable-override' -OverrideValue $unwritable -Arguments '--smoke-gui 3'

    # ---------------------------------------------------------- echo user-data selection
    # Redirect %LOCALAPPDATA% to a writable scratch dir so the real preference/migration
    # logic in main.py is exercised (the harness profile itself denies unsigned-exe writes).
    Write-Step '5/6 echo user-data selection + legacy migration (redirected writable LOCALAPPDATA)'
    $scratchLocal = Join-Path $LogDir 'localappdata-echo'
    $legacyScratch = Join-Path $LogDir 'localappdata-echo-migration'
    $savedLocalAppData = $env:LOCALAPPDATA
    try {
        Remove-Item -LiteralPath $scratchLocal -Recurse -Force -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Force -Path $scratchLocal | Out-Null
        $env:LOCALAPPDATA = $scratchLocal
        $caseC = Invoke-SmokeCase -Label 'echo-localappdata' -OverrideValue '' -Arguments '--smoke-gui 2'
        Remove-Item -LiteralPath $legacyScratch -Recurse -Force -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Force -Path (Join-Path $legacyScratch 'SixMic3D') | Out-Null
        Set-Content -LiteralPath (Join-Path $legacyScratch 'SixMic3D\legacy-marker.txt') -Value 'legacy SixMic3D user data marker' -Encoding utf8
        $env:LOCALAPPDATA = $legacyScratch
        $caseM = Invoke-SmokeCase -Label 'echo-localappdata-migration' -OverrideValue '' -Arguments '--smoke-gui 2'
    } finally {
        $env:LOCALAPPDATA = $savedLocalAppData
    }
} finally {
    $env:PATH = $previousPath
    $env:TEMP = $previousTemp
    $env:TMP = $previousTmp
    $env:QT_QPA_PLATFORM = $previousPlatform
    $env:QT_QUICK_BACKEND = $previousBackend
    $env:QT_ASSUME_STDERR_HAS_CONSOLE = $previousConsole
}
$report.noOverrideStartup = $caseA
$report.unwritableOverrideStartup = $caseB
$report.noOverrideSelfTest = $caseD

$echoDir = Join-Path $scratchLocal 'echo'
$echoSubdirs = @('logs', 'data', 'recordings', 'events', 'exports', 'ui', 'evidence', 'reports', 'screenshots')
$echoSubdirsPresent = @($echoSubdirs | Where-Object { Test-Path -LiteralPath (Join-Path $echoDir $_) })
$legacyInScratch = Test-Path -LiteralPath (Join-Path $scratchLocal 'SixMic3D')
$caseCOk = ($caseC -and $caseC.exitCode -eq 0 -and $caseC.marker -eq 'SMOKE_GUI_OK' -and @($caseC.qmlErrors).Count -eq 0 -and (-not $caseC.permissionError) -and (-not $caseC.pythonTraceback) -and (Test-Path -LiteralPath $echoDir) -and ($echoSubdirsPresent.Count -eq $echoSubdirs.Count) -and (-not $legacyInScratch))
$report.echoUserDataSelection = [ordered]@{
    case = $caseC
    redirectedLocalAppData = $scratchLocal
    expectedDir = $echoDir
    dirCreated = (Test-Path -LiteralPath $echoDir)
    subdirs = $echoSubdirsPresent
    legacyDirNotUsed = (-not $legacyInScratch)
}

$migrationTarget = Join-Path $legacyScratch 'echo'
$migrationMarker = Join-Path $migrationTarget 'legacy-marker.txt'
$migrationCopied = Test-Path -LiteralPath $migrationMarker
$legacyPreserved = Test-Path -LiteralPath (Join-Path $legacyScratch 'SixMic3D\legacy-marker.txt')
$caseMOk = ($caseM -and $caseM.exitCode -eq 0 -and $caseM.marker -eq 'SMOKE_GUI_OK' -and $migrationCopied -and $legacyPreserved)
$report.echoUserDataMigration = [ordered]@{
    case = $caseM
    redirectedLocalAppData = $legacyScratch
    echoDir = $migrationTarget
    legacyMarkerCopied = $migrationCopied
    legacyDirPreserved = $legacyPreserved
}

Write-Step '6/6 verdict + pristine-bundle cleanup'
# The writable-fallback startup test may create <bundle>/_internal/user-data (main.py
# APP_ROOT in the frozen app is _internal). Record its inventory for evidence, then
# remove it so the shipped bundle/installer/portable ZIP stay free of test residue.
$caseAOk = (($caseA.exitCode -eq 0) -and ($caseA.marker -eq 'SMOKE_GUI_OK') -and (@($caseA.qmlErrors).Count -eq 0) -and (-not $caseA.permissionError) -and (-not $caseA.pythonTraceback) -and (-not $caseA.timedOut))
$caseBOk = (($caseB.exitCode -eq 0) -and ($caseB.marker -eq 'SMOKE_GUI_OK') -and (@($caseB.qmlErrors).Count -eq 0) -and (-not $caseB.permissionError) -and (-not $caseB.pythonTraceback) -and (-not $caseB.timedOut))
$caseDOk = (($caseD.exitCode -eq 0) -and $caseD.selfTestPass -and (-not $caseD.permissionError) -and (-not $caseD.pythonTraceback))
$qmlDetailA = @($caseA.qmlErrors) -join ' | '
if (-not $qmlDetailA) { $qmlDetailA = 'none' }
$qmlDetailB = @($caseB.qmlErrors) -join ' | '
if (-not $qmlDetailB) { $qmlDetailB = 'none' }
Add-Check -Name 'startup-no-override-gui' -Ok $caseAOk -Detail ('exit=' + $caseA.exitCode + ' marker=' + $caseA.marker + ' qmlErrors=' + $qmlDetailA + ' permissionError=' + $caseA.permissionError + ' traceback=' + $caseA.pythonTraceback)
Add-Check -Name 'startup-no-override-fallback-used' -Ok ([bool]$caseA.fallbackUserDataDir) -Detail ('writable fallback user-data dir chosen: ' + $caseA.fallbackUserDataDir + ' (insideBundle=' + $caseA.fallbackUserDataInsideBundle + ')')
$bundleArtifactDir = ''
if ($caseA.fallbackUserDataInsideBundle -and $caseA.fallbackUserDataDir) { $bundleArtifactDir = $caseA.fallbackUserDataDir }
if ($caseB.fallbackUserDataInsideBundle -and $caseB.fallbackUserDataDir -and -not $bundleArtifactDir) { $bundleArtifactDir = $caseB.fallbackUserDataDir }
$caseACapture = $caseA.capture + '.pre-cleanup-inventory.log'
if ($bundleArtifactDir -and (Test-Path -LiteralPath $bundleArtifactDir)) {
    $bundleFiles = @(Get-ChildItem -LiteralPath $bundleArtifactDir -Recurse -File -ErrorAction SilentlyContinue)
    Set-Content -LiteralPath $caseACapture -Value (($bundleFiles | ForEach-Object { $_.FullName.Substring($bundleArtifactDir.Length) + '|' + $_.Length }) -join [string]([char]10)) -Encoding utf8
    Remove-Item -LiteralPath $bundleArtifactDir -Recurse -Force
}
$bundleRestored = (-not $bundleArtifactDir) -or (-not (Test-Path -LiteralPath $bundleArtifactDir))
$report.bundleCleanup = [ordered]@{ fallbackDir = $bundleArtifactDir; removed = [bool]$bundleArtifactDir; bundlePristine = $bundleRestored; inventoryLog = $caseACapture }
Add-Check -Name 'bundle-pristine-after-startup-tests' -Ok $bundleRestored -Detail ('test user-data removed from bundle: ' + [bool]$bundleArtifactDir)
Add-Check -Name 'startup-unwritable-override-falls-back' -Ok $caseBOk -Detail ('override=' + $caseB.override + ' exit=' + $caseB.exitCode + ' marker=' + $caseB.marker + ' qmlErrors=' + $qmlDetailB + ' permissionError=' + $caseB.permissionError)
Add-Check -Name 'startup-no-override-self-test' -Ok $caseDOk -Detail ('exit=' + $caseD.exitCode + ' SELF-TEST-PASS=' + $caseD.selfTestPass + ' permissionError=' + $caseD.permissionError)
Add-Check -Name 'main-py-resilience-guards' -Ok ($guardFailures.Count -eq 0) -Detail 'prepare_user_data_dir + APP_INIT_FAILED + crash log + QMessageBox guard + return 4 present'
Add-Check -Name 'echo-userdata-dir-selected' -Ok $caseCOk -Detail ('exit=' + $caseC.exitCode + ' marker=' + $caseC.marker + ' echoDirCreated=' + (Test-Path -LiteralPath $echoDir) + ' subdirs=' + $echoSubdirsPresent.Count + '/' + $echoSubdirs.Count + ' legacyDirNotUsed=' + (-not $legacyInScratch))
Add-Check -Name 'echo-userdata-legacy-migration' -Ok $caseMOk -Detail ('exit=' + $caseM.exitCode + ' marker=' + $caseM.marker + ' legacyMarkerCopied=' + $migrationCopied + ' legacyDirPreserved=' + $legacyPreserved)
$report.unverifiedItems += 'Interactive QMessageBox error-dialog rendering is code-verified only (all six user-data candidates would have to be unwritable); the fallback and clean-error classification are verified by the two startup runs above.'
$report.unverifiedItems += 'This test confirms startup robustness on this host; it does not verify interactive GUI acceptance or replace the frontend acceptance owner.'
foreach ($item in $report.unverifiedItems) { Write-Warn2 ('- ' + $item) }
$failures = @($report.checks | Where-Object { $_.status -eq 'FAIL' })
if ($failures.Count -gt 0) { Complete-Report -Status 'FAIL' -ExitCode 1 }
Complete-Report -Status 'PASS' -ExitCode 0
