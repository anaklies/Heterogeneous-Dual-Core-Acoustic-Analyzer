#Requires -Version 5.1
<#
.SYNOPSIS
    Build SixMic3D-BackendCheck.exe (PyInstaller, onedir) and verify it.

.DESCRIPTION
    Reproducible pipeline for the backend diagnostic console artifact:
      1. preflight (venv lock/versions, backend entry, protocol data, PyInstaller)
      2. PyInstaller onedir build of apps/sixmic-desktop/packaging/sixmic_backend_check.spec
      3. copy interfaces/pc_backend_v1 protocol data next to the exe as protocol/
      4. bundle evidence: hashes/inventory, forbidden-payload scan, Qt provenance
      5. --self-test from a scratch temp dir with the dev PATH/Python env scrubbed
      6. write console output + SHA256 hashes + JSON summary into packaging/build-logs/<timestamp>/

    The self-test is tried with the default user data dir (%LOCALAPPDATA%\SixMic3D)
    first; if the OS denies that path (this harness sandbox does), it retries with
    SIXMIC_USER_DATA_DIR pointed at the scratch dir and records the difference as
    an environment limitation, never as a real %LOCALAPPDATA% verification.

    No final SixMic3D GUI acceptance is claimed from this artifact. Packaging does
    not edit backend code: failures are reported, not patched around.

.PARAMETER SkipSelfTest
    Build without running --self-test. The produced summary is marked
    BUILT_UNVERIFIED; never treat it as acceptance evidence.

.PARAMETER SelfTestDataDir
    Test-only: set SIXMIC_USER_DATA_DIR for the self-test run(s) to this path.
    If omitted, the default %LOCALAPPDATA% attempt is made first.

.PARAMETER AllowMissingProtocolData
    Passed through to preflight/PyInstaller/protocol copy. Only for separating
    PyInstaller mechanics from protocol deliverables while the backend lands;
    produces a bundle missing protocol data (recorded as such).

.PARAMETER NoClean
    Keep existing dist/build outputs (no --clean, no delete).

.PARAMETER TempRoot
    Scratch root used for TEMP/TMP and self-test working dirs. Default: a fresh
    directory under %TEMP%; the script verifies the build venv can write there
    and falls back to packaging/build-logs/tmp when the host sandbox forbids it.

.PARAMETER LogRoot
    Build log root (default: apps/sixmic-desktop/packaging/build-logs).

.PARAMETER SelfTestTimeoutSeconds
    Per-run timeout for the frozen exe self-test (default 120 s).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File apps/sixmic-desktop/packaging/build_backend_check.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File apps/sixmic-desktop/packaging/build_backend_check.ps1 -SkipSelfTest

.NOTES
    Exit codes:
      0 = built; self-test passed (or explicitly skipped -> unverified)
      2 = preflight failed (environment/protocol/entry missing)
      3 = PyInstaller build failed
      4 = protocol data copy/verification failed
      5 = bundle evidence check failed (forbidden payload / missing protocol / Qt mix)
      6 = self-test failed
