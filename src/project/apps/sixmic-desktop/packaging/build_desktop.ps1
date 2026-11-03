#Requires -Version 5.1
<#
.SYNOPSIS
    Build echo.exe (PyInstaller onedir, Qt Quick/QML) - product GUI bundle.

.DESCRIPTION
    Wraps apps/sixmic-desktop/packaging/sixmic_desktop.spec. The spec itself
    refuses to build without the main-agent UI (main.py + ui/ or rendering/ with
    real QML sources), so this script can never fabricate a fake GUI.

      1. preflight --mode desktop (fails with exact paths if main.py/QML missing)
      2. PyInstaller onedir build (windowed, no console)
      3. copy protocol data next to exe as protocol/
      4. bundle evidence: SHA256 inventory, forbidden payloads, Qt6 DLL
         provenance vs build venv wheel, platforms/qwindows.dll, QML modules
      5. offscreen smoke tests of the built windowed exe with scrubbed PATH,
         throw-away cwd and workspace user-data override:
           a) --self-test (windowed exe: exit code + opt-in gui-log capture)
           b) --smoke-gui N with QT_QPA_PLATFORM=offscreen + software Quick
              backend; requires exit 0 (window/QML loaded) and no QML error
              lines in the captured Qt log (runtime hook rth_gui_log.py)
      6. JSON summary + logs under packaging/build-logs/<timestamp>/

    No final echo GUI acceptance is claimed here: the UI is owned by the
    main agent, and visual/functional GUI acceptance requires the merged UI plus
    a clean Windows test environment.

.NOTES
    Exit codes: 0 = built (+self-test if requested), 2 = preflight failed,
                3 = PyInstaller failed, 4 = protocol copy failed,
                5 = bundle evidence failed, 6 = self-test failed.
#>
[CmdletBinding()]
param(
    [string]$LogRoot,
    [switch]$SkipSelfTest,
    [switch]$NoClean,
    [string]$TempRoot,
    [int]$SelfTestTimeoutSeconds = 120,
    [double]$GuiSmokeSeconds = 3,
    [string]$PythonExecutable,
    [string]$OutputRoot
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$ScriptDir = $PSScriptRoot
$AppDir = Split-Path -Parent $ScriptDir
$RepoRoot = Split-Path -Parent (Split-Path -Parent $AppDir)
$VenvPython = Join-Path $AppDir '.venv\Scripts\python.exe'
if($PythonExecutable){$VenvPython=[IO.Path]::GetFullPath($PythonExecutable)}
$InterfacesDir = Join-Path $RepoRoot 'interfaces\pc_backend_v1'
$DistRoot = Join-Path $AppDir 'dist'
if($OutputRoot){$DistRoot=[IO.Path]::GetFullPath($OutputRoot)}
$BundleDir = Join-Path $DistRoot 'echo'
$ExePath = Join-Path $BundleDir 'echo.exe'
$WorkRoot = Join-Path $AppDir 'build\desktop'
if($OutputRoot){$WorkRoot=Join-Path (Split-Path -Parent $DistRoot) 'pyinstaller-work'}
$Preflight = Join-Path $ScriptDir 'tools\preflight.py'
$CopyProtocol = Join-Path $ScriptDir 'tools\copy_protocol_data.py'
$BundleEvidence = Join-Path $ScriptDir 'tools\bundle_evidence.py'
$UiMarkerTool = Join-Path $ScriptDir 'tools\ui_marker.py'
$WriteProbe = Join-Path $ScriptDir 'tools\scratch_write_probe.py'
$SpecPath = Join-Path $ScriptDir 'sixmic_desktop.spec'
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
if (-not $LogRoot -or $LogRoot.Trim().Length -eq 0) { $LogRoot = Join-Path $ScriptDir 'build-logs' }
$LogDir = Join-Path $LogRoot $Stamp
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$BuildLog = Join-Path $LogDir 'build_desktop.log'
$script:BuildLogPath = $BuildLog

function Write-Log { param([string]$Message, [string]$Color = 'Gray') Write-Host $Message -ForegroundColor $Color; Add-Content -LiteralPath $script:BuildLogPath -Value $Message -Encoding utf8 }
function Write-Step { param([string]$M) Write-Log -Message ''; Write-Log -Message ('=== ' + $M + ' ===') -Color Cyan }
function Write-Pass { param([string]$M) Write-Log -Message ('PASS  ' + $M) -Color Green }
function Write-Warn2 { param([string]$M) Write-Log -Message ('WARN  ' + $M) -Color Yellow }
function Write-Fail { param([string]$M) Write-Log -Message ('FAIL  ' + $M) -Color Red }
function Write-Info2 { param([string]$M) Write-Log -Message ('      ' + $M) }
function Get-NewLine { return [string]([char]13) + [string]([char]10) }

function Invoke-Python {
    param([string[]]$Arguments, [string]$LogFile)
    $savedEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $out = & $VenvPython @Arguments 2>&1; $code = $LASTEXITCODE } finally { $ErrorActionPreference = $savedEap }
    $text = ($out | ForEach-Object { $_.ToString() }) -join (Get-NewLine)
    if ($LogFile) { Set-Content -LiteralPath $LogFile -Value $text -Encoding utf8 }
    return [pscustomobject]@{ ExitCode = $code; Text = $text }
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

function Read-TextFileSafe {
    param([string]$Path)
    if (-not $Path) { return '' }
    if (-not (Test-Path -LiteralPath $Path)) { return '' }
    try { return (Get-Content -LiteralPath $Path -Raw -Encoding utf8) } catch { return '' }
}

# QML/Qt error signatures. A windowed PyInstaller bundle logs QML problems
# through Qt messages (captured by the opt-in runtime hook) instead of stdout.
$script:QmlErrorPattern = '(QQmlApplicationEngine failed|Failed to load component|QML_LOAD_FAILED|ReferenceError|TypeError:|is not a type|is not defined|Cannot assign|Unable to assign|QML module not found|module "[^"]+" is not installed|Cannot load library|file:///[^\s]*\.qml:[0-9]+)'
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

function New-ScratchRoot {
    param([string]$Preferred, [string]$LogPath)
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($Preferred -and $Preferred.Trim().Length -gt 0) { $candidates.Add($Preferred) }
    if ($env:TEMP) { $candidates.Add((Join-Path $env:TEMP ('sixmic-desktop-build-' + $Stamp))) }
    $candidates.Add((Join-Path $LogPath 'scratch'))
    $savedEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        foreach ($candidate in $candidates) {
            try {
                New-Item -ItemType Directory -Force -Path $candidate | Out-Null
                $probeOut = & $VenvPython $WriteProbe $candidate 2>&1
                if ($LASTEXITCODE -eq 0) { return (Resolve-Path -LiteralPath $candidate).Path }
            } catch { continue }
        }
    } finally { $ErrorActionPreference = $savedEap }
    throw 'No writable scratch directory with venv-python write access was found.'
}

