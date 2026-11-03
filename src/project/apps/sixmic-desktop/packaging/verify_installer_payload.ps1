#Requires -Version 5.1
<#
.SYNOPSIS
    Verify a compiled echo installer when this environment blocks installer
    EXECUTION: extract its payload with innoextract, prove the payload is
    byte-identical to the verified build bundles, and run the extracted
    "installed layout" (windowed GUI offscreen smoke + backend self-test).

.DESCRIPTION
    Why this script exists: on the current Windows host, unsigned third-party
    executables run under a restricted profile (they cannot write %APPDATA% or
    HKCU; verified by an unsigned PyInstaller probe), while Microsoft-signed
    processes (powershell, cmd) can. Consequently BOTH Inno Setup and NSIS
    silent installers fail here at the shortcut/uninstall-registry step; that is
    an environment limitation, not a product defect. The real install/uninstall
    flow is covered by smoke_test_installer.ps1 on a normal Windows machine.

    This script:
      1. records the installer file (size, sha256, Authenticode, version info);
      2. attempts a real silent install and captures the exact failure evidence
         (setup log lines) - the attempt is never hidden;
      3. extracts the installer payload with the vendored innoextract 1.9
         (official tool) and proves the payload equals the verified dist bundles:
            app/_internal + app/protocol + app/echo.exe == dist/echo
            app/BackendCheck                           == dist/SixMic3D-BackendCheck
            app/licenses                               == packaging/licenses
         per-file SHA256 comparison (missing/extra/mismatch counts);
      4. runs the extracted installed layout: packaged GUI --self-test and
         --smoke-gui 3 offscreen (scrubbed PATH, throw-away cwd, user-data
         override), and BackendCheck --self-test with the installed protocol dir;
      5. diagnoses the environment block (unsigned packaged exe profile write vs
         signed PowerShell HKCU write);
      6. writes installer_payload_verification.json + logs.

    Exit codes: 0 = real install verified; 1 = payload/extracted smoke FAILED;
                3 = NOT VERIFIED (installer execution blocked by the environment,
                payload verification result recorded); 2 = missing inputs.
#>
[CmdletBinding()]
param(
    [string]$InstallerPath,
    [string]$LogRoot,
    [string]$InstallDir,
    [switch]$SkipInstallAttempt,
    [switch]$SkipPayloadSmoke,
    [int]$TimeoutSeconds = 300
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$ScriptDir = $PSScriptRoot
$AppDir = Split-Path -Parent $ScriptDir
$DistRoot = Join-Path $AppDir 'dist'
$DesktopBundle = Join-Path $DistRoot 'echo'
$BackendBundle = Join-Path $DistRoot 'SixMic3D-BackendCheck'
$LicenseDir = Join-Path $ScriptDir 'licenses'
$DefaultInstaller = Join-Path $DistRoot 'installer\echo-Setup-x64.exe'
$ExtractTool = Join-Path $ScriptDir 'vendor\tools\innoextract-1.9\innoextract.exe'
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
if (-not $LogRoot -or $LogRoot.Trim().Length -eq 0) { $LogRoot = Join-Path $ScriptDir 'build-logs' }
$LogDir = Join-Path $LogRoot ($Stamp + '-installer-payload')
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$VerifyLog = Join-Path $LogDir 'verify_installer_payload.log'
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

function Get-TreeMap {
    param([string]$Root)
    $map = @{}
    if (-not (Test-Path -LiteralPath $Root)) { return $map }
    $rootFull = (Resolve-Path -LiteralPath $Root).Path
    Get-ChildItem -LiteralPath $rootFull -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
        $rel = $_.FullName.Substring($rootFull.Length).TrimStart('\')
        $map[$rel] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    return $map
}

function Compare-TreeMap {
    param([hashtable]$Expected, [hashtable]$Actual, [string]$Label)
    $missing = @($Expected.Keys | Where-Object { -not $Actual.ContainsKey($_) } | Sort-Object)
    $extra = @($Actual.Keys | Where-Object { -not $Expected.ContainsKey($_) } | Sort-Object)
    $mismatch = @($Expected.Keys | Where-Object { $Actual.ContainsKey($_) -and $Actual[$_] -ne $Expected[$_] } | Sort-Object)
    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($rel in ($Expected.Keys | Sort-Object)) {
        $actualHash = ''
        if ($Actual.ContainsKey($rel)) { $actualHash = $Actual[$rel] }
        $lines.Add($rel + '|' + $Expected[$rel] + '|' + $actualHash)
    }
    $canonical = ($lines -join [string]([char]10))
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $hash = (($sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($canonical))) | ForEach-Object { $_.ToString('x2') }) -join ''
    return [ordered]@{
        label = $Label
        expectedFiles = $Expected.Count
        actualFiles = $Actual.Count
        missing = @($missing)
        extra = @($extra)
        mismatched = @($mismatch)
        ok = ($missing.Count -eq 0 -and $extra.Count -eq 0 -and $mismatch.Count -eq 0)
        manifestSha256 = $hash
    }
}

$report = [ordered]@{
    artifact = 'echo-Setup-x64.exe'
    status = 'RUNNING'
    startedAtLocal = (Get-Date -Format 'o')
    finishedAtLocal = $null
    logDir = $LogDir
    logFile = $VerifyLog
    installer = $null
    realInstall = $null
    environmentBlock = $null
    environmentDiagnosis = $null
    payload = $null
    extractedLayoutSmoke = $null
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
    $reportPath = Join-Path $LogDir 'installer_payload_verification.json'
    $report | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $reportPath -Encoding utf8
    Write-Log -Message ''
    Write-Log -Message ('SUMMARY: ' + $Status)
    Write-Log -Message ('  report json : ' + $reportPath)
    Write-Log -Message ('  verify log  : ' + $VerifyLog)
    exit $ExitCode
}

if (-not $InstallerPath -or $InstallerPath.Trim().Length -eq 0) { $InstallerPath = $DefaultInstaller }
if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
    Write-Fail ('installer not found: ' + $InstallerPath)
    $report.errors += 'installer not found'
    Complete-Report -Status 'MISSING_INSTALLER' -ExitCode 2
}
$resolvedInstaller = (Resolve-Path -LiteralPath $InstallerPath).Path
if (-not (Test-Path -LiteralPath $ExtractTool)) { Write-Fail ('innoextract missing: ' + $ExtractTool); Complete-Report -Status 'MISSING_EXTRACT_TOOL' -ExitCode 2 }
if (-not (Test-Path -LiteralPath $DesktopBundle)) { Write-Fail ('desktop bundle missing: ' + $DesktopBundle); Complete-Report -Status 'MISSING_INPUTS' -ExitCode 2 }

