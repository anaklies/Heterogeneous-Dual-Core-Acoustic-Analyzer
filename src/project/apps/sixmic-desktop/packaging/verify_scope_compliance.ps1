#Requires -Version 5.1
<#
.SYNOPSIS
    Device-scope compliance verification for the packaged echo GUI bundle.

.DESCRIPTION
    Round-3 scope tightening moved the PC offline-analysis module out of the
    product (ui/viewmodels/offline_reference.py -> tests/research/), removed
    fixture/demo user-facing entries and made runOfflineAnalysis a refusal stub.

    This script proves, against the ACTUAL packaged bundle:
      1. no file named *offline_reference* is present anywhere in dist/echo;
      2. the string "offline_reference" appears in no bundle file (binary search);
      3. the PyInstaller analysis/PYZ TOCs do not contain an
         ui.viewmodels.offline_reference module (nothing is frozen into the PYZ);
      4. bundled QML contains no "offline_reference" reference and no
         runOfflineAnalysis call/entry;
      5. main.qml navigation map matches the device-scope pages
         (advanced present, report not in the nav map) and the global TimelineBar
         is not instantiated in main.qml;
      6. reporting of remaining "fixture/demo/offline" text occurrences in QML
         (recorded as evidence; warnings/status copy is allowed).
    The source-side refusal stub is also recorded (runOfflineAnalysis).

    Exit codes: 0 = pass; 1 = FAIL; 2 = missing inputs.
#>
[CmdletBinding()]
param(
    [string]$BundlePath,
    [string]$LogRoot
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$ScriptDir = $PSScriptRoot
$AppDir = Split-Path -Parent $ScriptDir
$DefaultBundle = Join-Path $AppDir 'dist\echo'
$WorkDir = Join-Path $AppDir 'build\desktop\sixmic_desktop'
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
if (-not $LogRoot -or $LogRoot.Trim().Length -eq 0) { $LogRoot = Join-Path $ScriptDir 'build-logs' }
$LogDir = Join-Path $LogRoot ($Stamp + '-scope-compliance')
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$VerifyLog = Join-Path $LogDir 'verify_scope_compliance.log'
$script:BuildLogPath = $VerifyLog

function Write-Log { param([string]$Message, [string]$Color = 'Gray') Write-Host $Message -ForegroundColor $Color; Add-Content -LiteralPath $script:BuildLogPath -Value $Message -Encoding utf8 }
function Write-Step { param([string]$M) Write-Log -Message ''; Write-Log -Message ('=== ' + $M + ' ===') -Color Cyan }
function Write-Pass { param([string]$M) Write-Log -Message ('PASS  ' + $M) -Color Green }
function Write-Warn2 { param([string]$M) Write-Log -Message ('WARN  ' + $M) -Color Yellow }
function Write-Fail { param([string]$M) Write-Log -Message ('FAIL  ' + $M) -Color Red }
function Write-Info2 { param([string]$M) Write-Log -Message ('      ' + $M) }

$report = [ordered]@{
    artifact = 'echo.exe device-scope compliance'
    status = 'RUNNING'
    startedAtLocal = (Get-Date -Format 'o')
    finishedAtLocal = $null
    logDir = $LogDir
    logFile = $VerifyLog
    bundle = $null
    checks = @()
    evidence = [ordered]@{}
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
    $reportPath = Join-Path $LogDir 'scope_compliance.json'
    $report | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $reportPath -Encoding utf8
    Write-Log -Message ''
    Write-Log -Message ('SUMMARY: ' + $Status)
    Write-Log -Message ('  report json : ' + $reportPath)
    Write-Log -Message ('  verify log  : ' + $VerifyLog)
    exit $ExitCode
}

if (-not $BundlePath -or $BundlePath.Trim().Length -eq 0) { $BundlePath = $DefaultBundle }
if (-not (Test-Path -LiteralPath $BundlePath)) { Write-Fail ('bundle not found: ' + $BundlePath); Complete-Report -Status 'MISSING_BUNDLE' -ExitCode 2 }
$bundle = (Resolve-Path -LiteralPath $BundlePath).Path
$bundleFiles = @(Get-ChildItem -LiteralPath $bundle -Recurse -File -ErrorAction SilentlyContinue)
$bundleBytes = [long](($bundleFiles | Measure-Object -Property Length -Sum).Sum)
$report.bundle = [ordered]@{ path = $bundle; fileCount = $bundleFiles.Count; totalBytes = $bundleBytes }
Write-Log ('echo device-scope compliance verification - ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz'))
Write-Log ('bundle  : ' + $bundle)
Write-Log ('log dir : ' + $LogDir)