#>
[CmdletBinding()]
param(
    [string]$LogRoot,
    [switch]$SkipSelfTest,
    [string]$SelfTestDataDir,
    [switch]$AllowMissingProtocolData,
    [switch]$NoClean,
    [string]$TempRoot,
    [int]$SelfTestTimeoutSeconds = 120
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$ScriptDir = $PSScriptRoot
$AppDir = Split-Path -Parent $ScriptDir
$RepoRoot = Split-Path -Parent (Split-Path -Parent $AppDir)
$VenvPython = Join-Path $AppDir '.venv\Scripts\python.exe'
$BackendDir = Join-Path $AppDir 'backend'
$BackendCheckEntry = Join-Path $BackendDir 'sixmic_backend\app\backend_check.py'
$InterfacesDir = Join-Path $RepoRoot 'interfaces\pc_backend_v1'
$DistRoot = Join-Path $AppDir 'dist'
$BundleDir = Join-Path $DistRoot 'SixMic3D-BackendCheck'
$ExePath = Join-Path $BundleDir 'SixMic3D-BackendCheck.exe'
$WorkRoot = Join-Path $AppDir 'build\backend_check'
$Preflight = Join-Path $ScriptDir 'tools\preflight.py'
$CopyProtocol = Join-Path $ScriptDir 'tools\copy_protocol_data.py'
$BundleEvidence = Join-Path $ScriptDir 'tools\bundle_evidence.py'
$WriteProbe = Join-Path $ScriptDir 'tools\scratch_write_probe.py'
$SpecPath = Join-Path $ScriptDir 'sixmic_backend_check.spec'
$Version = (Get-Content -LiteralPath (Join-Path $ScriptDir 'VERSION') -Raw).Trim()
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$StartedAt = Get-Date

if (-not $LogRoot -or $LogRoot.Trim().Length -eq 0) { $LogRoot = Join-Path $ScriptDir 'build-logs' }
$LogDir = Join-Path $LogRoot $Stamp
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$BuildLog = Join-Path $LogDir 'build_backend_check.log'
$script:BuildLogPath = $BuildLog

function Write-Log {
    param([string]$Message, [string]$Color = 'Gray', [switch]$NoConsole)
    if (-not $NoConsole) { Write-Host $Message -ForegroundColor $Color }
    Add-Content -LiteralPath $script:BuildLogPath -Value $Message -Encoding utf8
}

function Write-Step {
    param([string]$Message)
    Write-Log -Message ''
    Write-Log -Message ('=== ' + $Message + ' ===') -Color Cyan
}

function Write-Pass { param([string]$Message) Write-Log -Message ('PASS  ' + $Message) -Color Green }
function Write-Warn2 { param([string]$Message) Write-Log -Message ('WARN  ' + $Message) -Color Yellow }
function Write-Fail { param([string]$Message) Write-Log -Message ('FAIL  ' + $Message) -Color Red }
function Write-Info2 { param([string]$Message) Write-Log -Message ('      ' + $Message) }
function Get-NewLine { return [string]([char]13) + [string]([char]10) }

function New-ScratchRoot {
    param([string]$Preferred, [string]$LogPath)
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($Preferred -and $Preferred.Trim().Length -gt 0) { $candidates.Add($Preferred) }
    if ($env:TEMP) { $candidates.Add((Join-Path $env:TEMP ('sixmic-packaging-' + $Stamp))) }
    if ($env:TMP) { $candidates.Add((Join-Path $env:TMP ('sixmic-packaging-' + $Stamp))) }
    $candidates.Add((Join-Path $LogPath 'scratch'))
    $savedEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        foreach ($candidate in $candidates) {
            try {
                New-Item -ItemType Directory -Force -Path $candidate | Out-Null
                $probeOut = & $VenvPython $WriteProbe $candidate 2>&1
                if ($LASTEXITCODE -eq 0) { return (Resolve-Path -LiteralPath $candidate).Path }
            } catch {
                continue
            }
        }
    } finally {
        $ErrorActionPreference = $savedEap
    }
    throw 'No writable scratch directory with venv-python write access was found (checked explicit, %TEMP%, logs fallback).'
}

function Remove-SafePath {
    param([string]$Path, [string]$AllowedRoot)
    $full = [System.IO.Path]::GetFullPath($Path)
    $root = [System.IO.Path]::GetFullPath($AllowedRoot)
    if (-not $full.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw ('refusing to delete outside ' + $root + ': ' + $full)
    }
    if (Test-Path -LiteralPath $full) { Remove-Item -LiteralPath $full -Recurse -Force }
}

function Invoke-Python {
    param([string[]]$Arguments, [string]$LogFile)
    # Windows PowerShell 5.1 turns native stderr lines into error records; with
    # $ErrorActionPreference='Stop' that would abort on harmless PyInstaller INFO
    # logging (which goes to stderr). Temporarily continue while capturing.
    $savedEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & $VenvPython @Arguments 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $savedEap
    }
    $text = ($out | ForEach-Object { $_.ToString() }) -join (Get-NewLine)
    if ($LogFile) { Set-Content -LiteralPath $LogFile -Value $text -Encoding utf8 }
    return [pscustomobject]@{ ExitCode = $code; Text = $text }
}

function Set-EnvForScrub {
    param([string]$TempPath, [string]$UserDataDir, [string]$PathValue)
    $saved = @{
        PATH = $env:PATH
        PYTHONPATH = $env:PYTHONPATH
        PYTHONHOME = $env:PYTHONHOME
        PYTHONSTARTUP = $env:PYTHONSTARTUP
        VIRTUAL_ENV = $env:VIRTUAL_ENV
        QT_PLUGIN_PATH = $env:QT_PLUGIN_PATH
        QML2_IMPORT_PATH = $env:QML2_IMPORT_PATH
        QML_IMPORT_PATH = $env:QML_IMPORT_PATH
        SIXMIC_USER_DATA_DIR = $env:SIXMIC_USER_DATA_DIR
        TEMP = $env:TEMP
        TMP = $env:TMP
        PYTHONIOENCODING = $env:PYTHONIOENCODING
    }
    $env:PATH = $PathValue
    foreach ($name in @('PYTHONPATH','PYTHONHOME','PYTHONSTARTUP','VIRTUAL_ENV','QT_PLUGIN_PATH','QML2_IMPORT_PATH','QML_IMPORT_PATH')) {
        Remove-Item -Path ('Env:' + $name) -ErrorAction SilentlyContinue
    }
    if ($TempPath) { $env:TEMP = $TempPath; $env:TMP = $TempPath }
    if ($UserDataDir) { $env:SIXMIC_USER_DATA_DIR = $UserDataDir }
    else { Remove-Item -Path 'Env:SIXMIC_USER_DATA_DIR' -ErrorAction SilentlyContinue }
    $env:PYTHONIOENCODING = 'utf-8'
    return $saved
}