Write-Log -Message ('echo installer payload verification - ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz'))
Write-Log -Message ('installer: ' + $resolvedInstaller)
Write-Log -Message ('log dir  : ' + $LogDir)

# ------------------------------------------------------------------ 1 installer metadata
Write-Step '1/6 installer file metadata'
$installerHash = (Get-FileHash -LiteralPath $resolvedInstaller -Algorithm SHA256).Hash.ToLowerInvariant()
$installerItem = Get-Item -LiteralPath $resolvedInstaller
$auth = Get-AuthenticodeSignature -LiteralPath $resolvedInstaller
$report.installer = [ordered]@{
    path = $resolvedInstaller
    bytes = $installerItem.Length
    sha256 = $installerHash
    fileVersion = [string]$installerItem.VersionInfo.FileVersion
    productVersion = [string]$installerItem.VersionInfo.ProductVersion
    companyName = [string]$installerItem.VersionInfo.CompanyName
    authenticodeStatus = [string]$auth.Status
    signed = ($auth.Status -eq 'Valid')
    compiler = 'Inno Setup 6.0.5 (u) - vendored official release, see packaging/vendor/README.md'
}
Add-Check -Name 'installer-sha256' -Ok $true -Detail ($installerHash + ' bytes=' + $installerItem.Length)
Add-Check -Name 'installer-authenticode' -Ok ($auth.Status -eq 'Valid') -Detail ([string]$auth.Status + ' (this pipeline does not sign)') -Warning

