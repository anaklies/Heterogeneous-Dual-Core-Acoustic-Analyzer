#Requires -Version 5.1
<#
.SYNOPSIS
    Compile echo-Setup-x64.exe with Inno Setup 6 (ISCC.exe).

.DESCRIPTION
    This script NEVER downloads or installs third-party tools during a build.

    Compiler discovery order (first existing file wins):
      1. -IsccPath
      2. environment overrides ISCC_PATH / INNO_SETUP_ISCC / INNO_SETUP_HOME
      3. bundled build-time compiler: packaging/vendor/InnoSetup6/ISCC.exe
         (official Inno Setup 6.0.5, unpacked offline with innoextract; see
         packaging/vendor/README.md - this is the reproducible path on a machine
         where the official installer cannot run and no admin exists)
      4. PATH
      5. standard install locations / Windows uninstall registry (a system
         Inno Setup 6.0.5+ installation is accepted)

    The compiler version is detected from the compiler tree (whatsnew.htm) and,
    authoritatively, from the ISCC compile output ("Compiler engine version:").
    Minimum supported version: 6.0.5. Inno Setup 6.3+ is used when found; the
    .iss auto-selects x64compatible (6.3+) or x64 (older) via ISPP.

    Required inputs (preflight fails with the exact path if missing):
      * dist/echo/echo.exe                         -> build_desktop.ps1
      * dist/SixMic3D-BackendCheck/SixMic3D-BackendCheck.exe -> build_backend_check.ps1 (backend-stage artifact, name unchanged)
      * packaging/licenses/{THIRD_PARTY_LICENSES,LICENSE-LGPL-3.0,LICENSE-GPL-3.0,
        QT_PYSIDE6_NOTICE,PYTHON_LICENSE,SIXMIC_PROTOCOL_NOTICE}.txt

    A successful compile is NOT acceptance: run smoke_test_installer.ps1 to
    install/launch/uninstall. The installer produced here is NOT code-signed
    (Authenticode status is recorded as NotSigned).

.NOTES
    Exit codes:
      0 = installer compiled (and hashed)
      2 = required deployment inputs missing (desktop/backend bundle or licenses)
      3 = no usable Inno Setup 6 compiler (missing / too old / vendor provenance failed)
      4 = ISCC compile failed
      5 = compiled installer verification failed