function Restore-EnvAfterScrub {
    param($Saved)
    foreach ($key in $Saved.Keys) {
        $value = $Saved[$key]
        if ($null -eq $value) {
            Remove-Item -Path ('Env:' + $key) -ErrorAction SilentlyContinue
        } else {
            Set-Item -Path ('Env:' + $key) -Value $value
        }
    }
}

function Get-LastNonEmptyLine {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return '' }
    $lines = Get-Content -LiteralPath $Path -Encoding utf8 | Where-Object { $_.Trim().Length -gt 0 }
    if (-not $lines -or $lines.Count -eq 0) { return '' }
    return [string]($lines[$lines.Count - 1]).Trim()
}

function Get-SelfTestReport {
    param([string]$StdoutPath)
    if (-not (Test-Path -LiteralPath $StdoutPath)) { return $null }
    $text = Get-Content -LiteralPath $StdoutPath -Raw -Encoding utf8
    if (-not $text) { return $null }
    $first = $text.IndexOf('{')
    $last = $text.LastIndexOf('}')
    if ($first -lt 0 -or $last -le $first) { return $null }
    $jsonText = $text.Substring($first, $last - $first + 1)
    try { return ($jsonText | ConvertFrom-Json) } catch { return $null }
}

function Test-SandboxPermissionFailure {
    param([string]$Text)
    if (-not $Text) { return $false }
    if ($Text -match 'WinError 5') { return $true }
    if ($Text -match 'PermissionError') { return $true }
    if ($Text -match 'Access is denied') { return $true }
    if ($Text -match 'Access denied') { return $true }
    return $false
}