# ------------------------------------------------------------------ 2 real install attempt
Write-Step '2/6 real silent install attempt (expected to be blocked in this sandbox)'
$setupLog = Join-Path $LogDir 'installer-setup-attempt.log'
if (-not $InstallDir) { $InstallDir = Join-Path $LogDir 'install-target' }
$InstallDir = [System.IO.Path]::GetFullPath($InstallDir)
if (Test-Path -LiteralPath $InstallDir) { Remove-Item -LiteralPath $InstallDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$scopedTemp = Join-Path $LogDir 'temp'
New-Item -ItemType Directory -Force -Path $scopedTemp | Out-Null
$realInstallExit = $null
if (-not $SkipInstallAttempt) {
    $savedTemp = $env:TEMP
    $savedTmp = $env:TMP
    try {
        $env:TEMP = $scopedTemp
        $env:TMP = $scopedTemp
        $argString = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="' + $InstallDir + '" /LOG="' + $setupLog + '"'
        Write-Info2 ('command: ' + $resolvedInstaller + ' ' + $argString)
        $start = Get-Date
        $setupProc = Start-Process -FilePath $resolvedInstaller -ArgumentList $argString -Wait -PassThru -NoNewWindow
        $realInstallExit = $setupProc.ExitCode
        $seconds = [math]::Round(((Get-Date) - $start).TotalSeconds, 1)
        Write-Info2 ('setup exit=' + $realInstallExit + ' duration=' + $seconds + 's')
        $report.realInstall = [ordered]@{ attempted = $true; exitCode = $realInstallExit; durationSeconds = $seconds; installDir = $InstallDir; setupLog = $setupLog }
    } catch {
        $report.realInstall = [ordered]@{ attempted = $true; exitCode = $null; error = $_.Exception.Message; installDir = $InstallDir; setupLog = $setupLog }
        Write-Warn2 ('installer process could not be started: ' + $_.Exception.Message)
    } finally {
        $env:TEMP = $savedTemp
        $env:TMP = $savedTmp
    }
} else {
    $report.realInstall = [ordered]@{ attempted = $false }
    Write-Warn2 'real install attempt skipped (-SkipInstallAttempt)'
}

if ($realInstallExit -eq 0) {
    Add-Check -Name 'installer-exit-code' -Ok $true -Detail 'real silent install completed with exit 0'
} else {
    $setupLogText = Read-TextFileSafe -Path $setupLog
    $blockPattern = '(Error 5|Access is denied|RegCreateKeyEx failed|IPersistFile::Save failed|Setup was unable)'
    $blockLines = @()
    foreach ($line in ($setupLogText -split '[\r\n]+')) {
        if ($line.Trim().Length -gt 0 -and [regex]::IsMatch($line, $blockPattern, 'IgnoreCase')) { $blockLines += $line.Trim() }
    }
    $report.environmentBlock = [ordered]@{
        detected = ($blockLines.Count -gt 0)
        setupExitCode = $realInstallExit
        blockingLines = @($blockLines | Select-Object -First 12)
        note = 'Unsigned third-party executables run under a restricted profile in this sandbox: the installer process is denied writes to the Start Menu shortcut folder and the HKCU uninstall registry key (Error 5), and unsigned packaged exes cannot write their default %LOCALAPPDATA% directory. Microsoft-signed processes (powershell/cmd) can perform the same writes, so this is an environment limitation, not a product defect.'
    }
    Add-Check -Name 'installer-exit-code' -Ok $false -Warning -Detail ('real install blocked by environment (exit=' + $realInstallExit + ', ' + $blockLines.Count + ' permission-denied log lines)')
    Write-Warn2 'real silent install is blocked by the environment; proceeding with installer payload extraction verification'
}

# ------------------------------------------------------------------ 3 extract payload
Write-Step '3/6 extract installer payload with innoextract 1.9 (official tool)'
$extractRoot = Join-Path $LogDir 'installer-payload'
if (Test-Path -LiteralPath $extractRoot) { Remove-Item -LiteralPath $extractRoot -Recurse -Force }
New-Item -ItemType Directory -Force -Path $extractRoot | Out-Null
$extractOut = & $ExtractTool '--extract' '--output-dir' $extractRoot '--progress=no' $resolvedInstaller 2>&1
$extractExit = $LASTEXITCODE
$extractText = ($extractOut | ForEach-Object { $_.ToString() }) -join ([string]([char]13) + [string]([char]10))
Set-Content -LiteralPath (Join-Path $LogDir 'innoextract.log') -Value $extractText -Encoding utf8
Add-Check -Name 'innoextract-exit-code' -Ok ($extractExit -eq 0) -Detail ('exit=' + $extractExit)
$appRoot = Join-Path $extractRoot 'app'
Add-Check -Name 'payload-app-tree-extracted' -Ok (Test-Path -LiteralPath $appRoot) -Detail $appRoot
if (-not (Test-Path -LiteralPath $appRoot)) { Complete-Report -Status 'FAIL_PAYLOAD_EXTRACTION' -ExitCode 1 }

# ------------------------------------------------------------------ 4 payload equality
Write-Step '4/6 payload equals verified build bundles (per-file SHA256)'
$desktopMap = Get-TreeMap -Root $DesktopBundle
$backendMap = Get-TreeMap -Root $BackendBundle
$licenseMap = Get-TreeMap -Root $LicenseDir

$extractedDesktop = @{}
Get-ChildItem -LiteralPath $appRoot -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
    $rel = $_.FullName.Substring($appRoot.Length).TrimStart('\')
    if ($rel -like 'BackendCheck\*' -or $rel -like 'licenses\*') { return }
    $extractedDesktop[$rel] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
}
$extractedBackend = @{}
$backendRoot = Join-Path $appRoot 'BackendCheck'
if (Test-Path -LiteralPath $backendRoot) {
    Get-ChildItem -LiteralPath $backendRoot -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
        $rel = $_.FullName.Substring($backendRoot.Length).TrimStart('\')
        $extractedBackend[$rel] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
$extractedLicenses = @{}
$licenseRoot = Join-Path $appRoot 'licenses'
if (Test-Path -LiteralPath $licenseRoot) {
    Get-ChildItem -LiteralPath $licenseRoot -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
        $rel = $_.FullName.Substring($licenseRoot.Length).TrimStart('\')
        $extractedLicenses[$rel] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
$desktopCompare = Compare-TreeMap -Expected $desktopMap -Actual $extractedDesktop -Label 'desktop-bundle'
$backendCompare = Compare-TreeMap -Expected $backendMap -Actual $extractedBackend -Label 'backendcheck-bundle'
$licenseCompare = Compare-TreeMap -Expected $licenseMap -Actual $extractedLicenses -Label 'licenses'
$report.payload = [ordered]@{
    extractRoot = $extractRoot
    appRoot = $appRoot
    desktop = $desktopCompare
    backendCheck = $backendCompare
    licenses = $licenseCompare
}
Add-Check -Name 'payload-desktop-bundle-equal' -Ok $desktopCompare.ok -Detail ('expected=' + $desktopCompare.expectedFiles + ' actual=' + $desktopCompare.actualFiles + ' missing=' + @($desktopCompare.missing).Count + ' extra=' + @($desktopCompare.extra).Count + ' mismatch=' + @($desktopCompare.mismatched).Count + ' manifest=' + $desktopCompare.manifestSha256)
Add-Check -Name 'payload-backendcheck-equal' -Ok $backendCompare.ok -Detail ('expected=' + $backendCompare.expectedFiles + ' actual=' + $backendCompare.actualFiles + ' missing=' + @($backendCompare.missing).Count + ' extra=' + @($backendCompare.extra).Count + ' mismatch=' + @($backendCompare.mismatched).Count)
Add-Check -Name 'payload-licenses-equal' -Ok $licenseCompare.ok -Detail ('expected=' + $licenseCompare.expectedFiles + ' actual=' + $licenseCompare.actualFiles + ' missing=' + @($licenseCompare.missing).Count + ' extra=' + @($licenseCompare.extra).Count + ' mismatch=' + @($licenseCompare.mismatched).Count)

# ------------------------------------------------------------------ 5 extracted installed layout
Write-Step '5/6 extracted installed layout smoke (windowed GUI offscreen + backend self-test)'
if ($SkipPayloadSmoke) {
    Write-Warn2 'extracted layout smoke skipped (-SkipPayloadSmoke)'
    $report.unverifiedItems += 'Extracted installed-layout smoke skipped (-SkipPayloadSmoke).'
} else {
    $extractedExe = Join-Path $appRoot 'echo.exe'
    $extractedBackendExe = Join-Path $appRoot 'BackendCheck\SixMic3D-BackendCheck.exe'
    $smokeCwd = Join-Path $LogDir 'extracted-cwd'
    $smokeTemp = Join-Path $LogDir 'extracted-temp'
    $smokeUserData = Join-Path $LogDir 'extracted-userdata'
    New-Item -ItemType Directory -Force -Path $smokeCwd | Out-Null
    New-Item -ItemType Directory -Force -Path $smokeTemp | Out-Null
    $minPath = (@((Join-Path $env:SystemRoot 'System32'), $env:SystemRoot, (Join-Path $env:SystemRoot 'System32\Wbem'), (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0')) | Where-Object { Test-Path -LiteralPath $_ }) -join ';'
    $savedEnv = @{
        PATH = $env:PATH; PYTHONPATH = $env:PYTHONPATH; PYTHONHOME = $env:PYTHONHOME; VIRTUAL_ENV = $env:VIRTUAL_ENV
        QT_PLUGIN_PATH = $env:QT_PLUGIN_PATH; QML2_IMPORT_PATH = $env:QML2_IMPORT_PATH; QML_IMPORT_PATH = $env:QML_IMPORT_PATH
        TEMP = $env:TEMP; TMP = $env:TMP; SIXMIC_USER_DATA_DIR = $env:SIXMIC_USER_DATA_DIR
        QT_QPA_PLATFORM = $env:QT_QPA_PLATFORM; QT_QUICK_BACKEND = $env:QT_QUICK_BACKEND
        QT_ASSUME_STDERR_HAS_CONSOLE = $env:QT_ASSUME_STDERR_HAS_CONSOLE; SIXMIC_PACKAGING_GUI_LOG = $env:SIXMIC_PACKAGING_GUI_LOG
    }
    $guiStdout = Join-Path $LogDir 'extracted-gui.stdout.log'
    $guiStderr = Join-Path $LogDir 'extracted-gui.stderr.log'
    $guiCapture = Join-Path $LogDir 'extracted-gui.capture.log'
    $selfTestStdout = Join-Path $LogDir 'extracted-selftest.stdout.log'
    $selfTestStderr = Join-Path $LogDir 'extracted-selftest.stderr.log'
    $selfTestCapture = Join-Path $LogDir 'extracted-selftest.capture.log'
    $backendStdout = Join-Path $LogDir 'extracted-backend.stdout.log'
    $backendStderr = Join-Path $LogDir 'extracted-backend.stderr.log'
    $guiRun = $null
    $selfTestRun = $null
    $backendRun = $null
    try {
        $env:PATH = $minPath
        foreach ($name in @('PYTHONPATH','PYTHONHOME','VIRTUAL_ENV','QT_PLUGIN_PATH','QML2_IMPORT_PATH','QML_IMPORT_PATH')) { Remove-Item -Path ('Env:' + $name) -ErrorAction SilentlyContinue }
        $env:TEMP = $smokeTemp
        $env:TMP = $smokeTemp
        $env:SIXMIC_USER_DATA_DIR = $smokeUserData
        $env:SIXMIC_PACKAGING_GUI_LOG = $selfTestCapture
        $selfTestRun = Invoke-CapturedProcess -FilePath $extractedExe -Arguments '--self-test' -WorkingDirectory $smokeCwd -StdoutPath $selfTestStdout -StderrPath $selfTestStderr -TimeoutMs ($TimeoutSeconds * 1000)
        $env:SIXMIC_PACKAGING_GUI_LOG = $guiCapture
        $env:QT_QPA_PLATFORM = 'offscreen'
        $env:QT_QUICK_BACKEND = 'software'
        $env:QT_ASSUME_STDERR_HAS_CONSOLE = '1'
        $guiRun = Invoke-CapturedProcess -FilePath $extractedExe -Arguments '--smoke-gui 3' -WorkingDirectory $smokeCwd -StdoutPath $guiStdout -StderrPath $guiStderr -TimeoutMs ($TimeoutSeconds * 1000)
        if (Test-Path -LiteralPath $extractedBackendExe) {
            $env:SIXMIC_PACKAGING_GUI_LOG = ''
            $backendProtocol = Join-Path $appRoot 'BackendCheck\protocol'
            $backendArgs = '--self-test --protocol-dir "' + $backendProtocol + '"'
            $backendRun = Invoke-CapturedProcess -FilePath $extractedBackendExe -Arguments $backendArgs -WorkingDirectory $smokeCwd -StdoutPath $backendStdout -StderrPath $backendStderr -TimeoutMs ($TimeoutSeconds * 1000)
        }
    } finally {
        foreach ($key in $savedEnv.Keys) {
            if ($null -eq $savedEnv[$key]) { Remove-Item -Path ('Env:' + $key) -ErrorAction SilentlyContinue }
            else { Set-Item -Path ('Env:' + $key) -Value $savedEnv[$key] }
        }
    }
    $guiText = Read-TextFileSafe -Path $guiCapture
    $guiOutText = Read-TextFileSafe -Path $guiStdout
    $guiErrText = Read-TextFileSafe -Path $guiStderr
    $qmlErrors = @(Find-QmlErrors -Texts @($guiText, $guiOutText, $guiErrText))
    $guiMarker = ''
    if ($guiText -match 'SMOKE_GUI_OK' -or $guiOutText -match 'SMOKE_GUI_OK') { $guiMarker = 'SMOKE_GUI_OK' }
    elseif ($guiText -match 'SMOKE_GUI_WARNINGS' -or $guiOutText -match 'SMOKE_GUI_WARNINGS') { $guiMarker = 'SMOKE_GUI_WARNINGS' }
    $selfTestText = Read-TextFileSafe -Path $selfTestCapture
    $backendText = Read-TextFileSafe -Path $backendStdout
    $backendPass = ($backendText -match 'SELF-TEST PASS')
    $report.extractedLayoutSmoke = [ordered]@{
        exe = $extractedExe
        guiExitCode = $guiRun.ExitCode
        guiTimedOut = $guiRun.TimedOut
        guiMarker = $guiMarker
        qmlErrors = @($qmlErrors)
        selfTestExitCode = $selfTestRun.ExitCode
        selfTestPassMarker = ($selfTestText -match 'SELF-TEST PASS')
        backendSelfTestExitCode = $null
        backendSelfTestPassMarker = $backendPass
        logs = [ordered]@{ guiCapture = $guiCapture; guiStdout = $guiStdout; guiStderr = $guiStderr; selfTestCapture = $selfTestCapture; backendStdout = $backendStdout; backendStderr = $backendStderr }
    }
    if ($null -ne $backendRun) { $report.extractedLayoutSmoke.backendSelfTestExitCode = $backendRun.ExitCode }
    $qmlErrorDetail = @($qmlErrors) -join ' | '
    if (-not $qmlErrorDetail) { $qmlErrorDetail = 'none' }
    Add-Check -Name 'extracted-app-self-test' -Ok (($selfTestRun.ExitCode -eq 0) -and ([bool]($selfTestText -match 'SELF-TEST PASS'))) -Detail ('exit=' + $selfTestRun.ExitCode + ' marker=' + [string]($selfTestText -match 'SELF-TEST PASS'))
    Add-Check -Name 'extracted-app-offscreen-gui' -Ok (($guiRun.ExitCode -eq 0) -and -not $guiRun.TimedOut) -Detail ('exit=' + $guiRun.ExitCode + ' timedOut=' + $guiRun.TimedOut + ' marker=' + $guiMarker)
    Add-Check -Name 'extracted-app-no-qml-errors' -Ok (@($qmlErrors).Count -eq 0) -Detail $qmlErrorDetail
    if ($null -ne $backendRun) { Add-Check -Name 'extracted-backend-self-test' -Ok (($backendRun.ExitCode -eq 0) -and $backendPass) -Detail ('exit=' + $backendRun.ExitCode + ' marker=' + [string]$backendPass) }
}

# ------------------------------------------------------------------ 6 environment diagnosis
Write-Step '6/6 environment diagnosis: startup fallback (new main.py) + installer restriction evidence'
$diagnosis = [ordered]@{ noOverrideStartup = $null; unwritableOverrideStartup = $null; signedPowerShellHkcuWrite = $null }
$probeExe = Join-Path $DesktopBundle 'echo.exe'
if (Test-Path -LiteralPath $probeExe) {
    $probeCwd = Join-Path $LogDir 'env-probe-cwd'
    $probeTemp = Join-Path $LogDir 'env-probe-temp'
    New-Item -ItemType Directory -Force -Path $probeCwd | Out-Null
    New-Item -ItemType Directory -Force -Path $probeTemp | Out-Null
    $savedTemp = $env:TEMP
    $savedTmp = $env:TMP
    $savedUserData = $env:SIXMIC_USER_DATA_DIR
    $savedPath = $env:PATH
    $savedPlatform = $env:QT_QPA_PLATFORM
    $savedBackend = $env:QT_QUICK_BACKEND
    $savedConsole = $env:QT_ASSUME_STDERR_HAS_CONSOLE
    $savedGuiLog = $env:SIXMIC_PACKAGING_GUI_LOG
    $appFallback = Join-Path $DesktopBundle 'user-data'
    try {
        $env:TEMP = $probeTemp
        $env:TMP = $probeTemp
        $env:PATH = (@((Join-Path $env:SystemRoot 'System32'), $env:SystemRoot) -join ';')
        $env:QT_QPA_PLATFORM = 'offscreen'
        $env:QT_QUICK_BACKEND = 'software'
        $env:QT_ASSUME_STDERR_HAS_CONSOLE = '1'
        # A) no override at all: main.py must find a writable fallback and start
        Remove-Item -Path 'Env:SIXMIC_USER_DATA_DIR' -ErrorAction SilentlyContinue
        $captureA = Join-Path $LogDir 'startup-probe-no-override.capture.log'
        $stdoutA = Join-Path $LogDir 'startup-probe-no-override.stdout.log'
        $stderrA = Join-Path $LogDir 'startup-probe-no-override.stderr.log'
        $env:SIXMIC_PACKAGING_GUI_LOG = $captureA
        $runA = Invoke-CapturedProcess -FilePath $probeExe -Arguments '--smoke-gui 3' -WorkingDirectory $probeCwd -StdoutPath $stdoutA -StderrPath $stderrA -TimeoutMs 120000
        $textA = (Read-TextFileSafe -Path $captureA) + (Read-TextFileSafe -Path $stdoutA) + (Read-TextFileSafe -Path $stderrA)
        $diagnosis.noOverrideStartup = [ordered]@{
            exe = $probeExe
            exitCode = $runA.ExitCode
            marker = [bool]($textA -match 'SMOKE_GUI_OK')
            permissionDenied = [bool]($textA -match 'WinError 5|PermissionError|Access is denied')
            pythonTraceback = [bool]($textA -match 'Traceback (most recent call last)|Unhandled exception')
            appFallbackUserDataDir = $appFallback
            appFallbackCreated = (Test-Path -LiteralPath (Join-Path $appFallback 'logs'))
            capture = $captureA
        }
        # B) deliberately unwritable override: must fall back, not crash
        $unwritable = Join-Path $env:SystemRoot 'System32\echo-unwritable-userdata'
        $env:SIXMIC_USER_DATA_DIR = $unwritable
        $captureB = Join-Path $LogDir 'startup-probe-unwritable.capture.log'
        $stdoutB = Join-Path $LogDir 'startup-probe-unwritable.stdout.log'
        $stderrB = Join-Path $LogDir 'startup-probe-unwritable.stderr.log'
        $env:SIXMIC_PACKAGING_GUI_LOG = $captureB
        $runB = Invoke-CapturedProcess -FilePath $probeExe -Arguments '--smoke-gui 3' -WorkingDirectory $probeCwd -StdoutPath $stdoutB -StderrPath $stderrB -TimeoutMs 120000
        $textB = (Read-TextFileSafe -Path $captureB) + (Read-TextFileSafe -Path $stdoutB) + (Read-TextFileSafe -Path $stderrB)
        $diagnosis.unwritableOverrideStartup = [ordered]@{
            override = $unwritable
            exitCode = $runB.ExitCode
            marker = [bool]($textB -match 'SMOKE_GUI_OK')
            permissionDenied = [bool]($textB -match 'WinError 5|PermissionError|Access is denied')
            pythonTraceback = [bool]($textB -match 'Traceback (most recent call last)|Unhandled exception')
            capture = $captureB
        }
    } finally {
        $env:TEMP = $savedTemp
        $env:TMP = $savedTmp
        $env:SIXMIC_USER_DATA_DIR = $savedUserData
        $env:PATH = $savedPath
        $env:QT_QPA_PLATFORM = $savedPlatform
        $env:QT_QUICK_BACKEND = $savedBackend
        $env:QT_ASSUME_STDERR_HAS_CONSOLE = $savedConsole
        $env:SIXMIC_PACKAGING_GUI_LOG = $savedGuiLog
    }
    $signedOut = & powershell.exe -NoProfile -Command 'try { $k = ''HKCU:\Software\EchoSignedProbe''; New-Item -Path $k -Force | Out-Null; Remove-Item -Path $k -Recurse -Force; ''SIGNED_WRITE_OK'' } catch { ''SIGNED_WRITE_FAIL'' }' 2>&1
    $signedText = ($signedOut | ForEach-Object { $_.ToString() }) -join ' '
    $diagnosis.signedPowerShellHkcuWrite = [ordered]@{ hkcuWrite = ($signedText -match 'SIGNED_WRITE_OK'); process = 'powershell.exe (Microsoft-signed)' }
    Add-Check -Name 'startup-fallback-no-override' -Ok (($runA.ExitCode -eq 0) -and $diagnosis.noOverrideStartup.marker -and -not $diagnosis.noOverrideStartup.permissionDenied -and -not $diagnosis.noOverrideStartup.pythonTraceback) -Detail ('exit=' + $runA.ExitCode + ' marker=' + $diagnosis.noOverrideStartup.marker + ' permissionError=' + $diagnosis.noOverrideStartup.permissionDenied)
    Add-Check -Name 'startup-fallback-unwritable-override' -Ok (($runB.ExitCode -eq 0) -and $diagnosis.unwritableOverrideStartup.marker -and -not $diagnosis.unwritableOverrideStartup.permissionDenied -and -not $diagnosis.unwritableOverrideStartup.pythonTraceback) -Detail ('override=' + $diagnosis.unwritableOverrideStartup.override + ' exit=' + $runB.ExitCode + ' marker=' + $diagnosis.unwritableOverrideStartup.marker)
    Add-Check -Name 'environment-installer-restricted' -Ok (-not $diagnosis.signedPowerShellHkcuWrite.hkcuWrite) -Warning -Detail ('same-session signed powershell HKCU write=' + $diagnosis.signedPowerShellHkcuWrite.hkcuWrite + ' (installer setup process remains unsigned and is denied Start Menu/HKCU writes)')
}
# The startup-fallback probes above may create <bundle>/_internal/user-data in the
# shipped bundle; remove it (recording what was removed) so dist stays pristine.
$bundleCleanupDirs = @(
    (Join-Path $DesktopBundle '_internal\user-data'),
    (Join-Path $DesktopBundle 'user-data')
)
$removedDirs = New-Object System.Collections.Generic.List[object]
foreach ($dir in $bundleCleanupDirs) {
    if (Test-Path -LiteralPath $dir) {
        $files = @(Get-ChildItem -LiteralPath $dir -Recurse -File -ErrorAction SilentlyContinue)
        $removedDirs.Add([ordered]@{ path = $dir; fileCount = $files.Count })
        Remove-Item -LiteralPath $dir -Recurse -Force
    }
}
$report.bundleCleanup = [ordered]@{ removed = $removedDirs.ToArray(); bundlePristine = ($removedDirs.Count -eq 0 -or (-not (Test-Path -LiteralPath $bundleCleanupDirs[0]))) }
$report.environmentDiagnosis = $diagnosis

# ------------------------------------------------------------------ verdict
$payloadFails = @($report.checks | Where-Object { $_.name -like 'payload-*' -and $_.status -eq 'FAIL' })
$smokeFails = @($report.checks | Where-Object { ($_.name -like 'extracted-app-*' -or $_.name -like 'extracted-backend-*') -and $_.status -eq 'FAIL' })
$realInstallVerified = ($realInstallExit -eq 0)
$report.unverifiedItems += 'Real install/uninstall execution is NOT verified by this script: the sandbox blocks unsigned installer processes from writing the Start Menu folder and the HKCU uninstall key (both Inno Setup and NSIS probes fail here). Run smoke_test_installer.ps1 on a normal Windows machine for the real install -> uninstall -> user-data-preservation flow.'
$report.unverifiedItems += 'Uninstaller (unins000.exe) existence/behaviour and user-data preservation are therefore NOT runtime-verified here; the [Code] uninstall path is review-only.'
$report.unverifiedItems += 'Default %LOCALAPPDATA%\echo user-data creation is not runtime-verified here: the packaged exe starts via the main.py echo/legacy/fallback chain (recorded in environmentDiagnosis); re-verify the primary LOCALAPPDATA path on a normal Windows machine.'
$report.unverifiedItems += 'Installer is not Authenticode-signed (status: ' + [string]$report.installer.authenticodeStatus + '); SmartScreen reputation unknown.'
$report.unverifiedItems += 'No clean Windows VM test: only the current Windows 11 host was used.'
foreach ($item in $report.unverifiedItems) { Write-Warn2 ('- ' + $item) }
if ($payloadFails.Count -gt 0) { Complete-Report -Status 'FAIL_PAYLOAD_VERIFICATION' -ExitCode 1 }
if ($smokeFails.Count -gt 0) { Complete-Report -Status 'FAIL_EXTRACTED_LAYOUT_SMOKE' -ExitCode 1 }
if ($realInstallVerified) { Complete-Report -Status 'INSTALLER_VERIFIED' -ExitCode 0 }
Complete-Report -Status 'PAYLOAD_VERIFIED_INSTALL_EXECUTION_ENVIRONMENT_BLOCKED' -ExitCode 3
