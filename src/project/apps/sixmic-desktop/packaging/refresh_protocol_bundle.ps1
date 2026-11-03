#Requires -Version 5.1
<#
.SYNOPSIS
    Refresh the shipped protocol/ data bundles WITHOUT rebuilding the exe.

.DESCRIPTION
    Use when interfaces/pc_backend_v1 is extended (documentation/schema only) and
    the frozen SixMic3D-BackendCheck.exe itself is unaffected:
      1. verify protocol_data.SHIPPED_ENTRIES covers the whole frozen interface
         (shipped count == interface file count) and record the freeze markers
         (tools/freeze_marker.py: backendSha256/protocolSha256)
      2. recopy <bundle>/protocol/ (next to the exe) and
         <bundle>/_internal/protocol/ (PyInstaller datas copy)
      3. regenerate protocol manifests + bundle inventory evidence
      4. re-run the scrubbed-PATH --self-test of the existing frozen exe once
      5. write hashes + JSON summary under packaging/build-logs/<timestamp>-protocol-refresh/

    The exe is deliberately NOT rebuilt: PyInstaller output is not bit-for-bit
    reproducible and rebuilding would change the recorded exe SHA256 even though
    the code is unchanged.

.NOTES
    Exit codes: 0 = refreshed + self-test pass, 2 = preconditions/inputs,
                3 = copy failed, 4 = bundle evidence failed, 5 = self-test failed.
#>
[CmdletBinding()]
param(
    [string]$LogRoot,
    [switch]$SkipSelfTest,
    [string]$TempRoot
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$ScriptDir = $PSScriptRoot
$AppDir = Split-Path -Parent $ScriptDir
$RepoRoot = Split-Path -Parent (Split-Path -Parent $AppDir)
$VenvPython = Join-Path $AppDir '.venv\Scripts\python.exe'
$InterfacesDir = Join-Path $RepoRoot 'interfaces\pc_backend_v1'
$BundleDir = Join-Path $AppDir 'dist\SixMic3D-BackendCheck'
$ExePath = Join-Path $BundleDir 'SixMic3D-BackendCheck.exe'
$CopyTool = Join-Path $ScriptDir 'tools\copy_protocol_data.py'
$EvidenceTool = Join-Path $ScriptDir 'tools\bundle_evidence.py'
$FreezeTool = Join-Path $ScriptDir 'tools\freeze_marker.py'
$WriteProbe = Join-Path $ScriptDir 'tools\scratch_write_probe.py'
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
if (-not $LogRoot -or $LogRoot.Trim().Length -eq 0) { $LogRoot = Join-Path $ScriptDir 'build-logs' }
$LogDir = Join-Path $LogRoot ($Stamp + '-protocol-refresh')
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir 'refresh_protocol_bundle.log'
$script:LogPath = $LogFile

function Write-Log { param([string]$Message, [string]$Color = 'Gray') Write-Host $Message -ForegroundColor $Color; Add-Content -LiteralPath $script:LogPath -Value $Message -Encoding utf8 }
function Write-Step { param([string]$M) Write-Log -Message ''; Write-Log -Message ('=== ' + $M + ' ===') -Color Cyan }
function Write-Pass { param([string]$M) Write-Log -Message ('PASS  ' + $M) -Color Green }
function Write-Warn2 { param([string]$M) Write-Log -Message ('WARN  ' + $M) -Color Yellow }
function Write-Fail { param([string]$M) Write-Log -Message ('FAIL  ' + $M) -Color Red }
function Write-Info2 { param([string]$M) Write-Log -Message ('      ' + $M) }
function Get-NewLine { return [string]([char]13) + [string]([char]10) }
function Get-Sha256 { param([string]$Path) return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }

function Invoke-PythonCapture {
    param([string[]]$Arguments, [string]$OutFile)
    $savedEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $out = & $VenvPython @Arguments 2>&1; $code = $LASTEXITCODE } finally { $ErrorActionPreference = $savedEap }
    $text = ($out | ForEach-Object { $_.ToString() }) -join (Get-NewLine)
    if ($OutFile) { Set-Content -LiteralPath $OutFile -Value $text -Encoding utf8 }
    return [pscustomobject]@{ ExitCode = $code; Text = $text }
}

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