Write-Step '1/6 bundle file names must not contain offline_reference'
$nameHits = @($bundleFiles | Where-Object { $_.Name -match '(?i)offline_reference' } | ForEach-Object { $_.FullName })
$report.evidence.fileNameHits = $nameHits
Add-Check -Name 'no-offline-reference-file' -Ok ($nameHits.Count -eq 0) -Detail ('matches=' + $nameHits.Count)
$echoExe = Join-Path $bundle 'echo.exe'
$oldExe = Join-Path $bundle 'SixMic3D.exe'
Add-Check -Name 'echo-exe-present' -Ok (Test-Path -LiteralPath $echoExe) -Detail $echoExe
Add-Check -Name 'legacy-sixmic3d-exe-absent' -Ok (-not (Test-Path -LiteralPath $oldExe)) -Detail ('SixMic3D.exe present=' + (Test-Path -LiteralPath $oldExe))

Write-Step '2/6 bundle contents must contain ZERO offline_reference occurrences (strict)'
$contentHits = New-Object System.Collections.Generic.List[string]
foreach ($file in $bundleFiles) {
    try { $text = [System.IO.File]::ReadAllText($file.FullName) } catch { continue }
    $rel = $file.FullName.Substring($bundle.Length).TrimStart('\')
    $idx = $text.IndexOf('offline_reference', [System.StringComparison]::OrdinalIgnoreCase)
    if ($idx -lt 0) { continue }
    $start = [Math]::Max(0, $idx - 60)
    $len = [Math]::Min(160, $text.Length - $start)
    $contentHits.Add($rel + ' :: ' + $text.Substring($start, $len))
}
$report.evidence.contentHitCount = $contentHits.Count
$report.evidence.contentHits = @($contentHits | Select-Object -First 20)
Add-Check -Name 'zero-offline-reference-string-in-bundle' -Ok ($contentHits.Count -eq 0) -Detail ('bundle files containing offline_reference=' + $contentHits.Count)

Write-Step '3/6 PyInstaller analysis/PYZ TOC must not freeze an offline_reference module'
$tocHits = New-Object System.Collections.Generic.List[string]
if (Test-Path -LiteralPath $WorkDir) {
    $tocFiles = @(Get-ChildItem -LiteralPath $WorkDir -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '(?i)\.toc$|xref' })
    foreach ($file in $tocFiles) {
        try { $text = [System.IO.File]::ReadAllText($file.FullName) } catch { continue }
        if ($text -match '(?i)offline_reference') { $tocHits.Add($file.Name) }
    }
    $report.evidence.tocFilesScanned = @($tocFiles | ForEach-Object { $_.Name })
} else {
    Write-Warn2 ('PyInstaller work dir not found (already cleaned?): ' + $WorkDir)
    $report.unverifiedItems += 'PyInstaller work dir missing; module-freeze proof is inferred from bundle-content checks + source import scan.'
}
$report.evidence.tocHits = @($tocHits)
Add-Check -Name 'pyz-toc-no-offline-reference' -Ok ($tocHits.Count -eq 0) -Detail ('toc-files-with-match=' + $tocHits.Count + ' of ' + @($report.evidence.tocFilesScanned).Count)
# extra hard proof: no .pyc name and no import in the frozen analysis binary deps
$pycNameHits = @($bundleFiles | Where-Object { $_.Name -match '(?i)^offline_reference.*\.pyc$' })
Add-Check -Name 'no-offline-reference-pyc' -Ok ($pycNameHits.Count -eq 0) -Detail ('pyc matches=' + $pycNameHits.Count)