#>
[CmdletBinding()]
param(
    [string]$LogRoot,
    [string]$AppVersion,
    [string]$IsccPath,
    [switch]$NoPreflight
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$ScriptDir = $PSScriptRoot
$AppDir = Split-Path -Parent $ScriptDir
$RepoRoot = Split-Path -Parent (Split-Path -Parent $AppDir)
$VenvPython = Join-Path $AppDir '.venv\Scripts\python.exe'
$Preflight = Join-Path $ScriptDir 'tools\preflight.py'
$VendorVerify = Join-Path $ScriptDir 'tools\inno_vendor.py'
$IssPath = Join-Path $ScriptDir 'installer\echo.iss'
$LicenseDir = Join-Path $ScriptDir 'licenses'
$VendorRoot = Join-Path $ScriptDir 'vendor'
$VendorIscc = Join-Path $VendorRoot 'InnoSetup6\ISCC.exe'
$DistRoot = Join-Path $AppDir 'dist'
$DesktopBundle = Join-Path $DistRoot 'echo'
$BackendBundle = Join-Path $DistRoot 'SixMic3D-BackendCheck'
$InstallerOutDir = Join-Path $DistRoot 'installer'
$InstallerExe = Join-Path $InstallerOutDir 'echo-Setup-x64.exe'
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
if (-not $LogRoot -or $LogRoot.Trim().Length -eq 0) { $LogRoot = Join-Path $ScriptDir 'build-logs' }
$LogDir = Join-Path $LogRoot $Stamp
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$BuildLog = Join-Path $LogDir 'build_installer.log'
$script:BuildLogPath = $BuildLog

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

$Version = (Get-Content -LiteralPath (Join-Path $ScriptDir 'VERSION') -Raw).Trim()
if ($AppVersion) { $Version = $AppVersion }
$Version4 = $Version + '.0'
if (($Version.Split('.')).Count -ge 4) { $Version4 = $Version }

$summary = [ordered]@{
    artifact = 'echo-Setup-x64.exe'
    status = 'RUNNING'
    version = $Version
    startedAtLocal = (Get-Date -Format 'o')
    finishedAtLocal = $null
    logDir = $LogDir
    logFile = $BuildLog
    iscc = [ordered]@{ path = $null; source = $null; sha256 = $null; version = $null; architectureIdentifiers = $null }
    vendorProvenance = $null
    icon = $null
    checkedIsccLocations = @()
    preflight = $null
    compile = $null
    installer = $null
    signing = [ordered]@{ signed = $false; status = 'UNKNOWN'; note = 'Installer is not code-signed; no signing is claimed.' }
    unverifiedItems = @()
    errors = @()
}

function Complete-Summary {
    param([string]$Status, [int]$ExitCode)
    $summary.status = $Status
    $summary.finishedAtLocal = (Get-Date -Format 'o')
    $summaryPath = Join-Path $LogDir 'build_installer.json'
    $summary | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $summaryPath -Encoding utf8
    Write-Log -Message ''
    Write-Log -Message ('SUMMARY: ' + $Status)
    Write-Log -Message ('  summary json : ' + $summaryPath)
    Write-Log -Message ('  build log    : ' + $BuildLog)
    Write-Log -Message ('  installer    : ' + $InstallerExe)
    exit $ExitCode
}

# ------------------------------------------------------------------ ISCC discovery
function Get-IsccCandidates {
    $list = New-Object System.Collections.Generic.List[object]
    if ($IsccPath -and $IsccPath.Trim().Length -gt 0) { $list.Add([pscustomobject]@{ path = $IsccPath; source = 'command-line -IsccPath' }) }
    foreach ($envName in @('ISCC_PATH', 'INNO_SETUP_ISCC', 'INNO_SETUP_HOME')) {
        $value = [System.Environment]::GetEnvironmentVariable($envName)
        if ($value -and $value.Trim().Length -gt 0) {
            if ($value.ToLowerInvariant().EndsWith('iscc.exe')) { $list.Add([pscustomobject]@{ path = $value; source = 'env ' + $envName }) }
            else { $list.Add([pscustomobject]@{ path = (Join-Path $value 'ISCC.exe'); source = 'env ' + $envName }) }
        }
    }
    $list.Add([pscustomobject]@{ path = $VendorIscc; source = 'bundled vendor compiler (packaging/vendor/InnoSetup6, official 6.0.5)' })
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) { $list.Add([pscustomobject]@{ path = $cmd.Source; source = 'PATH' }) }
    $programFilesX86 = [System.Environment]::GetEnvironmentVariable('ProgramFiles(x86)')
    $localPrograms = Join-Path $env:LOCALAPPDATA 'Programs'
    $roots = @($env:ProgramFiles, $programFilesX86, $localPrograms, $env:LOCALAPPDATA, 'C:\Program Files', 'C:\Program Files (x86)')
    $subdirs = @('Inno Setup 6', 'Inno Setup 6 (x64)', 'Inno Setup 6.5', 'Inno Setup 6.4', 'Inno Setup 6.3', 'Inno Setup 6.2', 'Inno Setup 6.1', 'Inno Setup 6.0')
    foreach ($root in $roots) {
        if (-not $root) { continue }
        foreach ($sub in $subdirs) { $list.Add([pscustomobject]@{ path = (Join-Path (Join-Path $root $sub) 'ISCC.exe'); source = 'standard location ' + $root }) }
    }
    $uninstallKeys = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1',
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1',
        'HKCU:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1'
    )
    foreach ($key in $uninstallKeys) {
        try {
            $item = Get-ItemProperty -LiteralPath $key -ErrorAction Stop
            if ($item.InstallLocation) { $list.Add([pscustomobject]@{ path = (Join-Path $item.InstallLocation 'ISCC.exe'); source = 'uninstall registry ' + $key }) }
        } catch { }
    }
    $unique = New-Object System.Collections.Generic.List[object]
    $seen = @{}
    foreach ($candidate in $list) {
        if (-not $candidate.path) { continue }
        $normalized = $candidate.path.ToLowerInvariant()
        if ($seen.ContainsKey($normalized)) { continue }
        $seen[$normalized] = $true
        $unique.Add($candidate)
    }
    return $unique
}