$summary = [ordered]@{
    operation = 'protocol-bundle-refresh'
    status = 'RUNNING'
    startedAtLocal = (Get-Date -Format 'o')
    finishedAtLocal = $null
    logDir = $LogDir
    logFile = $LogFile
    exe = [ordered]@{ path = $ExePath; sha256 = $null; bytes = $null; rebuilt = $false }
    freeze = $null
    shipped = $null
    adjacentManifest = $null
    internalManifest = $null
    bundleEvidence = $null
    selfTest = $null
    unverifiedItems = @()
    errors = @()
}

function Complete-Summary {
    param([string]$Status, [int]$ExitCode)
    $summary.status = $Status
    $summary.finishedAtLocal = (Get-Date -Format 'o')
    $summaryPath = Join-Path $LogDir 'refresh_protocol_bundle.json'
    $summary | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $summaryPath -Encoding utf8
    Write-Log -Message ''
    Write-Log -Message ('SUMMARY: ' + $Status)
    Write-Log -Message ('  summary json : ' + $summaryPath)
    Write-Log -Message ('  log          : ' + $LogFile)
    exit $ExitCode
}

try {
    Write-Log -Message ('SixMic3D protocol-bundle refresh - ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz'))
    Write-Log -Message ('interfaces : ' + $InterfacesDir)
    Write-Log -Message ('bundle     : ' + $BundleDir)

    Write-Step '1/5 preconditions + freeze markers'
    if (-not (Test-Path -LiteralPath $ExePath)) {
        Write-Fail ('frozen exe missing: ' + $ExePath + ' - run build_backend_check.ps1 first')
        Complete-Summary -Status 'FAIL_PRECONDITIONS' -ExitCode 2
    }
    $summary.exe.sha256 = Get-Sha256 -Path $ExePath
    $summary.exe.bytes = (Get-Item -LiteralPath $ExePath).Length
    $freeze = Invoke-PythonCapture -Arguments @($FreezeTool, '--json') -OutFile (Join-Path $LogDir 'freeze_marker.json')
    if ($freeze.ExitCode -ne 0) {
        Write-Fail 'freeze_marker.py failed'
        Complete-Summary -Status 'FAIL_PRECONDITIONS' -ExitCode 2
    }
    $freezeJson = $freeze.Text | ConvertFrom-Json
    $summary.freeze = [ordered]@{
        algorithm = $freezeJson.algorithm
        backendFileCount = $freezeJson.backendFileCount
        backendSha256 = $freezeJson.backendSha256
        protocolFileCount = $freezeJson.protocolFileCount
        protocolSha256 = $freezeJson.protocolSha256
    }
    Write-Info2 ('backendSha256=' + $freezeJson.backendSha256 + ' (' + $freezeJson.backendFileCount + ' .py)')
    Write-Info2 ('protocolSha256=' + $freezeJson.protocolSha256 + ' (' + $freezeJson.protocolFileCount + ' files)')

    $shippedProbe = Invoke-PythonCapture -Arguments @('-c', 'import sys,pathlib; sys.path.insert(0, sys.argv[1]); import protocol_data; files=list(protocol_data.iter_shipped_files(pathlib.Path(sys.argv[2]))); print(len(files))', (Join-Path $ScriptDir 'tools'), $InterfacesDir) -OutFile $null
    if ($shippedProbe.ExitCode -ne 0) {
        Write-Fail 'could not count shipped protocol files'
        Complete-Summary -Status 'FAIL_PRECONDITIONS' -ExitCode 2
    }
    $shippedCount = [int]$shippedProbe.Text.Trim()
    $summary.shipped = [ordered]@{ fileCount = $shippedCount; interfaceFileCount = $freezeJson.protocolFileCount }
    Write-Info2 ('shipped protocol data: ' + $shippedCount + ' files; frozen interface: ' + $freezeJson.protocolFileCount + ' files')
    if ($shippedCount -ne $freezeJson.protocolFileCount) {
        Write-Fail 'tools/protocol_data.py SHIPPED_ENTRIES is out of sync with interfaces/pc_backend_v1 - update it before refreshing'
        Complete-Summary -Status 'FAIL_PRECONDITIONS' -ExitCode 2
    }

    $scratchRoot = $null
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($TempRoot) { $candidates.Add($TempRoot) }
    if ($env:TEMP) { $candidates.Add((Join-Path $env:TEMP ('sixmic-protocol-refresh-' + $Stamp))) }
    $candidates.Add((Join-Path $LogDir 'scratch'))
    $savedEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        foreach ($candidate in $candidates) {
            try {
                New-Item -ItemType Directory -Force -Path $candidate | Out-Null
                $probeOut = & $VenvPython $WriteProbe $candidate 2>&1
                if ($LASTEXITCODE -eq 0) { $scratchRoot = (Resolve-Path -LiteralPath $candidate).Path; break }
            } catch { continue }
        }
    } finally { $ErrorActionPreference = $savedEap }
    if (-not $scratchRoot) { $scratchRoot = Join-Path $LogDir 'scratch' }
    $scratchTemp = Join-Path $scratchRoot 'temp'
    New-Item -ItemType Directory -Force -Path $scratchTemp | Out-Null
    $env:TEMP = $scratchTemp
    $env:TMP = $scratchTemp

    Write-Step '2/5 refresh adjacent protocol/ (next to exe)'
    $adjacentDest = Join-Path $BundleDir 'protocol'
    $copy1 = Invoke-PythonCapture -Arguments @($CopyTool, '--interfaces', $InterfacesDir, '--dest', $adjacentDest, '--report', (Join-Path $LogDir 'protocol_manifest.json')) -OutFile (Join-Path $LogDir 'protocol_copy.log')
    Write-Log -Message $copy1.Text
    if ($copy1.ExitCode -ne 0) {
        Write-Fail ('adjacent protocol copy failed (exit ' + $copy1.ExitCode + ')')
        Complete-Summary -Status 'FAIL_COPY' -ExitCode 3
    }
    $am = Get-Content -LiteralPath (Join-Path $LogDir 'protocol_manifest.json') -Raw -Encoding utf8 | ConvertFrom-Json
    $summary.adjacentManifest = [ordered]@{ destination = $am.destination; fileCount = $am.fileCount; totalBytes = $am.totalBytes; manifestSha256 = $am.manifestSha256 }
    Write-Pass ('adjacent protocol/ : ' + $am.fileCount + ' files, ' + $am.totalBytes + ' bytes, manifestSha256=' + $am.manifestSha256)

    Write-Step '3/5 refresh _internal/protocol/ (PyInstaller datas copy)'
    $internalDest = Join-Path $BundleDir '_internal\protocol'
    $copy2 = Invoke-PythonCapture -Arguments @($CopyTool, '--interfaces', $InterfacesDir, '--dest', $internalDest, '--report', (Join-Path $LogDir 'protocol_manifest_internal.json')) -OutFile (Join-Path $LogDir 'protocol_copy_internal.log')
    Write-Log -Message $copy2.Text
    if ($copy2.ExitCode -ne 0) {
        Write-Fail ('internal protocol copy failed (exit ' + $copy2.ExitCode + ')')
        Complete-Summary -Status 'FAIL_COPY' -ExitCode 3
    }
    $im = Get-Content -LiteralPath (Join-Path $LogDir 'protocol_manifest_internal.json') -Raw -Encoding utf8 | ConvertFrom-Json
    $summary.internalManifest = [ordered]@{ destination = $im.destination; fileCount = $im.fileCount; totalBytes = $im.totalBytes; manifestSha256 = $im.manifestSha256 }
    Write-Pass ('_internal/protocol/ : ' + $im.fileCount + ' files, ' + $im.totalBytes + ' bytes, manifestSha256=' + $im.manifestSha256)

    Write-Step '4/5 regenerate bundle inventory evidence'
    $evidence = Invoke-PythonCapture -Arguments @($EvidenceTool, '--bundle', $BundleDir, '--exe-name', 'SixMic3D-BackendCheck.exe', '--profile', 'backend', '--report', (Join-Path $LogDir 'bundle_evidence.json')) -OutFile (Join-Path $LogDir 'bundle_evidence.log')
    Write-Log -Message $evidence.Text
    if ($evidence.ExitCode -ne 0) {
        Write-Fail 'bundle evidence failed after refresh'
        Complete-Summary -Status 'FAIL_EVIDENCE' -ExitCode 4
    }
    $be = Get-Content -LiteralPath (Join-Path $LogDir 'bundle_evidence.json') -Raw -Encoding utf8 | ConvertFrom-Json
    $summary.bundleEvidence = [ordered]@{
        exeSha256 = $be.exeSha256
        fileCount = $be.fileCount
        totalBytes = $be.totalBytes
        inventorySha256 = $be.inventorySha256
        protocol = $be.protocol
        violations = @($be.violations)
        warnings = @($be.warnings)
    }
    if (@($be.violations).Count -gt 0) {
        Write-Fail 'bundle evidence reported violations after refresh'
        Complete-Summary -Status 'FAIL_EVIDENCE' -ExitCode 4
    }
    Write-Pass ('bundle inventory: files=' + $be.fileCount + ' bytes=' + $be.totalBytes + ' inventorySha256=' + $be.inventorySha256)
    Write-Info2 ('protocol counts: adjacent=' + $be.protocol.adjacentProtocolFiles + ' internal=' + $be.protocol._internalProtcolFiles)

    $hashLines = New-Object System.Collections.Generic.List[string]
    $hashLines.Add($summary.exe.sha256 + '  ' + $ExePath)
    $hashLines.Add((Get-Sha256 -Path (Join-Path $LogDir 'protocol_manifest.json')) + '  protocol_manifest.json')
    $hashLines.Add((Get-Sha256 -Path (Join-Path $LogDir 'protocol_manifest_internal.json')) + '  protocol_manifest_internal.json')
    $hashLines.Add((Get-Sha256 -Path (Join-Path $LogDir 'bundle_evidence.json')) + '  bundle_evidence.json')
    Set-Content -LiteralPath (Join-Path $LogDir 'HASHES.sha256') -Value ($hashLines -join (Get-NewLine)) -Encoding utf8

    Write-Step '5/5 scrubbed-PATH exe self-test (existing frozen exe, not rebuilt)'
    $summary.selfTest = [ordered]@{ verified = $false; realLocalAppDataVerified = $false; overrideVerified = $false; dataDirMode = 'default-localappdata'; attempts = @(); tailLine = ''; evidenceFile = $null }
    if ($SkipSelfTest) {
        Write-Warn2 'self-test SKIPPED by -SkipSelfTest: refresh is NOT verified'
        $summary.unverifiedItems += 'self-test skipped (-SkipSelfTest); protocol refresh not verified by the frozen exe'
        Complete-Summary -Status 'REFRESHED_UNVERIFIED' -ExitCode 0
    }
    $selfTestRoot = Join-Path $LogDir 'selftest'
    $selfTestCwd = Join-Path $selfTestRoot 'cwd'
    $selfTestTemp = Join-Path $selfTestRoot 'temp'
    New-Item -ItemType Directory -Force -Path $selfTestCwd | Out-Null
    New-Item -ItemType Directory -Force -Path $selfTestTemp | Out-Null
    $minPath = (@((Join-Path $env:SystemRoot 'System32'), $env:SystemRoot, (Join-Path $env:SystemRoot 'System32\Wbem'), (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0')) | Where-Object { Test-Path -LiteralPath $_ }) -join ';'
    $realAppData = Join-Path $env:LOCALAPPDATA 'SixMic3D'

    function Invoke-Attempt {
        param([string]$Label, [string]$UserDataDir, [string]$StdoutPath, [string]$StderrPath)
        $saved = @{
            PATH = $env:PATH; PYTHONPATH = $env:PYTHONPATH; PYTHONHOME = $env:PYTHONHOME
            VIRTUAL_ENV = $env:VIRTUAL_ENV; QT_PLUGIN_PATH = $env:QT_PLUGIN_PATH
            QML2_IMPORT_PATH = $env:QML2_IMPORT_PATH; QML_IMPORT_PATH = $env:QML_IMPORT_PATH
            SIXMIC_USER_DATA_DIR = $env:SIXMIC_USER_DATA_DIR; TEMP = $env:TEMP; TMP = $env:TMP
        }
        $result = [ordered]@{ label = $Label; exitCode = $null; lastLine = ''; markerPass = $false; timedOut = $false; dataDirCreated = $false; evidenceFile = $null; permissionDenied = $false }
        try {
            $env:PATH = $minPath
            foreach ($name in @('PYTHONPATH','PYTHONHOME','VIRTUAL_ENV','QT_PLUGIN_PATH','QML2_IMPORT_PATH','QML_IMPORT_PATH')) {
                Remove-Item -Path ('Env:' + $name) -ErrorAction SilentlyContinue
            }
            $env:TEMP = $selfTestTemp
            $env:TMP = $selfTestTemp
            $env:PYTHONIOENCODING = 'utf-8'
            if ($UserDataDir) { $env:SIXMIC_USER_DATA_DIR = $UserDataDir }
            else { Remove-Item -Path 'Env:SIXMIC_USER_DATA_DIR' -ErrorAction SilentlyContinue }
            $run = Invoke-CapturedProcess -FilePath $ExePath -Arguments ('--self-test --protocol-dir "' + $adjacentDest + '"') -WorkingDirectory $selfTestCwd -StdoutPath $StdoutPath -StderrPath $StderrPath -TimeoutMs 120000
            $result.timedOut = $run.TimedOut
            if ($null -ne $run.ExitCode) { $result.exitCode = [int]$run.ExitCode } else { $result.exitCode = -1 }
        } finally {
            foreach ($key in $saved.Keys) {
                if ($null -eq $saved[$key]) { Remove-Item -Path ('Env:' + $key) -ErrorAction SilentlyContinue }
                else { Set-Item -Path ('Env:' + $key) -Value $saved[$key] }
            }
        }
        if (Test-Path -LiteralPath $StdoutPath) {
            $lines = Get-Content -LiteralPath $StdoutPath -Encoding utf8 | Where-Object { $_.Trim().Length -gt 0 }
            if ($lines -and $lines.Count -gt 0) { $result.lastLine = [string]($lines[$lines.Count - 1]).Trim() }
            $text = Get-Content -LiteralPath $StdoutPath -Raw -Encoding utf8
            if ($text -and ($text -match 'WinError 5' -or $text -match 'PermissionError')) { $result.permissionDenied = $true }
        }
        if (Test-Path -LiteralPath $StderrPath) {
            $errText = Get-Content -LiteralPath $StderrPath -Raw -Encoding utf8
            if ($errText -and ($errText -match 'WinError 5' -or $errText -match 'PermissionError')) { $result.permissionDenied = $true }
        }
        $result.markerPass = ($result.lastLine -ceq 'SELF-TEST PASS')
        if ($UserDataDir) {
            $result.dataDirCreated = Test-Path -LiteralPath $UserDataDir
            $candidateEvidence = Join-Path $UserDataDir 'evidence\backend-selftest.json'
            if (Test-Path -LiteralPath $candidateEvidence) { $result.evidenceFile = $candidateEvidence }
        } else {
            $result.dataDirCreated = Test-Path -LiteralPath $realAppData
            $candidateEvidence = Join-Path $realAppData 'evidence\backend-selftest.json'
            if (Test-Path -LiteralPath $candidateEvidence) { $result.evidenceFile = $candidateEvidence }
        }
        return [pscustomobject]$result
    }

    $attempts = @()
    $a1 = Invoke-Attempt -Label 'default-localappdata' -UserDataDir $null -StdoutPath (Join-Path $LogDir 'selftest.stdout.log') -StderrPath (Join-Path $LogDir 'selftest.stderr.log')
    $attempts += $a1
    if (-not ($a1.markerPass -and $a1.exitCode -eq 0)) {
        Write-Warn2 ('default %LOCALAPPDATA% run did not pass (exit=' + $a1.exitCode + '); retrying with SIXMIC_USER_DATA_DIR scratch override')
        if ($a1.permissionDenied) { Write-Warn2 'default run failure is an OS permission denial - harness sandbox limitation, not an app failure' }
        $a2 = Invoke-Attempt -Label 'override-scratch' -UserDataDir (Join-Path $selfTestRoot 'userdata') -StdoutPath (Join-Path $LogDir 'selftest.override.stdout.log') -StderrPath (Join-Path $LogDir 'selftest.override.stderr.log')
        $attempts += $a2
    }
    $summary.selfTest.attempts = @($attempts)
    $passing = @($attempts | Where-Object { $_.markerPass -and $_.exitCode -eq 0 })
    $realPass = @($attempts | Where-Object { $_.label -eq 'default-localappdata' -and $_.markerPass -and $_.exitCode -eq 0 }).Count -gt 0
    $overridePass = @($attempts | Where-Object { $_.label -eq 'override-scratch' -and $_.markerPass -and $_.exitCode -eq 0 }).Count -gt 0
    if ($passing.Count -eq 0) {
        Write-Fail 'self-test FAILED after refresh'
        foreach ($attempt in $attempts) { Write-Info2 ($attempt.label + ': exit=' + $attempt.exitCode + ' marker="' + $attempt.lastLine + '" timedOut=' + $attempt.timedOut) }
        $stdoutLog = Join-Path $LogDir 'selftest.override.stdout.log'
        if (-not (Test-Path -LiteralPath $stdoutLog)) { $stdoutLog = Join-Path $LogDir 'selftest.stdout.log' }
        if (Test-Path -LiteralPath $stdoutLog) { Write-Log -Message ((Get-Content -LiteralPath $stdoutLog -Encoding utf8 | Select-Object -Last 20) -join (Get-NewLine)) }
        Complete-Summary -Status 'FAIL_SELF_TEST' -ExitCode 5
    }
    $best = $passing[0]
    $summary.selfTest.verified = $true
    $summary.selfTest.realLocalAppDataVerified = $realPass
    $summary.selfTest.overrideVerified = $overridePass
    $summary.selfTest.tailLine = [string]$best.lastLine
    $summary.selfTest.evidenceFile = $best.evidenceFile
    if (-not $realPass) {
        $summary.selfTest.dataDirMode = 'override'
        $summary.unverifiedItems += 'real %LOCALAPPDATA%\SixMic3D creation not verified in this environment (harness sandbox denies child writes there); verified through SIXMIC_USER_DATA_DIR override.'
    }
    Write-Pass ('self-test PASS after refresh via ' + $best.label + ' (exit=' + $best.exitCode + ', marker="' + $best.lastLine + '", dataDirCreated=' + $best.dataDirCreated + ')')

    Write-Step 'evidence'
    if ($summary.unverifiedItems.Count -gt 0) {
        foreach ($item in $summary.unverifiedItems) { Write-Warn2 ('- ' + $item) }
    }
    Write-Log -Message ''
    Write-Log -Message ('REFRESHED_PROTOCOL_FILES=' + $am.fileCount)
    Write-Log -Message ('REFRESHED_PROTOCOL_BYTES=' + $am.totalBytes)
    Write-Log -Message ('REFRESHED_PROTOCOL_MANIFEST_SHA256=' + $am.manifestSha256)
    Write-Log -Message ('EXE_SHA256_UNCHANGED=' + $summary.exe.sha256)
    Write-Log -Message ('SELFTEST_TAIL=' + $best.lastLine)
    Complete-Summary -Status 'PROTOCOL_REFRESHED' -ExitCode 0
}
catch {
    Write-Fail ('unhandled error: ' + $_.Exception.Message)
    Write-Log -Message $_.ScriptStackTrace
    $summary.errors += $_.Exception.Message
    Complete-Summary -Status 'FAIL_UNHANDLED' -ExitCode 1
}
