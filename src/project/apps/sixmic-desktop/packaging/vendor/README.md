# Vendored build-time Inno Setup compiler (packaging/vendor/InnoSetup6)

Status: **build-time tool only, verified extracted from the official signed
release; never shipped inside the SixMic3D product or installer payload.**

This directory contains the Inno Setup 6 command-line compiler (ISCC.exe and
the compiler support files) used by `packaging/build_installer.ps1` to build
`dist/installer/SixMic3D-Setup-x64.exe`.

It exists because the official **Inno Setup 6.7.3** installer cannot install on
this machine (no admin, and its per-user install rolls back while creating the
HKCU uninstall key: `Error creating registry key ... RegCreateKeyEx failed;
code 5`, Setup exit code 4; `winget install` also fails). Rather than bypass
that or fake an installer, the build uses an **official older Inno Setup
release** whose installer can be unpacked offline with the official
`innoextract` tool - no install, no registry writes, no admin.

## What is in here

| Item | Value |
|---|---|
| Compiler | Inno Setup 6.0.5 (u) - engine version reported by ISCC: `Inno Setup 6.0.5 (u)` |
| Source installer | `innosetup-6.0.5.exe` from the **official** GitHub release `jrsoftware/issrc` tag `is-6_0_5` |
| Source URL | https://github.com/jrsoftware/issrc/releases/download/is-6_0_5/innosetup-6.0.5.exe |
| Source size | 4,218,712 bytes |
| Source SHA256 | `ae6823b523df87e9441789e51845434e4e0e70aac0b88afe80f94f20f4b98acb` |
| SHA256 cross-check | matches the GitHub release asset digest published by the GitHub API: `sha256:ae6823b523df87e9441789e51845434e4e0e70aac0b88afe80f94f20f4b98acb` |
| Authenticode | `Status=Valid`; signer `CN="Open Source Developer, Martijn Laan", O=Open Source Developer`, issuer Certum Code Signing CA SHA2; RFC3161 timestamped (Sectigo). Martijn Laan is the Inno Setup maintainer; the official release binaries are signed by him. |
| Extraction tool | innoextract 1.9 (official release, https://github.com/dscharrer/innoextract/releases/tag/1.9), `innoextract-1.9-windows.zip` sha256 `6989342c9b026a00a72a38f23b62a8e6a22cc5de69805cf47d68ac2fec993065`; the extracted `innoextract.exe` is kept under `vendor/tools/innoextract-1.9/` for audit |
| Extraction command | `innoextract --extract --output-dir apps/sixmic-desktop/packaging/vendor/InnoSetup6 innosetup-6.0.5.exe` (exit 0, output "Extracting \"Inno Setup\" - setup data version 6.0.0 (unicode)") |
| Extracted tree | 85 files, 11,143,167 bytes (includes Examples/ and Languages/) |
| Key file hashes | `ISCC.exe` `fb1eae60165f94b8604eaf2181e67a55c7f61547e3647cdbd5e30df99368338f`; `ISCmplr.dll` `b8965622bac7dab4f72ece94ee23f81869433a12fe3569aa470238d11456ec95` |
| License | `license.txt` in this directory (Inno Setup License, Jordan Russell / Martijn Laan). Redistribution in binary form is permitted provided the copyright notice is retained; this is a build tool and is NOT redistributed in the SixMic3D installer. |

## Reproduce

```powershell
# 1) download the official release asset (record hash)
#    https://github.com/jrsoftware/issrc/releases/download/is-6_0_5/innosetup-6.0.5.exe
#    expected sha256 ae6823b523df87e9441789e51845434e4e0e70aac0b88afe80f94f20f4b98acb
# 2) unpack it offline (no install, no registry)
apps/sixmic-desktop/packaging/vendor/tools/innoextract-1.9/innoextract.exe --extract --output-dir apps/sixmic-desktop/packaging/vendor/InnoSetup6 innosetup-6.0.5.exe
# 3) build the installer; build_installer.ps1 discovers this ISCC.exe
powershell -NoProfile -ExecutionPolicy Bypass -File apps/sixmic-desktop/packaging/build_installer.ps1
```

## Why 6.0.5 and not a newer 6.x

* innoextract 1.9 (the current official release, 2020) can only unpack
  installers created by Inno Setup **1.2.10 through 6.0.5**; it cannot parse
  6.7.x ("Unexpected setup loader revision: 2"). 6.0.5 is therefore the newest
  official release that can be obtained offline on this machine.
* Inno Setup **6.3+** introduced the `x64compatible` architecture identifier.
  `installer/SixMic3D.iss` therefore detects the compiler version with ISPP
  (`#if Ver >= EncodeVer(6,3,0)`) and uses `x64compatible` on 6.3+ and the
  older `x64` identifier on 6.0.x. Nothing else in the .iss needs 6.3+.
  Verified: `UninstallSilent`, `{autopf}`, `WizardStyle=modern`,
  `{param:NAME|default}`, `MinVersion=10.0`, `UninstallDisplayName` all
  compile with 6.0.5.
* The compiled `SixMic3D-Setup-x64.exe` produced by 6.0.5 is a normal Inno
  Setup per-user installer; it is **not** claimed to be built by Inno Setup 6.3+
  and no newer-version-only feature is used.

## Not claimed

* This is not an administrative/system installation of Inno Setup and no
  registry entry, PATH change or system state is created by vendoring it.
* The installer produced from this compiler is **not code-signed**; Authenticode
  / SmartScreen status is reported honestly in packaging/README.md.