function Remove-SafePath {
    param([string]$Path, [string]$AllowedRoot)
    $full = [System.IO.Path]::GetFullPath($Path)
    $root = [System.IO.Path]::GetFullPath($AllowedRoot)
    if (-not $full.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) { throw ('refusing to delete outside ' + $root + ': ' + $full) }
    if (Test-Path -LiteralPath $full) { Remove-Item -LiteralPath $full -Recurse -Force }
}

$summary = [ordered]@{
    artifact = 'echo.exe'
    status = 'RUNNING'
    startedAtLocal = (Get-Date -Format 'o')
    finishedAtLocal = $null
    logDir = $LogDir
    logFile = $BuildLog
    environment = [ordered]@{ python = $null; pyside6 = $null; qt = $null; pyinstaller = $null }
    preflight = $null
    uiSnapshot = $null
    build = $null
    protocol = $null
    bundle = $null
    bundleDiet = $null
    selfTest = $null
    guiSmoke = $null
    unverifiedItems = @()
    errors = @()
}

function Complete-Summary {
    param([string]$Status, [int]$ExitCode)
    $summary.status = $Status
    $summary.finishedAtLocal = (Get-Date -Format 'o')
    $summaryPath = Join-Path $LogDir 'build_desktop.json'
    $summary | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $summaryPath -Encoding utf8
    Write-Log -Message ''
    Write-Log -Message ('SUMMARY: ' + $Status)
    Write-Log -Message ('  summary json : ' + $summaryPath)
    Write-Log -Message ('  build log    : ' + $BuildLog)
    Write-Log -Message ('  artifact     : ' + $ExePath)
    exit $ExitCode
}