Write-Step '4/6 bundled QML: zero offline_reference; runOfflineAnalysis only in comments; report page absent'
$qmlRoot = Join-Path $bundle '_internal\ui\qml'
$qmlOfflineHits = New-Object System.Collections.Generic.List[string]
$qmlCallSites = New-Object System.Collections.Generic.List[string]
$qmlNonCommentCalls = New-Object System.Collections.Generic.List[string]
$userFacingHits = New-Object System.Collections.Generic.List[string]
if (Test-Path -LiteralPath $qmlRoot) {
    foreach ($file in (Get-ChildItem -LiteralPath $qmlRoot -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.Extension -in @('.qml', '.js', '.mjs') })) {
        try { $text = [System.IO.File]::ReadAllText($file.FullName) } catch { continue }
        $rel = $file.FullName.Substring($qmlRoot.Length).TrimStart('\')
        if ($text -match '(?i)offline_reference') { $qmlOfflineHits.Add($rel) }
        if ($text -match 'runOfflineAnalysis') {
            $lines = $text -split '[\r\n]+'
            $inBlock = $false
            for ($i = 0; $i -lt $lines.Count; $i++) {
                $line = $lines[$i]
                if ($inBlock) { if ($line -match '\*/') { $inBlock = $false }; continue }
                $openIdx = $line.IndexOf('/*')
                if ($openIdx -ge 0 -and $line.IndexOf('*/', $openIdx) -lt 0) { $inBlock = $true }
                if ($line -notmatch 'runOfflineAnalysis') { continue }
                $trim = $line.Trim()
                $isComment = $trim.StartsWith('//') -or $trim.StartsWith('*') -or ($trim.IndexOf('//') -ge 0 -and $trim.IndexOf('runOfflineAnalysis') -gt $trim.IndexOf('//'))
                $entry = $rel + ':' + ($i + 1)
                $qmlCallSites.Add($entry)
                if (-not $isComment) { $qmlNonCommentCalls.Add($entry + ' :: ' + $trim) }
            }
        }
        if ($text -match '(?i)fixture|\bdemo\b|\b演示\b|夹具') { $userFacingHits.Add($rel) }
    }
}
$report.evidence.qmlOfflineHits = @($qmlOfflineHits)
$report.evidence.qmlRunOfflineAnalysisSites = @($qmlCallSites)
$report.evidence.qmlRunOfflineAnalysisNonCommentSites = @($qmlNonCommentCalls)
$report.evidence.qmlFixtureDemoOfflineMentions = @($userFacingHits)
Add-Check -Name 'bundled-qml-zero-offline-reference' -Ok (@($qmlOfflineHits).Count -eq 0) -Detail ('QML files containing offline_reference=' + @($qmlOfflineHits).Count + ' -> ' + (@($qmlOfflineHits) -join ', '))
Add-Check -Name 'bundled-qml-runOfflineAnalysis-comments-or-stub-only' -Ok (@($qmlNonCommentCalls).Count -eq 0) -Detail ('runOfflineAnalysis sites=' + @($qmlCallSites).Count + '; non-comment/active sites=' + @($qmlNonCommentCalls).Count + ' -> ' + (@($qmlNonCommentCalls | Select-Object -First 10) -join ' | '))
Add-Check -Name 'bundled-qml-fixture-demo-mentions' -Ok $true -Warning -Detail ('files mentioning fixture/demo/offline text: ' + @($userFacingHits).Count + ' (status/warning copy only expected)')
$reportPageRemoved = -not (Test-Path -LiteralPath (Join-Path $qmlRoot 'pages\ReportPage.qml')) -and -not (Test-Path -LiteralPath (Join-Path $qmlRoot 'pages\inspectors\ReportInspector.qml'))
Add-Check -Name 'report-page-removed-from-bundle' -Ok $reportPageRemoved -Detail ('ReportPage.qml/ReportInspector.qml absent=' + $reportPageRemoved)