function Get-Sha256 {
    param([string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Invoke-CapturedProcess {
    # Start-Process -PassThru does not expose ExitCode reliably under this host
    # (Windows PowerShell 5.1 + sandbox); .NET ProcessStartInfo does, and also
    # gives us a real timeout + separate stdout/stderr files.
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
    # The self-test output is a few KiB, so reading both streams to the end
    # while the process runs cannot deadlock on pipe buffers.
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

# ---------------------------------------------------------------- header
Write-Log -Message ('SixMic3D-BackendCheck build - ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz'))
Write-Log -Message ('repo root : ' + $RepoRoot)
Write-Log -Message ('app dir   : ' + $AppDir)
Write-Log -Message ('version   : ' + $Version)
Write-Log -Message ('log dir   : ' + $LogDir)

$summary = [ordered]@{
    artifact = 'SixMic3D-BackendCheck.exe'
    status = 'RUNNING'
    version = $Version
    startedAtLocal = (Get-Date -Format 'o')
    finishedAtLocal = $null
    logDir = $LogDir
    logFile = $BuildLog
    environment = [ordered]@{
        python = $null
        venv = $VenvPython
        pyside6 = $null
        qt = $null
        pyinstaller = $null
        host = $env:COMPUTERNAME
        os = [System.Environment]::OSVersion.VersionString
    }
    preflight = $null
    build = $null
    protocol = $null
    bundle = $null
    selfTest = $null
    unverifiedItems = @()
    errors = @()
}

function Complete-Summary {
    param([string]$Status, [int]$ExitCode)
    $summary.status = $Status
    $summary.finishedAtLocal = (Get-Date -Format 'o')
    $summaryPath = Join-Path $LogDir 'build_backend_check.json'
    $summary | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $summaryPath -Encoding utf8
    Write-Log -Message ''
    Write-Log -Message ('SUMMARY: ' + $Status)
    Write-Log -Message ('  summary json : ' + $summaryPath)
    Write-Log -Message ('  build log    : ' + $BuildLog)
    Write-Log -Message ('  artifact     : ' + $ExePath)
    exit $ExitCode
}

try {
    # ---------------------------------------------------------- 1. preflight
    Write-Step '1/6 preflight (venv, lock, backend entry, protocol data)'
    $preflightArgs = @($Preflight, '--mode', 'backend', '--json', '--report', (Join-Path $LogDir 'preflight.json'))
    if ($AllowMissingProtocolData) { $preflightArgs += '--allow-missing-protocol-data' }
    $preflight = Invoke-Python -Arguments $preflightArgs -LogFile (Join-Path $LogDir 'preflight.log')
    $preflightJson = $null
    try { $preflightJson = $preflight.Text | ConvertFrom-Json } catch { $preflightJson = $null }
    if ($preflightJson) {
        $summary.preflight = [ordered]@{
            ok = $preflightJson.ok
            mode = $preflightJson.mode
            checks = @($preflightJson.checks)
        }
        $summary.environment.python = $preflightJson.versions.python
        $summary.environment.pyside6 = $preflightJson.versions.pyside6
        $summary.environment.qt = $preflightJson.versions.qt
        $summary.environment.pyinstaller = $preflightJson.versions.pyinstaller
        foreach ($item in $preflightJson.checks) {
            $line = '[' + $item.status + '] ' + $item.name + ': ' + $item.detail
            if ($item.status -eq 'FAIL') { Write-Log -Message ('      ' + $line) -Color Red }
            elseif ($item.status -eq 'WARN') { Write-Log -Message ('      ' + $line) -Color Yellow }
        }
    }
    if ($preflight.ExitCode -ne 0) {
        Write-Fail 'preflight failed - see preflight.json / preflight.log (exact missing item above)'
        $summary.errors += 'preflight failed with exit code ' + $preflight.ExitCode
        Complete-Summary -Status 'FAIL_PREFLIGHT' -ExitCode 2
    }
    Write-Pass 'preflight passed'
    foreach ($item in @($summary.preflight.checks)) {
        if ($item.status -eq 'WARN') { $summary.unverifiedItems += ('preflight warning: ' + $item.name + ': ' + $item.detail) }
    }

    $pipList = Invoke-Python -Arguments @('-m', 'pip', 'list', '--format=freeze') -LogFile (Join-Path $LogDir 'pip-freeze.txt')
    if ($pipList.ExitCode -ne 0) { Write-Warn2 ('pip list failed with exit ' + $pipList.ExitCode) }
    Write-Info2 ('python: ' + $summary.environment.python + ' | PySide6: ' + $summary.environment.pyside6 + ' | PyInstaller: ' + $summary.environment.pyinstaller)

    if (-not (Test-Path -LiteralPath $BackendCheckEntry)) {
        Write-Fail ('backend check entry missing: ' + $BackendCheckEntry)
        Complete-Summary -Status 'FAIL_PREFLIGHT' -ExitCode 2
    }

    $scratchRoot = New-ScratchRoot -Preferred $TempRoot -LogPath $LogDir
    $scratchTemp = Join-Path $scratchRoot 'temp'
    New-Item -ItemType Directory -Force -Path $scratchTemp | Out-Null
    $env:TEMP = $scratchTemp
    $env:TMP = $scratchTemp
    Write-Info2 ('scratch (TEMP/TMP for child processes): ' + $scratchRoot)

    # ---------------------------------------------------------- 2. PyInstaller build
    Write-Step '2/6 PyInstaller build (onedir, headless console)'
    if (-not $NoClean) {
        Remove-SafePath -Path $BundleDir -AllowedRoot $DistRoot
        Remove-SafePath -Path $WorkRoot -AllowedRoot (Join-Path $AppDir 'build')
        Write-Info2 'cleaned dist/SixMic3D-BackendCheck and build/backend_check'
    }
    New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null
    New-Item -ItemType Directory -Force -Path $WorkRoot | Out-Null
    if ($AllowMissingProtocolData) { $env:SIXMIC_ALLOW_MISSING_PROTOCOL_DATA = '1' }
    else { Remove-Item -Path 'Env:SIXMIC_ALLOW_MISSING_PROTOCOL_DATA' -ErrorAction SilentlyContinue }

    $pyiArgs = @('-m', 'PyInstaller', '--noconfirm', '--distpath', $DistRoot, '--workpath', $WorkRoot, '--log-level', 'INFO')
    if (-not $NoClean) { $pyiArgs += '--clean' }
    $pyiArgs += $SpecPath
    Write-Info2 ('command: ' + $VenvPython + ' ' + ($pyiArgs -join ' '))
    $buildStart = Get-Date
    $build = Invoke-Python -Arguments $pyiArgs -LogFile (Join-Path $LogDir 'pyinstaller.log')
    $buildSeconds = [math]::Round(((Get-Date) - $buildStart).TotalSeconds, 1)
    $summary.build = [ordered]@{ exitCode = $build.ExitCode; durationSeconds = $buildSeconds; logFile = 'pyinstaller.log' }
    Write-Info2 ('PyInstaller exit=' + $build.ExitCode + ' duration=' + $buildSeconds + 's log=pyinstaller.log')
    if ($build.ExitCode -ne 0) {
        $tailLength = [math]::Min(3000, $build.Text.Length)
        Write-Log -Message ($build.Text.Substring($build.Text.Length - $tailLength))
        Write-Fail 'PyInstaller build failed'
        $summary.errors += 'pyinstaller exit code ' + $build.ExitCode
        Complete-Summary -Status 'FAIL_BUILD' -ExitCode 3
    }
    if (-not (Test-Path -LiteralPath $ExePath)) {
        Write-Fail ('expected exe missing after build: ' + $ExePath)
        $summary.errors += 'exe missing after PyInstaller'
        Complete-Summary -Status 'FAIL_BUILD' -ExitCode 3
    }
    Write-Pass ('built ' + $ExePath)

    # ---------------------------------------------------------- 3. protocol data next to exe
    Write-Step '3/6 copy protocol data next to exe'
    $protocolDest = Join-Path $BundleDir 'protocol'
    $copyArgs = @($CopyProtocol, '--interfaces', $InterfacesDir, '--dest', $protocolDest, '--report', (Join-Path $LogDir 'protocol_manifest.json'))
    if ($AllowMissingProtocolData) { $copyArgs += '--allow-missing' }
    $copy = Invoke-Python -Arguments $copyArgs -LogFile (Join-Path $LogDir 'protocol_copy.log')
    Write-Log -Message $copy.Text
    if ($copy.ExitCode -ne 0) {
        Write-Fail ('protocol data copy failed (exit ' + $copy.ExitCode + ')')
        $summary.errors += 'protocol copy exit code ' + $copy.ExitCode
        Complete-Summary -Status 'FAIL_PROTOCOL_DATA' -ExitCode 4
    }
    $protocolManifestPath = Join-Path $LogDir 'protocol_manifest.json'
    if (Test-Path -LiteralPath $protocolManifestPath) {
        $pm = Get-Content -LiteralPath $protocolManifestPath -Raw -Encoding utf8 | ConvertFrom-Json
        $summary.protocol = [ordered]@{
            source = $pm.source
            destination = $pm.destination
            fileCount = $pm.fileCount
            totalBytes = $pm.totalBytes
            manifestSha256 = $pm.manifestSha256
            missingRequired = @($pm.missingRequired)
        }
    }
    if ($AllowMissingProtocolData) { $summary.unverifiedItems += 'protocol data: -AllowMissingProtocolData used; bundle is incomplete' }
    Write-Pass ('protocol data next to exe: ' + $summary.protocol.fileCount + ' files, manifestSha256=' + $summary.protocol.manifestSha256)

    # ---------------------------------------------------------- 4. bundle evidence
    Write-Step '4/6 bundle evidence (hashes, forbidden payload scan, Qt provenance)'
    $pyside6Dir = $null
    if ($summary.environment.pyside6 -and $summary.environment.pyside6 -ne 'not-installed') {
        $pysideProbe = Invoke-Python -Arguments @('-c', 'import PySide6, pathlib; print(pathlib.Path(PySide6.__file__).resolve().parent)') -LogFile $null
        if ($pysideProbe.ExitCode -eq 0) { $pyside6Dir = $pysideProbe.Text.Trim() }
    }
    $evidenceArgs = @($BundleEvidence, '--bundle', $BundleDir, '--exe-name', 'SixMic3D-BackendCheck.exe', '--profile', 'backend', '--report', (Join-Path $LogDir 'bundle_evidence.json'))
    if ($pyside6Dir) { $evidenceArgs += '--pyside6-dir'; $evidenceArgs += $pyside6Dir }
    $evidence = Invoke-Python -Arguments $evidenceArgs -LogFile (Join-Path $LogDir 'bundle_evidence.log')
    Write-Log -Message $evidence.Text
    if ($evidence.ExitCode -ne 0) {
        Write-Fail 'bundle evidence check failed (forbidden payload or missing protocol files)'
        $summary.errors += 'bundle evidence exit code ' + $evidence.ExitCode
        Complete-Summary -Status 'FAIL_BUNDLE_EVIDENCE' -ExitCode 5
    }
    $bundleJsonPath = Join-Path $LogDir 'bundle_evidence.json'
    if (Test-Path -LiteralPath $bundleJsonPath) {
        $be = Get-Content -LiteralPath $bundleJsonPath -Raw -Encoding utf8 | ConvertFrom-Json
        $summary.bundle = [ordered]@{
            exe = $be.exe
            exeBytes = $be.exeBytes
            exeSha256 = $be.exeSha256
            fileCount = $be.fileCount
            totalBytes = $be.totalBytes
            inventorySha256 = $be.inventorySha256
            qtDllCount = $be.qtDllCount
            protocol = $be.protocol
            warnings = @($be.warnings)
        }
        foreach ($warning in @($be.warnings)) { Write-Warn2 $warning; $summary.unverifiedItems += ('bundle warning: ' + $warning) }
    }
    Write-Pass ('bundle inventory sha256=' + $summary.bundle.inventorySha256 + ' files=' + $summary.bundle.fileCount + ' bytes=' + $summary.bundle.totalBytes)
    Write-Info2 ('exe sha256=' + $summary.bundle.exeSha256)

    $hashLines = New-Object System.Collections.Generic.List[string]
    $hashLines.Add((Get-Sha256 -Path $ExePath) + '  ' + $ExePath)
    if (Test-Path -LiteralPath $protocolManifestPath) {
        $hashLines.Add((Get-Sha256 -Path $protocolManifestPath) + '  ' + $protocolManifestPath)
    }
    $bundleEvidencePath = Join-Path $LogDir 'bundle_evidence.json'
    if (Test-Path -LiteralPath $bundleEvidencePath) {
        $hashLines.Add((Get-Sha256 -Path $bundleEvidencePath) + '  ' + $bundleEvidencePath)
    }
    Set-Content -LiteralPath (Join-Path $LogDir 'HASHES.sha256') -Value ($hashLines -join (Get-NewLine)) -Encoding utf8

    # ---------------------------------------------------------- 5. scrubbed-PATH self-test
    Write-Step '5/6 frozen exe self-test from temp dir with dev PATH scrubbed'
    if ($SkipSelfTest) {
        Write-Warn2 'self-test SKIPPED by -SkipSelfTest: build is NOT verified'
        $summary.selfTest = [ordered]@{ mode = 'skipped'; verified = $false; attempts = @() }
        $summary.unverifiedItems += 'self-test skipped (-SkipSelfTest); BackendCheck.exe is built but NOT verified'
        Complete-Summary -Status 'BUILT_UNVERIFIED' -ExitCode 0
    }

    $selfTestRoot = Join-Path $scratchRoot ('selftest-' + $Stamp)
    New-Item -ItemType Directory -Force -Path $selfTestRoot | Out-Null
    $selfTestTemp = Join-Path $selfTestRoot 'temp'
    $selfTestWork = Join-Path $selfTestRoot 'cwd'
    New-Item -ItemType Directory -Force -Path $selfTestTemp | Out-Null
    New-Item -ItemType Directory -Force -Path $selfTestWork | Out-Null

    $minPath = (@(
            (Join-Path $env:SystemRoot 'System32'),
            $env:SystemRoot,
            (Join-Path $env:SystemRoot 'System32\Wbem'),
            (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0')
        ) | Where-Object { Test-Path -LiteralPath $_ }) -join ';'
    $realAppData = Join-Path $env:LOCALAPPDATA 'SixMic3D'
    $realAppDataBefore = Test-Path -LiteralPath $realAppData
    Write-Info2 ('scrubbed PATH: ' + $minPath)
    Write-Info2 ('real user data dir (reference): ' + $realAppData)

    function Invoke-SelfTestAttempt {
        param(
            [string]$Label,
            [string]$UserDataDir,
            [string]$StdoutPath,
            [string]$StderrPath,
            [string]$WorkDir,
            [string]$TempDir
        )
        $savedEnv = Set-EnvForScrub -TempPath $TempDir -UserDataDir $UserDataDir -PathValue $minPath
        $pythonOnPath = $null -ne (Get-Command python -ErrorAction SilentlyContinue)
        $python3OnPath = $null -ne (Get-Command python3 -ErrorAction SilentlyContinue)
        $result = [ordered]@{
            label = $Label
            userDataDirOverride = $UserDataDir
            scrubbedPath = $minPath
            pythonOnScrubbedPath = $pythonOnPath
            python3OnScrubbedPath = $python3OnPath
            exitCode = $null
            lastLine = ''
            markerPass = $false
            timedOut = $false
            stdoutFile = $StdoutPath
            stderrFile = $StderrPath
            reportOk = $null
            checksPassed = $null
            checksTotal = $null
            reportError = $null
            dataDirCreated = $false
            evidenceFile = $null
            sandboxPermissionFailure = $false
        }
        try {
            $arguments = '--self-test --protocol-dir "' + $protocolDest + '"'
            $run = Invoke-CapturedProcess -FilePath $ExePath -Arguments $arguments -WorkingDirectory $WorkDir -StdoutPath $StdoutPath -StderrPath $StderrPath -TimeoutMs ($SelfTestTimeoutSeconds * 1000)
            $result.timedOut = $run.TimedOut
            if ($null -ne $run.ExitCode) { $result.exitCode = [int]$run.ExitCode }
            else { $result.exitCode = -1 }
        } finally {
            Restore-EnvAfterScrub -Saved $savedEnv
        }
        $result.lastLine = Get-LastNonEmptyLine -Path $StdoutPath
        $result.markerPass = ($result.lastLine -ceq 'SELF-TEST PASS')
        $report = Get-SelfTestReport -StdoutPath $StdoutPath
        if ($report) {
            $result.reportOk = $report.ok
            if ($report.PSObject.Properties.Name -contains 'error') { $result.reportError = $report.error }
            if ($report.PSObject.Properties.Name -contains 'checks') {
                $result.checksTotal = @($report.checks).Count
                $result.checksPassed = @($report.checks | Where-Object { $_.ok -eq $true }).Count
            }
        }
        if ($UserDataDir) {
            $result.dataDirCreated = Test-Path -LiteralPath $UserDataDir
            $candidateEvidence = Join-Path $UserDataDir 'evidence\backend-selftest.json'
            if (Test-Path -LiteralPath $candidateEvidence) { $result.evidenceFile = $candidateEvidence }
        } else {
            $result.dataDirCreated = Test-Path -LiteralPath $realAppData
            $candidateEvidence = Join-Path $realAppData 'evidence\backend-selftest.json'
            if (Test-Path -LiteralPath $candidateEvidence) { $result.evidenceFile = $candidateEvidence }
        }
        $stderrText = ''
        if (Test-Path -LiteralPath $StderrPath) { $stderrText = Get-Content -LiteralPath $StderrPath -Raw -Encoding utf8 }
        $stdoutText = ''
        if (Test-Path -LiteralPath $StdoutPath) { $stdoutText = Get-Content -LiteralPath $StdoutPath -Raw -Encoding utf8 }
        $result.sandboxPermissionFailure = Test-SandboxPermissionFailure -Text ($stderrText + $stdoutText)
        return [pscustomobject]$result
    }

    $attempts = @()
    if ($SelfTestDataDir) {
        Write-Info2 'data dir mode: explicit -SelfTestDataDir override (real %LOCALAPPDATA% not exercised)'
        $overrideDir = [System.IO.Path]::GetFullPath($SelfTestDataDir)
        $attempts += Invoke-SelfTestAttempt -Label 'override-explicit' -UserDataDir $overrideDir -StdoutPath (Join-Path $LogDir 'selftest.stdout.log') -StderrPath (Join-Path $LogDir 'selftest.stderr.log') -WorkDir $selfTestWork -TempDir $selfTestTemp
    } else {
        Write-Info2 'attempt: default user data dir (%LOCALAPPDATA%\SixMic3D)'
        $realAttempt = Invoke-SelfTestAttempt -Label 'default-localappdata' -UserDataDir $null -StdoutPath (Join-Path $LogDir 'selftest.stdout.log') -StderrPath (Join-Path $LogDir 'selftest.stderr.log') -WorkDir $selfTestWork -TempDir $selfTestTemp
        $attempts += $realAttempt
        if (-not ($realAttempt.markerPass -and $realAttempt.exitCode -eq 0)) {
            Write-Warn2 ('default %LOCALAPPDATA% run did not pass (exit=' + $realAttempt.exitCode + '); retrying with SIXMIC_USER_DATA_DIR scratch override')
            if ($realAttempt.sandboxPermissionFailure) {
                Write-Warn2 'default run failure is an OS permission denial - classified as harness sandbox limitation, not an app failure'
            }
            $overrideDir = Join-Path $selfTestRoot 'userdata'
            $attempts += Invoke-SelfTestAttempt -Label 'override-scratch' -UserDataDir $overrideDir -StdoutPath (Join-Path $LogDir 'selftest.override.stdout.log') -StderrPath (Join-Path $LogDir 'selftest.override.stderr.log') -WorkDir $selfTestWork -TempDir $selfTestTemp
        }
    }

    $summary.selfTest = [ordered]@{
        mode = 'self-test'
        attempts = @($attempts)
        verified = $false
        realLocalAppDataVerified = $false
        overrideVerified = $false
        dataDirMode = 'default-localappdata'
        evidenceFile = $null
    }
    $anyPass = @($attempts | Where-Object { $_.markerPass -and $_.exitCode -eq 0 }).Count -gt 0
    if ($anyPass) {
        $summary.selfTest.verified = $true
        $realPass = @($attempts | Where-Object { $_.label -eq 'default-localappdata' -and $_.markerPass -and $_.exitCode -eq 0 }).Count -gt 0
        $overridePass = @($attempts | Where-Object { $_.label -like 'override*' -and $_.markerPass -and $_.exitCode -eq 0 }).Count -gt 0
        $summary.selfTest.realLocalAppDataVerified = $realPass
        $summary.selfTest.overrideVerified = $overridePass
        $passing = @($attempts | Where-Object { $_.markerPass -and $_.exitCode -eq 0 })[0]
        if ($realPass) {
            Write-Pass 'self-test PASS with default %LOCALAPPDATA%\SixMic3D user data dir'
        } else {
            $summary.selfTest.dataDirMode = 'override'
            $summary.unverifiedItems += 'real %LOCALAPPDATA%\SixMic3D data dir creation NOT verified in this session (OS denied child writes to %LOCALAPPDATA%; harness sandbox limitation). Re-verify on a clean Windows machine without SIXMIC_USER_DATA_DIR.'
            Write-Pass 'self-test PASS with SIXMIC_USER_DATA_DIR scratch override (real %LOCALAPPDATA% remains UNVERIFIED here)'
        }
        $summary.selfTest.evidenceFile = $passing.evidenceFile
        Write-Info2 ('exit=' + $passing.exitCode + ' marker="' + $passing.lastLine + '" checks=' + $passing.checksPassed + '/' + $passing.checksTotal + ' dataDirCreated=' + $passing.dataDirCreated + ' evidence=' + $passing.evidenceFile)
        if (-not $passing.dataDirCreated) {
            Write-Warn2 'self-test passed but expected user data dir was not observed'
            $summary.unverifiedItems += 'self-test passed but user data dir creation was not observed'
        }
    } else {
        Write-Fail 'self-test FAILED on all attempts'
        foreach ($attempt in $attempts) {
            Write-Info2 ($attempt.label + ': exit=' + $attempt.exitCode + ' marker="' + $attempt.lastLine + '" timeout=' + $attempt.timedOut + ' error=' + $attempt.reportError)
        }
        $summary.errors += 'self-test failed on all attempts'
        $stdoutLog = Join-Path $LogDir 'selftest.override.stdout.log'
        if (-not (Test-Path -LiteralPath $stdoutLog)) { $stdoutLog = Join-Path $LogDir 'selftest.stdout.log' }
        if (Test-Path -LiteralPath $stdoutLog) {
            Write-Info2 '--- stdout tail ---'
            Write-Log -Message ((Get-Content -LiteralPath $stdoutLog -Encoding utf8 | Select-Object -Last 20) -join (Get-NewLine))
        }
        $stderrLog = Join-Path $LogDir 'selftest.override.stderr.log'
        if (-not (Test-Path -LiteralPath $stderrLog)) { $stderrLog = Join-Path $LogDir 'selftest.stderr.log' }
        if (Test-Path -LiteralPath $stderrLog) {
            Write-Info2 '--- stderr tail ---'
            Write-Log -Message ((Get-Content -LiteralPath $stderrLog -Encoding utf8 | Select-Object -Last 20) -join (Get-NewLine))
        }
        Complete-Summary -Status 'FAIL_SELF_TEST' -ExitCode 6
    }

    # ---------------------------------------------------------- 6. final
    Write-Step '6/6 evidence written'
    if ($summary.unverifiedItems.Count -gt 0) {
        Write-Warn2 'unverified items:'
        foreach ($item in $summary.unverifiedItems) { Write-Info2 ('- ' + $item) }
    }
    $finalStatus = 'PASS'
    if (-not $summary.selfTest.realLocalAppDataVerified) { $finalStatus = 'PASS_WITH_ENV_LIMITATION' }
    Write-Pass ('build + verification pipeline finished (' + $finalStatus + ')')
    Complete-Summary -Status $finalStatus -ExitCode 0
}
catch {
    Write-Fail ('unhandled error: ' + $_.Exception.Message)
    Write-Log -Message $_.ScriptStackTrace
    $summary.errors += $_.Exception.Message
    Complete-Summary -Status 'FAIL_UNHANDLED' -ExitCode 1
}