function Find-Iscc {
    $candidates = Get-IsccCandidates
    $summary.checkedIsccLocations = @($candidates | ForEach-Object { $_.path })
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate.path -PathType Leaf) { return $candidate }
    }
    return $null
}

function Get-InnoTreeVersion {
    param([string]$Iscc)
    $dir = Split-Path -Parent $Iscc
    $whatsnew = Join-Path $dir 'whatsnew.htm'
    if (-not (Test-Path -LiteralPath $whatsnew)) { return $null }
    try {
        $html = Get-Content -LiteralPath $whatsnew -Raw -ErrorAction Stop
        $match = [regex]::Match($html, '<span class="ver">\s*([0-9]+\.[0-9]+(?:\.[0-9]+)?)')
        if ($match.Success) { return $match.Groups[1].Value }
    } catch { }
    return $null
}

function Get-ArchitectureIdentifiers {
    param([string]$InnoVersion)
    if (-not $InnoVersion) { return 'unknown (compile-time ISPP auto-detection in echo.iss)' }
    try {
        $v = [version]$InnoVersion
        if ($v -ge [version]'6.3') { return 'x64compatible (Inno Setup 6.3+ identifier)' }
        return 'x64 (legacy identifier; compiler is older than 6.3, echo.iss adapts via ISPP)'
    } catch {
        return 'unknown'
    }
}