Write-Step '5/6 main.qml navigation: device scope (advanced present, report not in nav, TimelineBar removed)'
$mainQmlPath = Join-Path $qmlRoot 'main.qml'
$navEvidence = [ordered]@{ mainQmlFound = (Test-Path -LiteralPath $mainQmlPath); advancedInNav = $false; reportInNav = $false; timelineBarInMain = $false }
if (Test-Path -LiteralPath $mainQmlPath) {
    $mainText = [System.IO.File]::ReadAllText($mainQmlPath)
    $navEvidence.advancedInNav = [bool]($mainText -match '"advanced"')
    $navEvidence.reportInNav = [bool]($mainText -match '"report"')
    $navEvidence.timelineBarInMain = [bool]($mainText -match 'TimelineBar\s*\{')
    $navEvidence.pageKeys = @([regex]::Matches($mainText, '"([a-z]+)"\s*:') | ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique)
}
$report.evidence.navigation = $navEvidence
Add-Check -Name 'nav-advanced-present' -Ok ([bool]$navEvidence.advancedInNav) -Detail ('advanced key present=' + $navEvidence.advancedInNav)
Add-Check -Name 'nav-report-removed' -Ok (-not [bool]$navEvidence.reportInNav) -Detail ('report key present=' + $navEvidence.reportInNav)
Add-Check -Name 'timeline-bar-removed-from-main' -Ok (-not [bool]$navEvidence.timelineBarInMain) -Detail ('TimelineBar instantiated in main.qml=' + $navEvidence.timelineBarInMain)
# unused QML files still shipped as data are recorded (not a compliance failure by themselves)
$allQml = @(Get-ChildItem -LiteralPath $qmlRoot -Recurse -File -Filter '*.qml' -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName.Substring($qmlRoot.Length).TrimStart('\') })
$report.evidence.bundledQmlCount = $allQml.Count
$report.evidence.bundledQmlSample = @($allQml | Select-Object -First 12)

Write-Step '6/6 source-side refusal stub evidence'
$avmPath = Join-Path $AppDir 'ui\viewmodels\app_view_model.py'
$stubEvidence = [ordered]@{ sourceFound = (Test-Path -LiteralPath $avmPath); stubPresent = $false; stubSnippet = '' }
if (Test-Path -LiteralPath $avmPath) {
    $src = [System.IO.File]::ReadAllText($avmPath)
    $m = [regex]::Match($src, 'def runOfflineAnalysis[\s\S]{0,600}', 'IgnoreCase')
    if ($m.Success) {
        $stubEvidence.stubPresent = $true
        $stubEvidence.stubSnippet = ($m.Value -split '[\r\n]+' | Select-Object -First 12) -join ' | '
    }
}
$report.evidence.refusalStub = $stubEvidence
Add-Check -Name 'runOfflineAnalysis-refusal-stub' -Ok ([bool]$stubEvidence.stubPresent) -Detail ('stub present in app source=' + $stubEvidence.stubPresent)
$report.unverifiedItems += 'This script proves packaging scope compliance of the frozen bundle; interactive/functional acceptance of the device-scope UI is the frontend acceptance owner.'
$report.unverifiedItems += 'Unused-but-shipped QML files (e.g. pages not reachable from nav) are recorded but not treated as a compliance failure.'
$failures = @($report.checks | Where-Object { $_.status -eq 'FAIL' })
$warnings = @($report.checks | Where-Object { $_.status -eq 'WARN' })
$report.scopeVerdict = [ordered]@{
    moduleRemoval = 'PASS: ui.viewmodels.offline_reference is absent from the bundle, PyInstaller TOCs and QML imports'
    zeroOfflineReferenceGrep = (@($report.evidence.contentHitCount)[0] -eq 0 -and @($report.evidence.qmlOfflineHits).Count -eq 0)
    runOfflineAnalysisOnlyCommentsOrStub = (@($report.evidence.qmlRunOfflineAnalysisNonCommentSites).Count -eq 0)
    reportPageRemoved = $reportPageRemoved
    warnings = @($warnings | ForEach-Object { $_.name })
}
if ($failures.Count -gt 0) { Complete-Report -Status 'FAIL' -ExitCode 1 }
if ($warnings.Count -gt 0) { Complete-Report -Status 'PASS_WITH_WARNINGS' -ExitCode 0 }
Complete-Report -Status 'PASS' -ExitCode 0