try {
    Write-Log -Message ('echo desktop build - ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz'))
    Write-Log -Message ('log dir: ' + $LogDir)

    Write-Step '1/6 preflight (desktop mode: main.py + merged UI + Qt/QML + protocol)'
    $preflightArgs = @($Preflight, '--mode', 'desktop', '--json', '--report', (Join-Path $LogDir 'preflight.json'))
    $preflight = Invoke-Python -Arguments $preflightArgs -LogFile (Join-Path $LogDir 'preflight.log')
    $pj = $null
    try { $pj = $preflight.Text | ConvertFrom-Json } catch { $pj = $null }
    if ($pj) {
        $summary.preflight = [ordered]@{ ok = $pj.ok; checks = @($pj.checks) }
        $summary.environment.python = $pj.versions.python
        $summary.environment.pyside6 = $pj.versions.pyside6
        $summary.environment.qt = $pj.versions.qt
        $summary.environment.pyinstaller = $pj.versions.pyinstaller
        foreach ($item in $pj.checks) {
            if ($item.status -eq 'FAIL') { Write-Fail ($item.name + ': ' + $item.detail) }
            elseif ($item.status -eq 'WARN') { Write-Warn2 ($item.name + ': ' + $item.detail) }
        }
    }
    if ($preflight.ExitCode -ne 0) {
        Write-Fail 'desktop build preflight failed - the main-agent UI is not merged or Qt/protocol inputs are missing (exact items above).'
        $summary.errors += 'desktop preflight exit code ' + $preflight.ExitCode
        Complete-Summary -Status 'NOT_BUILT_UI_NOT_MERGED' -ExitCode 2
    }
    Write-Pass 'desktop preflight passed'

    Write-Step '1b/6 UI freeze snapshot (uiSha256 over ui/**, themes/**, assets/**, main.py)'
    $uiReportPath = Join-Path $LogDir 'ui_marker.json'
    $uiMarkerRun = Invoke-Python -Arguments @($UiMarkerTool, '--json', '--report', $uiReportPath) -LogFile (Join-Path $LogDir 'ui_marker.log')
    $uiMarker = $null
    try { $uiMarker = $uiMarkerRun.Text | ConvertFrom-Json } catch { $uiMarker = $null }
    if ($uiMarkerRun.ExitCode -ne 0 -or $null -eq $uiMarker) {
        Write-Fail ('UI freeze snapshot failed (exit=' + $uiMarkerRun.ExitCode + ') - cannot prove which UI tree was packaged')
        $summary.errors += 'ui marker exit code ' + $uiMarkerRun.ExitCode
        Complete-Summary -Status 'FAIL_UI_SNAPSHOT' -ExitCode 2
    }
    $summary.uiSnapshot = [ordered]@{
        uiSha256 = $uiMarker.uiSha256
        fileCount = $uiMarker.fileCount
        includePycache = $uiMarker.includePycache
        sourcesOnlySha256 = $uiMarker.sourcesOnly.uiSha256
        sourcesOnlyFileCount = $uiMarker.sourcesOnly.fileCount
        report = $uiReportPath
        beforeBuild = [ordered]@{ uiSha256 = $uiMarker.uiSha256; fileCount = $uiMarker.fileCount }
        afterBuild = $null
    }
    Write-Log ('UI_FREEZE uiSha256=' + $uiMarker.uiSha256 + ' files=' + $uiMarker.fileCount + ' sourcesOnly=' + $uiMarker.sourcesOnly.uiSha256)
    Write-Pass ('UI freeze snapshot recorded: uiSha256=' + $uiMarker.uiSha256 + ' (' + $uiMarker.fileCount + ' files)')

    $scratchRoot = New-ScratchRoot -Preferred $TempRoot -LogPath $LogDir
    $scratchTemp = Join-Path $scratchRoot 'temp'
    New-Item -ItemType Directory -Force -Path $scratchTemp | Out-Null
    $env:TEMP = $scratchTemp
    $env:TMP = $scratchTemp

    Write-Step '2/6 PyInstaller build (windowed Qt Quick/QML onedir)'
    if (-not $NoClean) {
        Remove-SafePath -Path $BundleDir -AllowedRoot $DistRoot
        Remove-SafePath -Path $WorkRoot -AllowedRoot (Join-Path $AppDir 'build')
    }
    New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null
    New-Item -ItemType Directory -Force -Path $WorkRoot | Out-Null
    $pyiArgs = @('-m', 'PyInstaller', '--noconfirm', '--distpath', $DistRoot, '--workpath', $WorkRoot, '--log-level', 'INFO')
    if (-not $NoClean) { $pyiArgs += '--clean' }
    $pyiArgs += $SpecPath
    Write-Info2 ('command: ' + $VenvPython + ' ' + ($pyiArgs -join ' '))
    $buildStart = Get-Date
    $build = Invoke-Python -Arguments $pyiArgs -LogFile (Join-Path $LogDir 'pyinstaller.log')
    $buildSeconds = [math]::Round(((Get-Date) - $buildStart).TotalSeconds, 1)
    $summary.build = [ordered]@{ exitCode = $build.ExitCode; durationSeconds = $buildSeconds; logFile = 'pyinstaller.log' }
    Write-Info2 ('PyInstaller exit=' + $build.ExitCode + ' duration=' + $buildSeconds + 's')
    if ($build.ExitCode -ne 0) {
        $tailLength = [math]::Min(4000, $build.Text.Length)
        Write-Log -Message ($build.Text.Substring($build.Text.Length - $tailLength))
        Write-Fail 'PyInstaller desktop build failed'
        $summary.errors += 'pyinstaller exit code ' + $build.ExitCode
        Complete-Summary -Status 'FAIL_BUILD' -ExitCode 3
    }
    if (-not (Test-Path -LiteralPath $ExePath)) {
        Write-Fail ('expected exe missing after build: ' + $ExePath)
        Complete-Summary -Status 'FAIL_BUILD' -ExitCode 3
    }
    Write-Pass ('built ' + $ExePath)

    # Record what the spec actually collected (real values from the build log).
    $buildText = $build.Text
    $buildInfo = [ordered]@{ qmlModulesCopied = $null; appModulesCollected = $null; exeIcon = $null; runtimeHooks = @() }
    $qmlMatch = [regex]::Match($buildText, 'QML modules copied=(\d+)')
    if ($qmlMatch.Success) { $buildInfo.qmlModulesCopied = [int]$qmlMatch.Groups[1].Value }
    $appModsMatch = [regex]::Match($buildText, 'application python modules collected=(\d+)')
    if ($appModsMatch.Success) { $buildInfo.appModulesCollected = [int]$appModsMatch.Groups[1].Value }
    $iconMatch = [regex]::Match($buildText, 'sixmic_desktop\.spec: exe icon=(.+)')
    if ($iconMatch.Success) { $buildInfo.exeIcon = $iconMatch.Groups[1].Value.Trim() }
    foreach ($hookMatch in [regex]::Matches($buildText, 'runtime hook=(.+)')) { $buildInfo.runtimeHooks += $hookMatch.Groups[1].Value.Trim() }
    $summary.build.qmlModulesCopied = $buildInfo.qmlModulesCopied
    $summary.build.appModulesCollected = $buildInfo.appModulesCollected
    $summary.build.exeIcon = $buildInfo.exeIcon
    $summary.build.runtimeHooks = @($buildInfo.runtimeHooks)
    Write-Info2 ('spec: qmlModulesCopied=' + [string]$buildInfo.qmlModulesCopied + ' appModulesCollected=' + [string]$buildInfo.appModulesCollected + ' exeIcon=' + [string]$buildInfo.exeIcon)

    # --- documented bundle diet (files proven unused by the runtime) --------
    Write-Step '2b/6 bundle diet (drop non-product Qt payloads, reasons recorded)'
    $dietItems = @(
        [pscustomobject]@{ RelativePath = 'PySide6\translations'; Reason = 'Qt translation catalogs unused: application i18n ships as ui/i18n/*.json; Qt fallback strings stay English' },
        [pscustomobject]@{ RelativePath = 'PySide6\plugins\qmltooling'; Reason = 'QML debugger/tooling plugins are not loaded by the runtime application' },
        [pscustomobject]@{ RelativePath = 'PySide6\opengl32sw.dll'; Reason = 'software-OpenGL fallback unused: Qt Quick RHI runs on D3D11 on Windows; documented limitation in packaging/README.md' }
    )
    $dietApplied = New-Object System.Collections.Generic.List[object]
    foreach ($item in $dietItems) {
        $full = Join-Path (Join-Path $BundleDir '_internal') $item.RelativePath
        if (-not (Test-Path -LiteralPath $full)) { Write-Info2 ('diet: already absent ' + $item.RelativePath); continue }
        $isContainer = (Get-Item -LiteralPath $full).PSIsContainer
        $files = @()
        $bytes = [long]0
        if ($isContainer) {
            $files = @(Get-ChildItem -LiteralPath $full -Recurse -File -ErrorAction SilentlyContinue)
            if ($files.Count -gt 0) { $bytes = [long](($files | Measure-Object -Property Length -Sum).Sum) }
        } else {
            $bytes = [long](Get-Item -LiteralPath $full).Length
        }
        Remove-Item -LiteralPath $full -Recurse -Force
        $dietApplied.Add([ordered]@{ path = $item.RelativePath; fileCount = $files.Count; bytes = $bytes; reason = $item.Reason })
        Write-Info2 ('diet: removed ' + $item.RelativePath + ' (' + $files.Count + ' files, ' + $bytes + ' bytes): ' + $item.Reason)
    }
    $summary.bundleDiet = $dietApplied.ToArray()
    Write-Pass ('bundle diet applied: ' + $dietApplied.Count + ' item(s), ' + [long](($dietApplied | ForEach-Object { $_.bytes } | Measure-Object -Sum).Sum) + ' bytes removed')

    Write-Step '3/6 copy protocol data next to exe'
    $protocolDest = Join-Path $BundleDir 'protocol'
    $copy = Invoke-Python -Arguments @($CopyProtocol, '--interfaces', $InterfacesDir, '--dest', $protocolDest, '--report', (Join-Path $LogDir 'protocol_manifest.json')) -LogFile (Join-Path $LogDir 'protocol_copy.log')
    Write-Log -Message $copy.Text
    if ($copy.ExitCode -ne 0) {
        Write-Fail ('protocol data copy failed (exit ' + $copy.ExitCode + ')')
        Complete-Summary -Status 'FAIL_PROTOCOL_DATA' -ExitCode 4
    }
    $pm = Get-Content -LiteralPath (Join-Path $LogDir 'protocol_manifest.json') -Raw -Encoding utf8 | ConvertFrom-Json
    $summary.protocol = [ordered]@{ fileCount = $pm.fileCount; totalBytes = $pm.totalBytes; manifestSha256 = $pm.manifestSha256; destination = $pm.destination }
    Write-Pass ('protocol data next to exe: ' + $pm.fileCount + ' files, manifestSha256=' + $pm.manifestSha256)

    Write-Step '4/6 bundle evidence (Qt6 provenance, platforms/qwindows.dll, QML modules, forbidden payloads)'
    $pysideProbe = Invoke-Python -Arguments @('-c', 'import PySide6, pathlib; print(pathlib.Path(PySide6.__file__).resolve().parent)') -LogFile $null
    $pyside6Dir = $null
    if ($pysideProbe.ExitCode -eq 0) { $pyside6Dir = $pysideProbe.Text.Trim() }
    $evidenceArgs = @($BundleEvidence, '--bundle', $BundleDir, '--exe-name', 'echo.exe', '--profile', 'desktop', '--report', (Join-Path $LogDir 'bundle_evidence.json'))
    if ($pyside6Dir) { $evidenceArgs += '--pyside6-dir'; $evidenceArgs += $pyside6Dir }
    $evidence = Invoke-Python -Arguments $evidenceArgs -LogFile (Join-Path $LogDir 'bundle_evidence.log')
    Write-Log -Message $evidence.Text
    if ($evidence.ExitCode -ne 0) {
        Write-Fail 'desktop bundle evidence check failed (Qt provenance/QML/platform plugin/protocol)'
        $summary.errors += 'bundle evidence exit code ' + $evidence.ExitCode
        Complete-Summary -Status 'FAIL_BUNDLE_EVIDENCE' -ExitCode 5
    }
    $be = Get-Content -LiteralPath (Join-Path $LogDir 'bundle_evidence.json') -Raw -Encoding utf8 | ConvertFrom-Json
    $summary.bundle = [ordered]@{
        exe = $be.exe; exeBytes = $be.exeBytes; exeSha256 = $be.exeSha256
        fileCount = $be.fileCount; totalBytes = $be.totalBytes; inventorySha256 = $be.inventorySha256
        qtDllCount = $be.qtDllCount; protocol = $be.protocol; warnings = @($be.warnings)
    }
    foreach ($warning in @($be.warnings)) { Write-Warn2 $warning; $summary.unverifiedItems += ('bundle warning: ' + $warning) }
    Write-Pass ('desktop bundle: files=' + $be.fileCount + ' bytes=' + $be.totalBytes + ' qtDlls=' + $be.qtDllCount + ' inventorySha256=' + $be.inventorySha256)
    Write-Info2 ('exe sha256=' + $be.exeSha256)
    Set-Content -LiteralPath (Join-Path $LogDir 'HASHES.sha256') -Value ($be.exeSha256 + '  ' + $ExePath) -Encoding utf8

    if ($SkipSelfTest) {
        Write-Step '5/6 smoke tests SKIPPED (-SkipSelfTest)'
        $summary.selfTest = [ordered]@{ mode = 'skipped'; verified = $false }
        $summary.guiSmoke = [ordered]@{ mode = 'skipped'; verified = $false }
        $summary.unverifiedItems += 'smoke tests skipped (-SkipSelfTest): echo.exe built but never launched'
        Complete-Summary -Status 'BUILT_UNVERIFIED' -ExitCode 0
    }

    Write-Step '5/6 offscreen smoke tests (scrubbed PATH, throw-away cwd, workspace user-data)'
    $selfTestCwd = Join-Path $scratchRoot 'selftest-cwd'
    $selfTestTemp = Join-Path $scratchRoot 'selftest-temp'
    $guiCwd = Join-Path $scratchRoot 'gui-smoke-cwd'
    $guiTemp = Join-Path $scratchRoot 'gui-smoke-temp'
    $selfTestUserData = Join-Path $scratchRoot 'selftest-userdata'
    $guiUserData = Join-Path $scratchRoot 'gui-smoke-userdata'
    foreach ($dir in @($selfTestCwd, $selfTestTemp, $guiCwd, $guiTemp)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $selfTestCapture = Join-Path $LogDir 'desktop-selftest.capture.log'
    $selfTestStdout = Join-Path $LogDir 'desktop-selftest.stdout.log'
    $selfTestStderr = Join-Path $LogDir 'desktop-selftest.stderr.log'
    $guiCapture = Join-Path $LogDir 'gui-smoke.capture.log'
    $guiStdout = Join-Path $LogDir 'gui-smoke.stdout.log'
    $guiStderr = Join-Path $LogDir 'gui-smoke.stderr.log'
    $minPath = (@((Join-Path $env:SystemRoot 'System32'), $env:SystemRoot, (Join-Path $env:SystemRoot 'System32\Wbem'), (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0')) | Where-Object { Test-Path -LiteralPath $_ }) -join ';'
    $savedEnv = @{
        PATH = $env:PATH; PYTHONPATH = $env:PYTHONPATH; PYTHONHOME = $env:PYTHONHOME; VIRTUAL_ENV = $env:VIRTUAL_ENV
        QT_PLUGIN_PATH = $env:QT_PLUGIN_PATH; QML2_IMPORT_PATH = $env:QML2_IMPORT_PATH; QML_IMPORT_PATH = $env:QML_IMPORT_PATH
        TEMP = $env:TEMP; TMP = $env:TMP; SIXMIC_USER_DATA_DIR = $env:SIXMIC_USER_DATA_DIR
        QT_QPA_PLATFORM = $env:QT_QPA_PLATFORM; QT_QUICK_BACKEND = $env:QT_QUICK_BACKEND
        QT_ASSUME_STDERR_HAS_CONSOLE = $env:QT_ASSUME_STDERR_HAS_CONSOLE; SIXMIC_PACKAGING_GUI_LOG = $env:SIXMIC_PACKAGING_GUI_LOG
    }
    $selfTest = [ordered]@{ exitCode = $null; timedOut = $false; capture = $selfTestCapture; stdout = $selfTestStdout; stderr = $selfTestStderr }
    $guiRun = $null
    try {
        $env:PATH = $minPath
        foreach ($name in @('PYTHONPATH','PYTHONHOME','VIRTUAL_ENV','QT_PLUGIN_PATH','QML2_IMPORT_PATH','QML_IMPORT_PATH')) { Remove-Item -Path ('Env:' + $name) -ErrorAction SilentlyContinue }

        # --- 5a: headless backend self-test from the windowed product bundle ---
        $env:TEMP = $selfTestTemp
        $env:TMP = $selfTestTemp
        $env:SIXMIC_USER_DATA_DIR = $selfTestUserData
        $env:SIXMIC_PACKAGING_GUI_LOG = $selfTestCapture
        Write-Info2 ('run: ' + $ExePath + ' --self-test (cwd=' + $selfTestCwd + ')')
        $st = Invoke-CapturedProcess -FilePath $ExePath -Arguments '--self-test' -WorkingDirectory $selfTestCwd -StdoutPath $selfTestStdout -StderrPath $selfTestStderr -TimeoutMs ($SelfTestTimeoutSeconds * 1000)
        $selfTest.exitCode = $st.ExitCode
        $selfTest.timedOut = $st.TimedOut

        # --- 5b: real GUI startup, offscreen, no console ---
        $env:TEMP = $guiTemp
        $env:TMP = $guiTemp
        $env:SIXMIC_USER_DATA_DIR = $guiUserData
        $env:SIXMIC_PACKAGING_GUI_LOG = $guiCapture
        $env:QT_QPA_PLATFORM = 'offscreen'
        $env:QT_QUICK_BACKEND = 'software'
        $env:QT_ASSUME_STDERR_HAS_CONSOLE = '1'
        Write-Info2 ('run: ' + $ExePath + ' --smoke-gui ' + $GuiSmokeSeconds + ' (QT_QPA_PLATFORM=offscreen, cwd=' + $guiCwd + ')')
        $guiSecondsInvariant = $GuiSmokeSeconds.ToString([System.Globalization.CultureInfo]::InvariantCulture)
        $guiRun = Invoke-CapturedProcess -FilePath $ExePath -Arguments ('--smoke-gui ' + $guiSecondsInvariant) -WorkingDirectory $guiCwd -StdoutPath $guiStdout -StderrPath $guiStderr -TimeoutMs ($SelfTestTimeoutSeconds * 1000)
    } finally {
        foreach ($key in $savedEnv.Keys) {
            if ($null -eq $savedEnv[$key]) { Remove-Item -Path ('Env:' + $key) -ErrorAction SilentlyContinue }
            else { Set-Item -Path ('Env:' + $key) -Value $savedEnv[$key] }
        }
    }

    $selfTestCaptured = Read-TextFileSafe -Path $selfTestCapture
    $selfTestTail = ''
    if ($selfTestCaptured) { $selfTestTail = (($selfTestCaptured -split '[\r\n]+') | Where-Object { $_.Trim().Length -gt 0 } | Select-Object -Last 1) }
    $summary.selfTest = [ordered]@{
        exitCode = $selfTest.exitCode; timedOut = $selfTest.timedOut; lastCapturedLine = $selfTestTail
        capture = $selfTestCapture; stdout = $selfTestStdout; stderr = $selfTestStderr
    }
    if ($selfTest.exitCode -ne 0) {
        Write-Fail ('desktop exe --self-test failed (exit=' + $selfTest.exitCode + ' timedOut=' + $selfTest.timedOut + '); see ' + $selfTestCapture)
        Complete-Summary -Status 'FAIL_SELF_TEST' -ExitCode 6
    }
    Write-Pass 'desktop exe --self-test exit=0'
    if ($selfTestCaptured -match 'SELF-TEST PASS') { Write-Pass 'captured self-test output contains SELF-TEST PASS' }
    elseif ($selfTestCaptured) { Write-Warn2 'captured self-test output has no SELF-TEST PASS line (windowed exe output capture incomplete); exit code is the authority' }
    else { Write-Warn2 'self-test output was not captured by the windowed exe (exit code is the authority)' }

    $guiCaptured = Read-TextFileSafe -Path $guiCapture
    $guiOut = Read-TextFileSafe -Path $guiStdout
    $guiErr = Read-TextFileSafe -Path $guiStderr
    $qmlErrors = @(Find-QmlErrors -Texts @($guiCaptured, $guiOut, $guiErr))
    $guiMarker = $null
    if ($guiCaptured -match 'SMOKE_GUI_OK') { $guiMarker = 'SMOKE_GUI_OK' }
    elseif ($guiCaptured -match 'SMOKE_GUI_WARNINGS') { $guiMarker = 'SMOKE_GUI_WARNINGS' }
    elseif ($guiOut -match 'SMOKE_GUI_OK') { $guiMarker = 'SMOKE_GUI_OK' }
    elseif ($guiOut -match 'SMOKE_GUI_WARNINGS') { $guiMarker = 'SMOKE_GUI_WARNINGS' }
    $guiUserDataCreated = Test-Path -LiteralPath $guiUserData
    $guiUserDataHasUi = Test-Path -LiteralPath (Join-Path $guiUserData 'ui')
    $summary.guiSmoke = [ordered]@{
        exitCode = $guiRun.ExitCode; timedOut = $guiRun.TimedOut; seconds = $GuiSmokeSeconds
        qmlErrors = @($qmlErrors); marker = $guiMarker
        userDataDir = $guiUserData; userDataDirCreated = $guiUserDataCreated; userDataHasUiDir = $guiUserDataHasUi
        capture = $guiCapture; stdout = $guiStdout; stderr = $guiStderr
    }
    if ($guiRun.TimedOut) {
        Write-Fail ('GUI offscreen smoke timed out after ' + $SelfTestTimeoutSeconds + 's')
        Complete-Summary -Status 'FAIL_GUI_SMOKE' -ExitCode 6
    }
    if ($guiRun.ExitCode -ne 0) {
        Write-Fail ('GUI offscreen smoke failed (exit=' + $guiRun.ExitCode + ') - QML/window did not load cleanly; see ' + $guiCapture)
        foreach ($line in $qmlErrors) { Write-Fail ('  qml: ' + $line) }
        Complete-Summary -Status 'FAIL_GUI_SMOKE' -ExitCode 6
    }
    if ($qmlErrors.Count -gt 0) {
        Write-Fail ('GUI loaded but logged ' + $qmlErrors.Count + ' QML/Qt error line(s):')
        foreach ($line in $qmlErrors) { Write-Fail ('  qml: ' + $line) }
        Complete-Summary -Status 'FAIL_QML_ERRORS' -ExitCode 6
    }
    Write-Pass ('GUI offscreen smoke exit=0, no QML errors (marker=' + [string]$guiMarker + ', userDataDirCreated=' + $guiUserDataCreated + ')')
    if (-not $guiCaptured) { $summary.unverifiedItems += 'Windowed GUI smoke output was not captured by the opt-in runtime hook; exit code 0 is the evidence that the window/QML root loaded.' }
    if (-not $guiUserDataCreated) { $summary.unverifiedItems += 'GUI smoke did not create the SIXMIC_USER_DATA_DIR override directory; check on a normal session.' }

    Write-Step '6/6 evidence + limitations'
    $uiAfterPath = Join-Path $LogDir 'ui_marker_after.json'
    $uiAfterRun = Invoke-Python -Arguments @($UiMarkerTool, '--json', '--report', $uiAfterPath) -LogFile (Join-Path $LogDir 'ui_marker_after.log')
    $uiAfter = $null
    try { $uiAfter = $uiAfterRun.Text | ConvertFrom-Json } catch { $uiAfter = $null }
    if ($uiAfter) {
        $summary.uiSnapshot.afterBuild = [ordered]@{ uiSha256 = $uiAfter.uiSha256; fileCount = $uiAfter.fileCount }
        if ($uiAfter.uiSha256 -ne $summary.uiSnapshot.uiSha256) {
            Write-Warn2 ('UI tree changed during the build: before=' + $summary.uiSnapshot.uiSha256 + ' after=' + $uiAfter.uiSha256 + ' (pycache drift or a source edit during build; see ui_marker_after.json)')
            $summary.unverifiedItems += 'UI tree changed during this build (uiSha256 before=' + $summary.uiSnapshot.uiSha256 + ' after=' + $uiAfter.uiSha256 + '): the packaged bundle corresponds to the pre-build snapshot recorded in ui_marker.json; re-run the build on a stable tree.'
        } else {
            Write-Pass ('UI freeze confirmed unchanged after build: uiSha256=' + $uiAfter.uiSha256)
        }
    }
    $summary.unverifiedItems += 'echo GUI visual/functional acceptance NOT performed: the offscreen smoke proves the packaged window/QML loads without QML errors, but visual/functional review and a clean Windows VM test remain pending.'
    $summary.unverifiedItems += 'Real desktop compositor / GPU path not exercised: QT_QPA_PLATFORM=offscreen + QT_QUICK_BACKEND=software are used for deterministic CI smoke.'
    foreach ($item in $summary.unverifiedItems) { Write-Warn2 ('- ' + $item) }
    Complete-Summary -Status 'BUILT_OFFSCREEN_SMOKE_PASS' -ExitCode 0
}
catch {
    Write-Fail ('unhandled error: ' + $_.Exception.Message)
    Write-Log -Message $_.ScriptStackTrace
    $summary.errors += $_.Exception.Message
    Complete-Summary -Status 'FAIL_UNHANDLED' -ExitCode 1
}