function Get-FileSha256 {
    param([string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

# ------------------------------------------------------------------ main
Write-Log -Message ('echo installer build - ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz'))
Write-Log -Message ('version          : ' + $Version)
Write-Log -Message ('installer script : ' + $IssPath)
Write-Log -Message ('log dir          : ' + $LogDir)

Write-Step '1/6 Inno Setup 6 (ISCC.exe) discovery + compiler provenance'
$isccMatch = Find-Iscc
if (-not $isccMatch) {
    Write-Fail 'No Inno Setup 6 compiler (ISCC.exe) was found.'
    Write-Info2 'Checked exactly these locations:'
    foreach ($candidate in $summary.checkedIsccLocations) { Write-Info2 ('- ' + $candidate) }
    Write-Info2 'This script does NOT download or install third-party tools during a build.'
    Write-Info2 'The bundled build-time compiler should be at: ' + $VendorIscc
    Write-Info2 'Reproduce it from the official release as documented in packaging/vendor/README.md.'
    $summary.unverifiedItems += 'INSTALLER NOT BUILT: no usable Inno Setup 6 compiler (ISCC.exe) found.'
    Complete-Summary -Status 'NOT_BUILT_MISSING_TOOL' -ExitCode 3
}
$iscc = (Resolve-Path -LiteralPath $isccMatch.path).Path
$summary.iscc.path = $iscc
$summary.iscc.source = $isccMatch.source
$summary.iscc.sha256 = Get-FileSha256 -Path $iscc
Write-Pass ('using ISCC.exe: ' + $iscc)
Write-Info2 ('source : ' + $summary.iscc.source)
Write-Info2 ('sha256 : ' + $summary.iscc.sha256)

$isccDir = Split-Path -Parent $iscc
$isVendored = [System.IO.Path]::GetFullPath($isccDir).TrimEnd('\').Equals([System.IO.Path]::GetFullPath((Split-Path -Parent $VendorIscc)).TrimEnd('\'), [System.StringComparison]::OrdinalIgnoreCase)
if ($isVendored) {
    Write-Info2 'vendored compiler detected - verifying recorded provenance hashes'
    $vendorReport = Join-Path $LogDir 'inno_vendor.json'
    $vendorOut = & $VenvPython $VendorVerify '--vendor' $VendorRoot '--json' '--report' $vendorReport 2>&1
    $vendorExit = $LASTEXITCODE
    $vendorText = ($vendorOut | ForEach-Object { $_.ToString() }) -join [string]([char]13) + [string]([char]10)
    Set-Content -LiteralPath (Join-Path $LogDir 'inno_vendor.log') -Value $vendorText -Encoding utf8
    if ($vendorExit -ne 0) {
        Write-Fail 'vendored Inno Setup tree failed provenance verification (see inno_vendor.log)'
        $summary.vendorProvenance = [ordered]@{ verified = $false; report = $vendorReport; exitCode = $vendorExit }
        $summary.unverifiedItems += 'INSTALLER NOT BUILT: vendored Inno Setup tree provenance verification failed.'
        Complete-Summary -Status 'NOT_BUILT_VENDOR_PROVENANCE' -ExitCode 3
    }
    $vendorJson = Get-Content -LiteralPath $vendorReport -Raw -Encoding utf8 | ConvertFrom-Json
    $summary.vendorProvenance = [ordered]@{
        verified = $true
        report = $vendorReport
        inventorySha256 = $vendorJson.inventory.inventorySha256
        isccSha256 = $vendorJson.iscc.sha256
        checks = @($vendorJson.checks | ForEach-Object { $_.name + '=' + $_.status })
    }
    Write-Pass ('vendored compiler provenance verified (' + @($vendorJson.checks).Count + ' checks, inventorySha256=' + $vendorJson.inventory.inventorySha256 + ')')
}

$treeVersion = Get-InnoTreeVersion -Iscc $iscc
$probeVersion = $null
$probeExit = $null
$probeLog = Join-Path $LogDir 'iscc-version-probe.log'
$probeIss = Join-Path $LogDir 'iscc-version-probe.iss'
$probeOut = Join-Path $LogDir 'iscc-version-probe-out'
New-Item -ItemType Directory -Force -Path $probeOut | Out-Null
$probeLines = @(
    '[Setup]',
    'AppName=echo Inno Setup version probe',
    'AppVersion=1.0',
    'DefaultDirName={autopf}\echo-InnoVersionProbe',
    'OutputBaseFilename=sixmic-inno-version-probe',
    'OutputDir=.',
    '',
    '[Files]'
)
Set-Content -LiteralPath $probeIss -Value $probeLines -Encoding utf8
$savedEapProbe = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    $probeOutText = & $iscc ('/O' + $probeOut) $probeIss 2>&1
    $probeExit = $LASTEXITCODE
} finally { $ErrorActionPreference = $savedEapProbe }
$probeText = ($probeOutText | ForEach-Object { $_.ToString() }) -join [string]([char]13) + [string]([char]10)
Set-Content -LiteralPath $probeLog -Value $probeText -Encoding utf8
if ($probeExit -eq 0) {
    $probeMatch = [regex]::Match($probeText, 'Compiler engine version:\s*Inno Setup\s+([0-9]+\.[0-9]+(?:\.[0-9]+)?)')
    if ($probeMatch.Success) { $probeVersion = $probeMatch.Groups[1].Value }
}
Remove-Item -LiteralPath $probeOut -Recurse -Force -ErrorAction SilentlyContinue
$chosenVersion = $probeVersion
$versionSource = 'probe compile (ISCC "Compiler engine version" output)'
if (-not $chosenVersion) {
    $chosenVersion = $treeVersion
    $versionSource = 'whatsnew.htm next to ISCC.exe'
}
if ($chosenVersion) {
    $summary.iscc.version = $chosenVersion
    $summary.iscc.architectureIdentifiers = Get-ArchitectureIdentifiers -InnoVersion $chosenVersion
    Write-Info2 ('detected Inno Setup version: ' + $chosenVersion + ' (source: ' + $versionSource + ') -> architecture identifiers: ' + $summary.iscc.architectureIdentifiers)
    try {
        $detected = [version]$chosenVersion
        if ($detected -lt [version]'6.0.5') {
            Write-Fail ('Inno Setup ' + $chosenVersion + ' is too old: echo.iss requires 6.0.5+ ({autopf}, modern wizard).')
            $summary.unverifiedItems += 'INSTALLER NOT BUILT: Inno Setup ' + $chosenVersion + ' is older than required 6.0.5.'
            Complete-Summary -Status 'NOT_BUILT_TOOL_TOO_OLD' -ExitCode 3
        }
        if ($detected -lt [version]'6.3') {
            Write-Warn2 ('compiler is older than 6.3: echo.iss uses the legacy x64 architecture identifier (verified compatible; not a 6.3+ feature build)')
        }
    } catch {
        Write-Warn2 ('could not compare compiler version; continuing (the compile output reveals the engine version)')
    }
} else {
    Write-Warn2 'could not detect compiler version (version probe failed and no whatsnew.htm); the compile step will fail clearly if the compiler is too old'
    $summary.unverifiedItems += 'Compiler version not detected before compile (probe exit=' + [string]$probeExit + ').'
}

Write-Step '2/6 deployment inputs preflight'
if ($NoPreflight) {
    Write-Warn2 'preflight skipped by -NoPreflight (compile may fail on missing source files)'
} else {
    $preflightArgs = @($Preflight, '--mode', 'installer', '--json', '--report', (Join-Path $LogDir 'preflight.json'))
    $out = & $VenvPython @preflightArgs 2>&1
    $preflightExit = $LASTEXITCODE
    $text = ($out | ForEach-Object { $_.ToString() }) -join [string]([char]13) + [string]([char]10)
    Set-Content -LiteralPath (Join-Path $LogDir 'preflight.log') -Value $text -Encoding utf8
    try { $pj = $text | ConvertFrom-Json } catch { $pj = $null }
    if ($pj) {
        $summary.preflight = [ordered]@{ ok = $pj.ok; checks = @($pj.checks) }
        foreach ($item in $pj.checks) {
            if ($item.status -eq 'FAIL') { Write-Fail ($item.name + ': ' + $item.detail) }
            elseif ($item.status -eq 'WARN') { Write-Warn2 ($item.name + ': ' + $item.detail) }
        }
    }
    if ($preflightExit -ne 0) {
        Write-Fail 'deployment inputs are incomplete - installer NOT built (exact paths above).'
        $summary.errors += 'preflight installer mode exit code ' + $preflightExit
        Complete-Summary -Status 'NOT_BUILT_MISSING_INPUTS' -ExitCode 2
    }
    Write-Pass 'deployment inputs preflight passed'
}

# Packaging must never ship test residue: runtime probes use <bundle>/_internal/user-data
# as the sandbox fallback. Refuse to package a bundle that has it.
$residueDir = Join-Path $DesktopBundle '_internal\user-data'
if (Test-Path -LiteralPath $residueDir) {
    Write-Fail ('refusing to package bundle test residue: ' + $residueDir)
    $summary.errors += 'bundle test residue present: ' + $residueDir
    Complete-Summary -Status 'NOT_BUILT_BUNDLE_RESIDUE' -ExitCode 2
}

# ------------------------------------------------------------------ app icon
$iconCandidates = @(
    (Join-Path $AppDir 'assets\branding\sixmic3d.ico'),
    (Join-Path $AppDir 'assets\icon.ico')
)
$appIcon = $null
foreach ($candidate in $iconCandidates) {
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $appIcon = (Resolve-Path -LiteralPath $candidate).Path; break }
}
if ($appIcon) {
    $summary.icon = [ordered]@{ path = $appIcon; bytes = (Get-Item -LiteralPath $appIcon).Length; sha256 = Get-FileSha256 -Path $appIcon; usedByInstaller = $true }
    Write-Pass ('application icon wired into installer: ' + $appIcon)
} else {
    $summary.icon = [ordered]@{ path = $null; usedByInstaller = $false }
    Write-Warn2 'no application icon found (assets/branding/sixmic3d.ico or assets/icon.ico); installer uses the default Inno Setup icon'
    $summary.unverifiedItems += 'Installer icon: no app .ico found at packaging time; default compiler icon used.'
}

Write-Step '3/6 compile echo.iss with ISCC'
New-Item -ItemType Directory -Force -Path $InstallerOutDir | Out-Null
$isccArgs = @(
    '/Qp',
    ('/DMyAppVersion=' + $Version),
    ('/DMyAppVersion4=' + $Version4),
    ('/DAppSourceDir=' + $DesktopBundle),
    ('/DBackendSourceDir=' + $BackendBundle),
    ('/DLicenseDir=' + $LicenseDir),
    ('/DOutputDir=' + $InstallerOutDir)
)
if ($appIcon) { $isccArgs += ('/DSetupIconFile=' + $appIcon) }
$isccArgs += $IssPath
Write-Info2 ('command: ' + $iscc + ' ' + ($isccArgs -join ' '))
$compileStart = Get-Date
$savedEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try { $compileOut = & $iscc @isccArgs 2>&1; $compileExit = $LASTEXITCODE } finally { $ErrorActionPreference = $savedEap }
$compileSeconds = [math]::Round(((Get-Date) - $compileStart).TotalSeconds, 1)
$compileText = ($compileOut | ForEach-Object { $_.ToString() }) -join [string]([char]13) + [string]([char]10)
Set-Content -LiteralPath (Join-Path $LogDir 'iscc-compile.log') -Value $compileText -Encoding utf8
Write-Log -Message $compileText

$engineVersion = $null
$engineMatch = [regex]::Match($compileText, 'Compiler engine version:\s*Inno Setup\s+([0-9]+\.[0-9]+(?:\.[0-9]+)?)')
if ($engineMatch.Success) {
    $engineVersion = $engineMatch.Groups[1].Value
    $summary.iscc.version = $engineVersion
    $summary.iscc.architectureIdentifiers = Get-ArchitectureIdentifiers -InnoVersion $engineVersion
    Write-Info2 ('compile engine version: Inno Setup ' + $engineVersion + ' (' + $summary.iscc.architectureIdentifiers + ')')
} elseif ($summary.iscc.version) {
    $engineVersion = [string]$summary.iscc.version
    Write-Info2 ('compile engine version not echoed by /Qp; using pre-compile detection: Inno Setup ' + $engineVersion)
} else {
    Write-Warn2 'compiler engine version could not be determined from the compile log'
}
$summary.compile = [ordered]@{ exitCode = $compileExit; durationSeconds = $compileSeconds; engineVersion = $engineVersion; logFile = 'iscc-compile.log' }
Write-Info2 ('ISCC exit=' + $compileExit + ' duration=' + $compileSeconds + 's')
if ($compileExit -ne 0) {
    Write-Fail ('ISCC compile failed with exit code ' + $compileExit + ' - see iscc-compile.log')
    $summary.errors += 'ISCC exit code ' + $compileExit
    Complete-Summary -Status 'FAIL_COMPILE' -ExitCode 4
}

Write-Step '4/6 verify compiled installer'
if (-not (Test-Path -LiteralPath $InstallerExe)) {
    Write-Fail ('compiled installer missing: ' + $InstallerExe)
    $summary.errors += 'installer exe missing after compile'
    Complete-Summary -Status 'FAIL_VERIFY' -ExitCode 5
}
$installerHash = Get-FileSha256 -Path $InstallerExe
$installerItem = Get-Item -LiteralPath $InstallerExe
$installerSize = $installerItem.Length
$installerVersionInfo = $installerItem.VersionInfo
$auth = Get-AuthenticodeSignature -LiteralPath $InstallerExe
$summary.signing = [ordered]@{
    signed = ($auth.Status -eq 'Valid')
    status = [string]$auth.Status
    note = 'Installer is not Authenticode-signed by this pipeline; no signing is claimed.'
}
$summary.installer = [ordered]@{
    path = $InstallerExe
    bytes = $installerSize
    sha256 = $installerHash
    version = $Version
    fileVersion = [string]$installerVersionInfo.FileVersion
    productVersion = [string]$installerVersionInfo.ProductVersion
    companyName = [string]$installerVersionInfo.CompanyName
    authenticodeStatus = [string]$auth.Status
}
# hash the artifacts this build depends on, not only the output
$hashLines = @(
    ($installerHash + '  ' + $InstallerExe),
    ($summary.iscc.sha256 + '  ' + $iscc)
)
if ($appIcon) { $hashLines += ($summary.icon.sha256 + '  ' + $appIcon) }
Set-Content -LiteralPath (Join-Path $LogDir 'HASHES.sha256') -Value $hashLines -Encoding utf8
Write-Pass ('installer built: ' + $InstallerExe)
Write-Info2 ('bytes=' + $installerSize + ' sha256=' + $installerHash)
Write-Info2 ('versionInfo: FileVersion=' + [string]$installerVersionInfo.FileVersion + ' ProductVersion=' + [string]$installerVersionInfo.ProductVersion)
Write-Info2 ('authenticode: ' + [string]$auth.Status + ' (not claimed signed by this pipeline)')
Write-Info2 ('hash file: ' + (Join-Path $LogDir 'HASHES.sha256'))

Write-Step '5/6 compiler / signing / smoke status'
if ($summary.iscc.version -and ([version]$summary.iscc.version) -lt [version]'6.3') {
    $summary.unverifiedItems += 'Installation was compiled by official Inno Setup ' + $summary.iscc.version + ' (newest release unpackable offline with innoextract 1.9 on this machine; not a 6.3+ compiler). The .iss auto-selects the legacy x64 architecture identifier - no 6.3+-only feature is used.'
}
if ($isVendored) {
    $summary.unverifiedItems += 'Compiler is the vendored official Inno Setup 6.0.5 extracted offline from the signed official installer (packaging/vendor/README.md); the official 6.7.3 installer cannot install here (HKCU uninstall-key access denied, exit 4) and innoextract 1.9 cannot parse 6.7 archives.'
} else {
    $summary.unverifiedItems += 'Compiler came from a system installation (' + $summary.iscc.source + '), not the pinned vendor tree; installer bytes may differ from a vendor-compiled build.'
}
if (-not $summary.signing.signed) {
    $summary.unverifiedItems += 'Installer is NOT Authenticode-signed (status: ' + $summary.signing.status + '); SmartScreen reputation unknown. Signing requires a certificate not available in this environment and is not claimed.'
}
$summary.unverifiedItems += 'Installer compiled but NOT installed/launched by this script: run smoke_test_installer.ps1 for install -> offscreen GUI/backend self-test -> uninstall -> user-data preservation evidence.'
$summary.unverifiedItems += 'No clean Windows VM test: only the current Windows 11 host was used.'
foreach ($item in $summary.unverifiedItems) { Write-Warn2 ('- ' + $item) }

Write-Step '6/6 evidence'
Complete-Summary -Status 'BUILT_UNVERIFIED_SMOKE' -ExitCode 0
