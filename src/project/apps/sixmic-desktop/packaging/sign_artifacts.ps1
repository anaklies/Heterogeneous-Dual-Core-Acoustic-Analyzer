<#
.SYNOPSIS
  Authenticode signing helper for echo release artifacts.
.DESCRIPTION
  Signs echo.exe / echo-Setup-x64.exe with a CA-issued code-signing
  certificate (PFX or certificate-store thumbprint), SHA-256 digest and an
  RFC3161 timestamp, then verifies and writes JSON evidence.
  Self-signed certificates are accepted only with -AllowSelfSignedTest; such
  signatures are NOT trusted on other PCs. Public distribution needs a real
  OV/EV code-signing certificate from a publicly trusted CA.
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File packaging/sign_artifacts.ps1 -PfxPath C:/secure/codesign.pfx -PfxPassword (Read-Host -AsSecureString)
#>
[CmdletBinding()]
param(
    [string]$PfxPath,
    [securestring]$PfxPassword,
    [string]$Thumbprint,
    [string[]]$Files,
    [string]$TimestampUrl = "http://timestamp.digicert.com",
    [string]$OutputDir = "",
    [switch]$AllowSelfSignedTest,
    [switch]$SkipTimestamp
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $Files -or $Files.Count -eq 0) {
    $Files = @(
        (Join-Path $root "dist/echo/echo.exe"),
        (Join-Path $root "dist/installer/echo-Setup-x64.exe")
    )
}
if (-not $OutputDir) { $OutputDir = Join-Path $root "dist/authenticode" }
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

function Find-SignTool {
    $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $kits = @("C:/Program Files (x86)/Windows Kits/10/bin", "C:/Program Files/Windows Kits/10/bin")
    foreach ($base in $kits) {
        if (-not (Test-Path $base)) { continue }
        $hit = Get-ChildItem $base -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -like "*/x64/signtool.exe" } |
            Sort-Object FullName -Descending | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}

$cert = $null
if ($PfxPath) {
    if (-not (Test-Path $PfxPath)) { throw "PFX not found: $PfxPath" }
    $cert = Get-PfxCertificate -FilePath $PfxPath -Password $PfxPassword
}
elseif ($Thumbprint) {
    $cert = Get-ChildItem Cert:/CurrentUser/My, Cert:/LocalMachine/My -ErrorAction SilentlyContinue |
        Where-Object { $_.Thumbprint -eq $Thumbprint } | Select-Object -First 1
    if (-not $cert) { throw "Certificate not found in store: $Thumbprint" }
}
else {
    throw "Provide -PfxPath/-PfxPassword or -Thumbprint. Without a code-signing certificate no signature is created."
}

if (-not $cert.HasPrivateKey) { throw "Certificate has no private key; cannot sign." }
$eku = $cert.EnhancedKeyUsageList | Where-Object { $_.FriendlyName -match "Code Signing" -or $_.ObjectId -eq "1.3.6.1.5.5.7.3.3" }
if (-not $eku) { throw "Certificate is not valid for code signing (missing Code Signing EKU)." }
if ($cert.NotAfter -lt (Get-Date)) { throw "Certificate expired on $($cert.NotAfter)." }
$isSelfSigned = ($cert.Subject -eq $cert.Issuer)
if ($isSelfSigned -and -not $AllowSelfSignedTest) {
    throw "Certificate is self-signed. It will NOT be trusted on other PCs; pass -AllowSelfSignedTest only for internal pipeline tests."
}

$signTool = Find-SignTool
$results = @()
foreach ($file in $Files) {
    if (-not (Test-Path $file)) { throw "File not found: $file" }
    $target = Join-Path $OutputDir (Split-Path -Leaf $file)
    Copy-Item $file $target -Force
    $ok = $false
    $method = ""
    if ($signTool) {
        $method = "signtool"
        $sarg = @("sign", "/fd", "SHA256", "/f", $PfxPath)
        if (-not $SkipTimestamp -and $TimestampUrl) { $sarg += @("/tr", $TimestampUrl, "/td", "SHA256") }
        $sarg += @($target)
        & $signTool @sarg | Out-Null
        $ok = ($LASTEXITCODE -eq 0)
    }
    else {
        $method = "Set-AuthenticodeSignature"
        $params = @{ FilePath = $target; Certificate = $cert; HashAlgorithm = "SHA256" }
        if (-not $SkipTimestamp -and $TimestampUrl) { $params.TimestampServer = $TimestampUrl }
        $sig = Set-AuthenticodeSignature @params
        $ok = ($sig.Status -eq "Valid" -or $sig.Status -eq "UnknownError")
    }
    $check = Get-AuthenticodeSignature $target
    $results += [ordered]@{
        file = $target
        size = (Get-Item $target).Length
        sha256 = (Get-FileHash $target -Algorithm SHA256).Hash.ToLowerInvariant()
        method = $method
        status = $check.Status.ToString()
        signerSubject = if ($check.SignerCertificate) { $check.SignerCertificate.Subject } else { "" }
        signerThumbprint = if ($check.SignerCertificate) { $check.SignerCertificate.Thumbprint } else { "" }
        timeStamper = if ($check.TimeStamperCertificate) { $check.TimeStamperCertificate.Subject } else { "" }
        selfSigned = $isSelfSigned
        trustedOnThisMachine = ($check.Status -eq "Valid")
        signed = $ok
    }
    Write-Output ("SIGN " + $target + " status=" + $check.Status + " selfSigned=" + $isSelfSigned)
}
$evidence = [ordered]@{
    generatedAt = (Get-Date).ToString("o")
    certificateSubject = $cert.Subject
    certificateIssuer = $cert.Issuer
    certificateThumbprint = $cert.Thumbprint
    certificateNotAfter = $cert.NotAfter.ToString("o")
    selfSigned = $isSelfSigned
    timestampUrl = if ($SkipTimestamp) { "" } else { $TimestampUrl }
    results = $results
    note = if ($isSelfSigned) {
        "TEST SIGNATURE ONLY: self-signed certificate, not trusted on other Windows PCs. Public distribution requires a CA-issued OV/EV code-signing certificate."
    } else {
        "Signed with a CA-issued certificate; verify timestamp and SmartScreen reputation separately."
    }
}
$evidence | ConvertTo-Json -Depth 6 | Set-Content -Path (Join-Path $OutputDir "signing-evidence.json") -Encoding UTF8
Write-Output ("SIGNING_EVIDENCE " + (Join-Path $OutputDir "signing-evidence.json"))
if ($results | Where-Object { -not $_.signed }) { exit 2 }
exit 0
