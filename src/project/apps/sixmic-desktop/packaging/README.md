# echo Windows packaging (GUI release pipeline)

Status (2026-10-26, FINAL 51-FEATURE PC WIRING BUILD: echo Windows x64, frozen marker c75dbc9d; feature_page_map (51 features -> 7 pages) + FeatureRibbon/FeaturePanel/FeatureChart + feature_codec decoding packaged on top of the feature API client and all UI work; NativeRendering still 0 in bundled QML): waterfall chart + analysis plot panel UI + pro-instrument chart textures/palette + font/clarity + full "echo" rename (artefacts, install targets, OS metadata, echo user-data policy) + device-scope compliance + round-2/4/6/7/8/9 UI + startup-crash fix):

* **Windowed GUI bundle VERIFIED** - echo.exe built from the frozen UI tree
  (uiSha256 c75dbc9d387a9eb341de1f89d97d8eab7b3820b1c7649d394c68b668b649b831),
  backend self-test PASS, offscreen GUI smoke PASS with zero QML error lines.
  Round-3 device-scope UI delivered in this bundle: PC offline-analysis module moved
  out of the app (only a refusal stub remains), external recording open refused,
  fixture/demo user-facing buttons removed, nav = 8 main pages + diagnostics/
  settings/about with new AdvancedToolsPage (periodic/directional/room), report
  page removed, global TimelineBar removed, default dark theme + Tabler outline
  nav icons, larger body/button text, page lifecycle + activateFeature/
  deactivateFeature facade. Round-2 adaptive/maximized window + F11 fullscreen,
  tinted surfaces/SVG backgrounds and Settings Apply / Restart-and-apply bar are
  retained. Readability pass (round 4) delivered: global QML font scale raised with
  minimum body 16px, Medium default font weight, higher-contrast text tokens, nav
  icons 24px/item 50px, IconButton 44px/26px icons, Icon rasterization at
  max(2, devicePixelRatio) with mipmap disabled (no blur), chart axis/legend text
  >=16px with +25% line widths, high-DPI policy PassThrough + AA_UseHighDpiPixmaps
  before QGuiApplication creation (guarded). Round 5 (font/clarity + rename):
  bundled Noto Sans CJK SC Medium (16.5 MB OTF + OFL) registered as the app font
  with DemiBold default weight; NativeRendering on QML Text for ClearType;
  nav 24px icons and body min 16-17px; quick-actions clipping fixed; product
  display name is "echo" (window/App/About + installer AppName/DisplayName +
  Start-menu labels, install dir, desktop shortcut) and the distribution artefacts
  are echo-named (echo.exe / echo-Setup-x64.exe / echo-Portable-x64-0.1.0.zip);
  BackendCheck keeps its frozen artefact name. Round 6 UI fixes: inspector content
  scrollable at any DPI/window size, Overview connection card auto-height (epoch/
  server no longer clip), LabeledValue width constrained. Interactive acceptance
  remains with the frontend owner (offscreen smoke only).
* **Device-scope compliance VERIFIED on the packaged bundle** - zero
  "offline_reference" occurrences in bundle file names AND contents; no
  ui.viewmodels.offline_reference in PyInstaller analysis/PYZ TOCs; runOfflineAnalysis
  appears only in a QML comment and as the app-side refusal stub (non-comment
  QML call sites = 0); ReportPage.qml/ReportInspector.qml are not in the bundle;
  nav has advanced and no report; TimelineBar is not instantiated. See 3.2b.
* **Startup-crash fix VERIFIED on the packaged exe** - the previously reported
  "[WinError 5] AppData\Local\SixMic3D\logs" crash is gone: with
  SIXMIC_USER_DATA_DIR unset the packaged exe starts via main.py's writable
  fallback chain (exit 0, SMOKE_GUI_OK, no PermissionError, no traceback), and a
  deliberately unwritable SIXMIC_USER_DATA_DIR also falls back cleanly. See 3.2.
* **Installer BUILT** - echo-Setup-x64.exe compiled by official Inno Setup
  6.0.5 (u); payload proven byte-identical to the verified bundles
  (desktop 584/584, BackendCheck 130/130, licenses 9/9 files).
* **Real install/uninstall execution BLOCKED BY THIS SANDBOX ENVIRONMENT** - see
  section 4. Exact setup-log evidence is recorded; this is an environment
  limitation (unsigned executables run under a restricted profile here), not a
  product defect. The full install/uninstall/user-data-preservation flow MUST be
  re-run with smoke_test_installer.ps1 on a normal Windows machine.
* **Portable ZIP (supplementary) VERIFIED** - extracted and run offscreen.
* Artifacts are **UNSIGNED** (Authenticode NotSigned). packaging/sign_artifacts.ps1
  is the signing step; a self-signed pipeline test exists ONLY under
  dist/authenticode-test (NOT for distribution, not trusted on other PCs), because
  no CA-issued code-signing certificate exists in this environment.
* NOT claimed: Authenticode signing, SmartScreen reputation, clean-VM test,
  visual/interactive GUI acceptance, interactive error-dialog rendering, real
  %LOCALAPPDATA% user-data creation (sandbox-denied; fallback verified instead),
  real install/uninstall execution on this host.

Authoritative evidence lane:
    apps/sixmic-desktop/packaging/build-logs/20261026-082156-release-evidence/

---

## 1. Deliverables (paths relative to apps/sixmic-desktop/)

| File | Purpose |
|---|---|
| dist/echo/echo.exe | windowed Qt Quick/QML product bundle (PyInstaller onedir, verified) |
| dist/installer/echo-Setup-x64.exe | per-user Inno Setup 6.0.5 installer (payload verified, execution blocked here) |
| dist/portable/echo-Portable-x64-0.1.0.zip | supplementary portable ZIP (verified by extract+run) |
| dist/SixMic3D-BackendCheck/SixMic3D-BackendCheck.exe | headless backend diagnostic (backend-stage artifact, unchanged) |
| dist/authenticode-test/ | SELF-SIGNED signing-pipeline test artifacts only - NOT for distribution, not trusted, do not ship |
| packaging/requirements-lock.txt | exact build-venv pin snapshot |
| packaging/sixmic_desktop.spec | PyInstaller onedir spec for the GUI bundle |
| packaging/sixmic_backend_check.spec | PyInstaller onedir spec for the headless diagnostic |
| packaging/build_desktop.ps1 | GUI pipeline: preflight -> UI freeze snapshot -> PyInstaller -> bundle diet -> protocol data -> bundle evidence -> offscreen smoke (self-test + GUI) -> hashes/logs |
| packaging/verify_packaged_startup.ps1 | startup-crash regression test: packaged exe with NO override, with an unwritable override, no-override self-test, static main.py guard checks |
| packaging/verify_scope_compliance.ps1 | device-scope compliance proof on the packaged bundle: zero offline_reference (names+contents+PYZ TOC+QML), runOfflineAnalysis comments/stub only, report page removed, nav/TimelineBar checks, refusal-stub evidence |
| packaging/build_installer.ps1 | finds the vendored/system ISCC.exe, verifies compiler provenance, probes the compiler version, compiles the .iss, records hashes/signing status |
| packaging/verify_installer_payload.ps1 | real install attempt + innoextract payload equality proof + extracted installed-layout smoke + startup/restriction diagnosis |
| packaging/build_portable_zip.ps1 | builds + verifies the supplementary portable ZIP |
| packaging/smoke_test_installer.ps1 | REAL install/uninstall smoke (normal Windows machine): silent install -> file/shortcut/registry checks -> backend self-test -> GUI offscreen smoke -> silent uninstall -> user-data preservation |
| packaging/sign_artifacts.ps1 | Authenticode signing helper (PFX or cert-store thumbprint, signtool/Set-AuthenticodeSignature, RFC3161 timestamp, JSON evidence; self-signed only with -AllowSelfSignedTest for pipeline tests) |
| packaging/installer/echo.iss | Inno Setup script: per-user install, Start Menu shortcuts, uninstall entry, /VERYSILENT, user data preserved on uninstall |
| packaging/vendor/InnoSetup6/ | vendored official Inno Setup 6.0.5 compiler (85 files, inventory sha 4a5cdeb4...); build-time only |
| packaging/vendor/MANIFEST.json + README.md + InnoSetup6.INVENTORY.sha256 | compiler acquisition provenance and integrity evidence |
| packaging/vendor/NSIS3/ | official portable NSIS 3.09 (evaluation only; that engine is also blocked by this sandbox; not the shipped installer) |
| packaging/vendor/tools/innoextract-1.9/ | official innoextract 1.9 (unpacks the Inno compiler; verifies installer payloads) |
| packaging/pyi/rth_gui_log.py | opt-in runtime hook: captures stdout/Qt messages of the windowed exe to a file when SIXMIC_PACKAGING_GUI_LOG is set (no effect otherwise) |
| packaging/pyi/hook-PySide6.QtQml.py | packaging hook override: disables PyInstaller's collect-every-QML-module behaviour so only imported modules ship |
| packaging/tools/ui_marker.py | reproducible UI freeze marker (the uiSha256 scheme agreed with the Lead) |
| packaging/tools/qt_qml.py | QML import scanner + selective module collector + app resource collector |
| packaging/tools/qt_runtime.py | minimal Qt 6 runtime DLL closure from PE import tables |
| packaging/tools/pyi_common.py | shared spec policy (excludes, protocol datas, Qt layout resolution, Qt6 assertion, plugin datas) |
| packaging/tools/bundle_evidence.py | bundle inventory SHA256, forbidden payload scan, Qt provenance, QML module checks |
| packaging/tools/inno_vendor.py | re-verifies the vendored Inno Setup tree hashes on every installer build |
| packaging/tools/preflight.py | environment/inputs checker (modes: backend, desktop, installer, all) |
| packaging/licenses/, pyi/version_*.txt, VERSION, build-logs/ | as before |

---

## 2. Build environment and toolchain provenance

* Python 3.12.10 in apps/sixmic-desktop/.venv; PySide6 6.12.0 (Qt 6.12.0);
  PyInstaller 6.22.3 + pyinstaller-hooks-contrib 2026.9; pytest 9.1.1 (build/test only).
  Exact pins: packaging/requirements-lock.txt (preflight verifies them).
* **Inno Setup 6.0.5 (u)** is vendored at packaging/vendor/InnoSetup6/ because the
  official 6.7.3 installer cannot install on this machine (per-user install rolls
  back with HKCU uninstall-key Access Denied / exit 4; winget also fails) and
  innoextract 1.9 cannot parse 6.7 archives. The official signed 6.0.5 installer
  asset (github jrsoftware/issrc tag is-6_0_5, sha256
  ae6823b523df87e9441789e51845434e4e0e70aac0b88afe80f94f20f4b98acb, matching the
  GitHub release digest; Authenticode Valid - Inno Setup maintainer) was unpacked
  offline with official innoextract 1.9. Provenance: packaging/vendor/README.md +
  MANIFEST.json + InnoSetup6.INVENTORY.sha256; build_installer.ps1 re-verifies it
  every build (tools/inno_vendor.py). No admin rights/system installs were used.
* Inno 6.0.5 is older than 6.3: echo.iss auto-detects the compiler with ISPP
  (Ver >= EncodeVer(6,3,0) selects x64compatible, else legacy x64), so the same
  script builds with 6.0.x and 6.3+. No 6.3+-only feature is used.
* NSIS fallback was evaluated with official portable NSIS 3.09 (vendored;
  nsis-3.09.zip sha256 f5dc52eef1f3884230520199bac6f36b82d643d86b003ce51bd24b05c6ba7c91
  matches the official checksum) but the NSIS engine is blocked by the same
  environment restriction as Inno Setup, so the shipped installer is Inno-based.

---

## 3. Final verified build (2026-10-25)

UI freeze marker actually packaged (recorded before AND after the build, unchanged):

    uiSha256 = c75dbc9d387a9eb341de1f89d97d8eab7b3820b1c7649d394c68b668b649b831
    files    = 220 (ui/**, themes/**, assets/**, main.py)
    sources-only (no __pycache__) = 8291ab94d00f96f8610cb2d2c7606d0463628cdb24ea52d07594d5323a4c69a6

### 3.1 Windowed GUI bundle - VERIFIED

Evidence lane: packaging/build-logs/20261026-081909/

    artifact : apps/sixmic-desktop/dist/echo/echo.exe
    exe size : 2,627,279 bytes
    exe sha256: 0af316487cb621f8b9f9fc46338cbc993e316a8002f97e7bd512ed6ebd3d7475
    bundle   : onedir, 595 files, 168,844,853 bytes
    inventory sha256: 478d317b04f772aedbd80ad5f6581fe049a8338d2affc19994fecfd665774e6b
    Qt6 DLLs : 24 (all byte-identical to the build venv PySide6 wheel)
    QML      : 170 module files; required modules present; forbidden QML trees absent
    forbidden-payload scan: 0 violations

Bundle diet applied after PyInstaller (recorded with reasons in build_desktop.json):
127 Qt translation catalogs (8,865,545 B), QML debug tooling plugins (1,323,480 B)
and opengl32sw.dll (20,639,544 B) are not shipped (app i18n is ui/i18n JSON;
tooling plugins are never loaded; Qt Quick uses the D3D11 RHI on Windows).
Dev-only ui/.../charts/_selftest trees, ui/tools and Python sources are not shipped as data.

### 3.2 Startup-crash fix + echo user-data policy - VERIFIED on the packaged exe

Reported by the user: packaged exe showed "Unhandled exception ... [WinError 5] ...
AppData\Local\SixMic3D\logs" and never opened. main.py runs
prepare_user_data_dir() before any component with this preference order:
explicit SIXMIC_USER_DATA_DIR -> %LOCALAPPDATA%\echo -> legacy
%LOCALAPPDATA%\SixMic3D -> <app>/user-data -> %TEMP%/echo -> cwd/echo-user-data ->
~/echo (each candidate probe-written; first writable wins and is exported as
SIXMIC_USER_DATA_DIR). When the preferred echo directory is chosen and legacy
%LOCALAPPDATA%\SixMic3D data exists, a one-time best-effort copy is performed
(legacy directory never deleted). AppViewModel init failures become APP_INIT_FAILED;
the run_gui/__main__ guard writes %TEMP%/echo-crash.log and shows an echo-titled
QMessageBox, return code 4.

Evidence lane: packaging/build-logs/20261026-082010-startup-robustness/

    A. --smoke-gui 3 with SIXMIC_USER_DATA_DIR UNSET (reported-crash scenario):
         exit 0, marker SMOKE_GUI_OK, QML errors 0,
         permissionError=false, pythonTraceback=false
         real-profile fallback chosen: <bundle>/_internal/user-data (proven by the
         created logs/data/evidence/ui subdirs; removed again afterwards so the
         shipped bundle stays pristine - verified 584 files, no user-data residue)
    B. --smoke-gui 3 with an UNWRITABLE SIXMIC_USER_DATA_DIR
       (C:\WINDOWS\System32\echo-unwritable-userdata):
         exit 0, marker SMOKE_GUI_OK, permissionError=false -> falls back cleanly
    C. --self-test with NO override: exit 0, captured last line SELF-TEST PASS
    D. echo user-data selection: with a redirected writable %LOCALAPPDATA%,
       --smoke-gui 2 creates %LOCALAPPDATA%\echo with all 9 user-data subdirs,
         legacy %LOCALAPPDATA%\SixMic3D is NOT used
    E. legacy migration: redirect-localappdata + seeded legacy SixMic3D marker file,
       --smoke-gui 2 -> the marker is copied into %LOCALAPPDATA%\echo and the
         legacy directory is preserved
    F. static guards present: prepare_user_data_dir, echo + legacy + app/temp
       candidates, copytree migration, exported SIXMIC_USER_DATA_DIR,
       APP_INIT_FAILED, echo-crash.log, echo-startup-error.log, echo dialog title,
       show_startup_error QMessageBox guard, return code 4

Not force-tested: the interactive QMessageBox rendering (it only triggers when all
data-dir candidates are unwritable; code-verified instead). The real user-profile
%LOCALAPPDATA%\echo creation remains sandbox-denied for unsigned exes; selection and
migration are therefore exercised with a redirected writable %LOCALAPPDATA% and the
fallback chain on the real profile.

### 3.2b Device-scope compliance - VERIFIED on the packaged bundle

Evidence lane: packaging/build-logs/20261026-082007-scope-compliance/
(report: scope_compliance.json, status PASS_WITH_WARNINGS)

After the Lead purged the residual offline entries (ReportPage/ReportInspector
removed, 11 active runOfflineAnalysis buttons deleted, provenance labels moved to
source.none, obsolete i18n keys deleted), the packaged bundle is verified:

    zero "offline_reference" occurrences in bundle file NAMES and CONTENTS
      (587 files scanned, plus PyInstaller analysis/PYZ TOCs: 0 hits)
    no ui.viewmodels.offline_reference module frozen in the PYZ; no offline_reference pyc
    bundled QML: 0 offline_reference occurrences; runOfflineAnalysis sites = 0
      (final user UI removed even the previous comment); app-side stub is a refusal
    ReportPage.qml / ReportInspector.qml absent from the bundle; report not in nav
    nav "advanced" present; TimelineBar not instantiated in main.qml
    advisory (NOT offline entries): SourceBadge.qml has color mappings for
      sourceKind offline-reference/test-fixture; DiagnosticsPage shows a backend
      fixture-status row; OverviewPage has one visible:false dead button label;
      components/charts/ChartGallery.qml is a dev-only demo gallery shipped as
      unreferenced QML data (not reachable from nav).

### 3.2c Readability + font/clarity passes (rounds 4-5) - packaged and smoke-verified

The final frozen marker c75dbc9d... carries the round-4..17 UI work plus the
round-5 font/clarity pass on top of the device-scope-compliant tree:

    global QML font scale raised again; minimum body text 16px
    window default font weight Medium; higher-contrast text tokens
    nav icons 24px and nav item height 50px; IconButton 44px with 26px icons
    Icon rasterizes at max(2, devicePixelRatio) with mipmap disabled (no blur)
    all chart axis/legend text >=16px; chart line widths +25%
    high-DPI policy PassThrough + AA_UseHighDpiPixmaps set before
      QGuiApplication creation (guarded so an existing application instance /
      test harness is unaffected)
    round-5: bundled + registered Noto Sans CJK SC Medium
      (assets/fonts/NotoSansCJKsc-Medium.otf 16,523,632 B, sha256
      ca094f6b0001fb048ca39ddd797a0cdb0179e1e55c6561e111c49c3e6a61d7b7, OFL.txt
      shipped in the same folder) as the application font; default weight
      DemiBold; NativeRendering on all QML Text for ClearType sharpness;
      nav 24px icons, body minimum 16-17px; quick-actions clipping fixed
      (panel heights 244/118, AppButton 40/46px, font 17). Bundle grows
      ~+16.5 MB to 168,350,097 bytes; the font and its OFL license ship inside
      _internal/assets/fonts/ and are covered by the bundle evidence.

Verification here: the packaged windowed exe loads the QML UI offscreen with 0
QML errors (self-test PASS, SMOKE_GUI_OK with and without a user-data override),
and the high-DPI policy does not break headless startup. Real display scaling /
visual readability acceptance (frontend screenshots: 1920x1080 dark zh, 1280
small window, en; 13 shots) remains with the frontend acceptance owner and is
not claimed by packaging.

### 3.2d FULL "echo" rename (final round) - artifacts, install targets, OS metadata

The user requires the entire application to be named **echo**; the final rebuild
(final marker c75dbc9d) renames every distribution artefact and install target:

    GUI executable      : dist/echo/echo.exe
    installer           : dist/installer/echo-Setup-x64.exe
    portable ZIP        : dist/portable/echo-Portable-x64-0.1.0.zip
    install directory   : %LOCALAPPDATA%\Programs\echo
    Start Menu group    : echo (shortcut label echo; backend diagnostic shortcut
                          "echo\Backend diagnostics (self-test)")
    desktop shortcut    : echo
    user data directory : %LOCALAPPDATA%\echo preferred; legacy
                          %LOCALAPPDATA%\SixMic3D auto-migrated (copy, legacy kept)
    BackendCheck        : BackendCheck\SixMic3D-BackendCheck.exe (backend-stage
                          frozen artefact name intentionally unchanged)

Frozen metadata now verified from the binaries: echo.exe ProductName=echo,
InternalName=echo, OriginalFilename=echo.exe, CompanyName=echo, FileDescription=
"echo acoustic analysis workstation (Qt Quick desktop application)"; installer
ProductName=echo, CompanyName=echo project. Inno script is packaging/installer/echo.iss
with AppName=echo, DefaultDirName={autopf}\echo, DefaultGroupName=echo,
UninstallDisplayName=echo and the echo desktop icon. main.py owns the OS-level
application names (setApplicationName/DisplayName/OrganizationName = echo) and the
QML window title is "echo".

Packaging refuses to compile an installer or build a portable ZIP when the GUI
bundle contains test residue (<bundle>/_internal/user-data); the bundle is verified
pristine (584 files) before packaging.



### 3.2e Pro-instrument chart palette + textures + user waterfall UI + compact bars (rounds 7-10) - packaged, chart evidence refreshed

Frozen markers 332756d0..c75dbc9d add the professional instrument look, the final user waterfall UI, the compact histogram bars, the clarity/fullscreen/font pass, the final UI scale, the hover previews, the scale settings, the feature API integration and the 51-feature PC wiring (visual/UI and PC-client changes only; no backend change):

    six-channel palette: #4FC3F7 cyan, #FFD166 amber, #FF5CA8 magenta,
      #4ADE80 green, #FB923C orange, #C4B5FD lilac (themes/tokens.py CHANNEL_COLORS)
    instrument plot surface #0A0E14 with clearer major/minor grid hierarchy
      (#3E4E60 / #202C38), brighter axis/text (#E9F1F9 / #A4B6C9), cursor A amber /
      B green, bluer panel chrome (#16212E on #0D1420, border #2C3D50)
    final chart textures (round 8): octave/third-octave bars are vertical gradients
      (deep color -> saturated -> bright top) with a thin light outline and denser
      bar spacing 0.84/0.78 (BarChart.qml); level meters use gradient fills
      (dark -> channel color -> bright peak edge) with the existing peak/Clip
      markers (LevelMeter.qml)
    final compact bars (round 10): BarChart.qml compact histogram bar widths are
      0.98 of the band in both log-centre and categorical modes; inter-band
      separator lines removed; existing viridis level gradient
      (purple->blue->green->yellow) retained; chart_octave_bars.png refreshed
    chart gallery regenerated with 7 chart types + light/dark/provider previews

The FINAL user UI (round 9, carried into c75dbc9d) adds WaterfallChart.qml +
AnalysisPlotPanel.qml + PlotWorkbenchPage.qml (7 chart types in the gallery now,
incl. galleryWaterfall; bundle 587 files). ALL chart evidence copies were
refreshed in docs/frontend/screenshots/ (gallery/waterfall from the frozen tree
renders, per-chart PNGs from the final docs capture set; 13 files total):

    charts_gallery_dark.png     bytes=611537 sha256=55709fd5ed555ba2a6aad32e6181dd507d9f7703377a014514421c25f3ab1b73
    charts_gallery_light.png    bytes=618016 sha256=34a196a9c7571788200df6947745ae286d098778ca99d24494922f0a65914926
    charts_gallery_provider.png bytes=617959 sha256=a310a14f8ed8605471451b3b91817a91bac1e6fcc35a25014a87217f6d4c2bbd
    chart_fft_psd.png           bytes=33980  sha256=775ed242f1862c6551cbe66e4897ec73278688164e9d059d05651e55ebbef535
    chart_level_meters.png      bytes=23865  sha256=f2142b45fe4bf52a7ba44c54d1d21d0c4ef6a109c4e8a47ba34b0345fa380197
    chart_octave_bars.png       bytes=18066  sha256=e91d3ddfd2075cb07b960921ea6adb7bf1bd08bf616af31951d43419b1d42852
    chart_polar_spatial.png     bytes=57185  sha256=ec6ee44f3e96a579a273044ff167c243fa7b5c5042efb8d82564c8af97126b80
    chart_stft_heatmap.png      bytes=131085 sha256=10c25f0fb2249c2450d7e38d9b66cce7dba298d36606cd573799b9000ff8e49e
    chart_timeline.png          bytes=10016  sha256=56a9bf289000ae31643174108c2dd301633cda467b368574f3ed6d3d2b425d64
    chart_waterfall.png         bytes=189659 sha256=de209d44d226cec33a4dea7e8772d43087a2396b6facd07c3b394dfdafe6b310
    chart_waterfall_dark.png    bytes=190784 sha256=c69b7f00a45f0fb1cab659910f99da056f9f3c6beeba37410e82ff6688951aa6
    chart_waterfall_light.png   bytes=193481 sha256=4a90117866419269ae6f9c4e05bab1458feb2f6981bd34bdf9fc1b1b55ab9fab
    chart_waveform.png          bytes=118024 sha256=0fa19bb97c393972b6ab5b914521848936b9b6329daa5c0cba0a5db1b69b93ac

The packaged GUI loads with 0 QML errors; real-display chart rendering/sharpness
and interactive visual acceptance remain with the frontend acceptance owner.
All 13 chart hashes are also listed in the release-evidence lane HASHES.sha256.

### 3.2f Protocol ports + PC-side mock data path - VERIFIED (and what is NOT wired)

Protocol port constants (checked in source):
    backend/sixmic_backend/constants.py: DEFAULT_CONTROL_PORT = 48120,
      DEFAULT_BINARY_PORT = 48121, LEGACY_TAKEOVER_PORT = 48110
      ("old service; must never be reused")
    model/dto.py: control_port default 48120, binary_port default 48121
    qt/adapter.py: connectDevice(controlPort=48120, binaryPort=48121) defaults
    data/config_store.py rejects legacy with reason "legacy-48110-must-not-be-reused"
    ui/viewmodels/app_view_model.py: settings defaults 48120/48121 and validation
      rejects value == 48110

Fresh mock-session run on this build (harness backend/sixmic_backend/testing/
mock_ps_server.py; evidence JSON copied into the release-evidence lane as
protocolMockDataPath-mock_data_path_evidence.json):
    3/3 result frames received (sourceKind test-fixture, sampleRate 48009.7734375)
    146 PCM chunks received in the bounded 3 s stream window (target 142; the
      mock stream is time-bounded, not chunk-capped, so the check enforces >=142)
    startJob(p2OneShot) accepted (jobId job-000001), duplicate-tolerant,
      final state completed (result=null, error=null)
    capabilities: livePcm=not_ready, liveResults=not_ready, eventCapture=not_ready
    feature catalog: available=0 of 52 (42 experimental, 9 not_ready, 1 unsupported)
    service results: unavailable (no per-feature service result received)
    control jobs allowed by the frozen backend: p1Carousel, p2OneShot only

HONEST CONCLUSION: PL feature/task routes are NOT wired in the frozen backend.
startJob is accepted generically, but there is no per-feature PL result service, so
PC software cannot yet receive real PL analysis results; only base telemetry/PCM/
events are receivable via protocol v1 (mock-verified here).

### 3.2g ACCEPTANCE foundation - clarity/fullscreen/font round (12): NativeRendering fully removed

Frozen marker 2a2acdc3 (NativeRendering removal foundation, carried into the final 51-feature marker c75dbc9d; 245 files; bundle 595 files / 168,844,853 B, +33.4 MB vs
the compact-bar build). Packaging verified in the packaged bundle:
    bundled QML Text.NativeRendering occurrences = 0 across 67 QML files
      (this was the one deviation in the previous marker 7a6a4c61; the Lead
      unfroze the UI and removed all 140 remaining occurrences; the acceptance
      build contains none)
    three real Noto Sans CJK SC weights bundled + registered: Regular 16,437,364 B
      sha256 2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b,
      Medium 16,523,632 B ca094f6b..., Bold 17,002,248 B b5f0d1a1... (+ OFL
      dab7fb4c...); main.py registers sorted NotoSansCJKsc-*.otf and sets the
      window/app font to family 11 Medium (real weights, no synthetic blur)
    DPI rounding policy PassThrough -> RoundPreferFloor (main.py, guarded before
      QGuiApplication) together with AA_UseHighDpiPixmaps
    fullscreen button in the top toolbar (AppToolBar.qml maximize-2 icon toggling
      Window.FullScreen <-> Window.Maximized, tooltip 全屏/退出全屏; F11 also works)
    deep instrument blue accent #2F7BEA (accentPressed #1F63CC, accentSoft
      #1E3552); chromeBg #101722 instead of pure black
    channel visibility chips fixed (Flow single row, chip height 38, panel
      auto-height)
    page screenshots regenerated on the acceptance tree: capture_manifest has 13
      shots at 2560x1440 native (the small-window shot is captured on the same
      2560x1440 canvas because the frozen capture tool's resize is overridden by
      the QML width binding - documented, not silently altered)
    chart gallery + waterfall renders regenerated on the acceptance tree; the 8
      per-chart PNGs remain unchanged prior-round crops (documented)
    artifacts: echo.exe 2,627,279 B / echo-Setup-x64.exe 73,631,373 B /
      echo-Portable-x64-0.1.0.zip 98,224,614 B (inventorySha256 478d317b...);
      startup/self-test/smoke/payload/portable/scope verification all green;
      NotSigned; real install/uninstall still environment-blocked.

### 3.2h FINAL UI SCALE round (13) - font scale +12% / min 18px, larger controls, regenerated screenshots

Frozen marker c4e8c89f (UI-scale foundation, carried into the final 51-feature marker c75dbc9d; 245 files; bundle 595 files / 168,844,853 B; artifacts:
echo.exe 2,627,279 B, echo-Setup-x64.exe 73,631,373 B, echo-Portable ZIP 98,224,614 B;
inventorySha256 478d317b...) is the final UI-scale foundation. Packaging verified:

    global QML font scale +12% with 18px minimum (QML pixelSize 18-21 for
      body/status/labels; 20-27 for headers/titles; chart axis header text 18)
    IconButton iconSize 32 in a 52x52 hit area; nav rail 252px wide with 28px
      icons and 58px items; InspectorPanel 340px + 38px tabs
    AppButton 48/56px; ChoiceChips 34/40px; channel chips 46px
    AppToolBar 66px; StatusBar 46px; Overview connection card +40 auto padding;
      fixed card heights raised +15% (60-400 range) to stop clipping when scaled
    NativeRendering gate still green: 0 Text.NativeRendering occurrences across
      67 bundled QML files
    page screenshots regenerated on this tree by the frontend capture pipeline:
      capture_manifest 2026-10-25T16:02:44+0800, 13 shots (12 at 2560x1440 +
      1 small-window 1280x800); all 13 hashes recorded in the acceptance/scale lane
    chart gallery + waterfall renders regenerated on this tree (chart axis min
      18px); 8 per-chart PNGs remain unchanged prior-round crops (documented)
    startup/self-test/smoke/payload/portable/scope checks green; NotSigned;
      real install/uninstall still environment-blocked.

### 3.2i FINAL HOVER-PREVIEW round (14) - chart/table hover readouts

Frozen marker aea4b862 (hover foundation, carried into the final 51-feature marker c75dbc9d; 245 files; bundle 595 files / 168,844,853 B) adds the final
hover-preview feature (visual/interaction only; no data/logic change). Packaging
verified the hover code is present in the packaged bundle:

    LineChart.qml (FFT/PSD etc): hoverEnabled MouseArea, hoverTextAt(x) nearest-point
      readout, floating panel showing nearest x + per-series value/unit
    BarChart.qml: hoverTextAt + overlay Rectangle z=200 with Theme.panelBg and
      Theme.accent border, clamped on-screen (band label + value/unit)
    LabeledValue.qml / StatTile.qml: HoverHandler + ToolTip with
      label = value (StatTile adds unit)
    hover overlays are hidden at rest: the regenerated chart gallery/waterfall
      renders are byte-identical to the UI-scale round, and the 13 page screenshots
      are unchanged (verified by re-hash on this tree)

Artifacts: echo.exe 2,627,279 B / echo-Setup-x64.exe 73,631,373 B /
echo-Portable-x64-0.1.0.zip 98,224,614 B; inventorySha256 478d317b...; startup/
self-test/smoke/payload (589/589)/portable/scope green; NativeRendering gate still
0 occurrences across 67 bundled QML files; NotSigned; real install/uninstall still
environment-blocked.

### 3.2j FINAL SCALE-SETTINGS round (15) - user UI scale + font-size scale settings

Frozen marker 7ab2aae0 (scale-settings foundation, carried into the final 51-feature marker c75dbc9d; 245 files; bundle 595 files / 168,844,853 B). Packaging
verified in the packaged bundle:

    Settings > 通用 has 界面缩放 (uiScale, 0.8-1.5, applied at next launch) and
      字号缩放 (fontScale, 0.85-1.10, live via Theme.fontScale); the bottom bar
      always shows 应用设置 (settings.apply) + 应用并重启 (settings.restart_apply),
      with settings.scale_hint text; Restart-and-apply uses QProcess relaunch
    main.py apply_saved_ui_scale(): reads <user-data>/ui/ui_settings.json uiScale
      BEFORE QGuiApplication, respects an existing QT_SCALE_FACTOR and
      SIXMIC_DISABLE_UI_SCALE, clamps 0.75..1.6, sets QT_SCALE_FACTOR; DPI rounding
      policy remains RoundPreferFloor
    all QML font.pixelSize values multiply Theme.fontScale; control heights scale
      (AppButton round((48/56)*fontScale), ChoiceChips round((34/40)*fontScale)) and
      inspector width round(340*fontScale); StatusBar fixed compact 44px/15px;
      fonts capped at 1.10 to guarantee no clipping; default scale stays 1.0
    NativeRendering gate still 0 occurrences across 67 bundled QML files

Packaged scale probes (offscreen runs of the packaged echo.exe --smoke-gui 2 with
seeded user-data settings; results copied into the release lane):
    fontScale 1.10 -> exit 0, SMOKE_GUI_OK
    fontScale 0.85 -> exit 0, SMOKE_GUI_OK
    uiScale 1.25   -> exit 0, SMOKE_GUI_OK
    uiScale 0.80   -> exit 0, SMOKE_GUI_OK
(visual clipping acceptance at 1.10 is frontend-owned; the frontend also ran a
separate fontScale=1.10 clipping capture)

Artifacts: echo.exe 2,627,279 B / echo-Setup-x64.exe 73,631,373 B /
echo-Portable-x64-0.1.0.zip 98,224,614 B; inventorySha256 478d317b...; payload
589/589; startup/self-test/smoke/portable/scope green; NotSigned; real install/
uninstall still environment-blocked. Page screenshots (13) captured at saved
fontScale=1.0; chart renders unchanged (default fontScale 1.0).

### 3.2k FINAL FEATURE-API INTEGRATION round (16) - pc_client + Feature Workbench

Frozen marker 4becaaa0 (foundation carried into the final 51-feature marker c75dbc9d; 245 files; bundle 595 files / 168,844,853 B, +4 files:
FeatureWorkbenchPage.qml and ui/config/feature_calls.json). Packaging verified:

    apps/sixmic-desktop/pc_client/ (additive PC-side client, no second socket):
      client.py, qt_bridge.py (FeatureBackendBridge extends BackendBridge),
      transport.py, __init__.py, test_client.py, HANDOFF.md
    main.py imports pc_client.qt_bridge.FeatureBackendBridge and instantiates it
      (bridge = FeatureBackendBridge(protocol_root=...); backend adapter only as an
      import fallback), so the packaged app uses the feature-aware bridge
    AppViewModel exposes featureApi + listFeatures/startSelectedFeature/
      stopActiveFeature/refreshFeatureJob/fetchFeatureResult/
      releaseFeatureResult/saveFeatureResult
    Advanced Tools -> Feature Workbench page (51 feature calls from
      ui/config/feature_calls.json generated from 51_FEATURE_CALLS.csv):
      catalog, JSON params, start/stop/state/result/release/export
    docs: FEATURE_API_INTEGRATION.md + updated DEVICE_FEATURE_CALL_MATRIX.csv
      (PC client implemented; device gateway deployment pending)

Packaging proof that the frozen exe really contains the client (not a silent
fallback): the embedded PYZ.pyz in dist/echo/echo.exe was extracted and inspected -
it contains modules pc_client, pc_client.client, pc_client.qt_bridge,
pc_client.transport, and the pc_client.qt_bridge code object contains the
FeatureBackendBridge class constant; PyInstaller PYZ-00.toc/Analysis TOC/xref also
list the pc_client modules. The bundled data contains
_internal/ui/qml/pages/FeatureWorkbenchPage.qml and
_internal/ui/config/feature_calls.json (51 features). Reference pc_client tests:
8 passed (pytest pc_client/test_client.py with backend on PYTHONPATH).

Device-side gateway/registry deployment and real network feature.* acceptance are
pending (the workbench page shows "feature API not enabled" until the device
gateway exists); the base frozen backend still has no PL task routes
(only p1Carousel/p2OneShot; base telemetry/PCM/events via protocol v1).

Artifacts: echo.exe 2,627,279 B / echo-Setup-x64.exe 73,631,373 B /
echo-Portable-x64-0.1.0.zip 98,224,614 B; inventorySha256 478d317b...; payload
591/591; startup/self-test/smoke/portable/scope green; NativeRendering gate 0/67
bundled QML files; NotSigned; real install/uninstall still environment-blocked.

### 3.2l FINAL 51-FEATURE PC WIRING round (17) - page map, ribbon, panel, chart, codec

Frozen marker c75dbc9d (245 files; bundle 595 files / 168,844,853 B, +4 files:
FeatureRibbon.qml, FeaturePanel.qml, FeatureChart.qml, ui/config/feature_page_map.json).
Packaging verified in the packaged bundle:

    ui/config/feature_page_map.json (version echo-features-1, 7 pages, 51 features,
      260,559 B) bundled; every feature has a unique page entry
    FeatureRibbon (icon + short name -> real feature API) hosted in main.qml;
      FeaturePanel drawer (params JSON, start/stop/refresh/fetch/release/export)
      hosted in main.qml; FeatureChart inside the panel binds App.featureChart and
      renders line/waveform/bars/raw through the existing chart components
    ui/viewmodels/feature_codec.py frozen into the PYZ (module ui.viewmodels.feature_codec):
      server layout precedence actualProducerLayout > producerLayout > schema.layout,
      mixed uint32/float32/PCM24 decoding, no DSP, missing layout -> explicit
      unavailable (never guessed); AppViewModel exposes featureRibbon/featureChart/
      openFeature/closeFeaturePanel and decodes full result words
    pc_client FeatureClient/FeatureBackendBridge still frozen (PYZ contains
      pc_client, pc_client.client, pc_client.qt_bridge, pc_client.transport;
      FeatureBackendBridge class constant present)
    frontend tests: 5 codec tests passed (frontend suite 39 passed per Lead);
      GUI smoke 0 QML errors; NativeRendering gate 0 occurrences across 71 bundled
      QML files

Artifacts: echo.exe 2,627,279 B / echo-Setup-x64.exe 73,631,373 B /
echo-Portable-x64-0.1.0.zip 98,224,614 B; inventorySha256 478d317b...; installer
payload 595/595; 14 page screenshots (new 03b_spectrum_feature_panel) at
2560x1440; chart renders unchanged. Device-side gateway/registry deployment and
real network feature.* acceptance remain pending (workbench/ribbon show "feature
API not enabled" until the device gateway exists).

### 3.3 Installer - BUILT (Inno Setup 6.0.5), payload verified

Evidence lanes: packaging/build-logs/20261026-082024/ (compile) and
packaging/build-logs/20261026-082106-installer-payload/ (payload verification).

    artifact : apps/sixmic-desktop/dist/installer/echo-Setup-x64.exe
    size     : 73,631,373 bytes
    sha256   : f4b5ad33be49693e8e45d203c66aa61eaa22a5d489439d017f9917ab6015a7d2
    compiler : official Inno Setup 6.0.5 (u) - vendored, provenance-verified
               (ISCC.exe sha256 fb1eae60165f94b8604eaf2181e67a55c7f61547e3647cdbd5e30df99368338f)
    file version: 0.1.0.0 (packaging/VERSION 0.1.0; in-app version string is 1.0.0-rc1)
    Authenticode: NotSigned (this pipeline does not sign and no signing is claimed)

Installer payload proof (innoextract 1.9, official tool):

    desktop bundle : 584/584 files byte-identical (manifest sha a616836d9273d78789300ea4dd69d07ea44af7f80c24e82fc051e9a8688bacab)
    BackendCheck   : 130/130 files byte-identical
    licenses       : 9/9 files byte-identical
    extracted installed-layout smoke: self-test PASS, offscreen GUI exit 0
    (SMOKE_GUI_OK, zero QML errors), BackendCheck self-test PASS
    startup probes on the packaged exe: no-override exit 0 (fallback),
    unwritable-override exit 0 -> no startup crash

### 3.4 Portable ZIP - VERIFIED (supplementary deliverable)

Evidence lane: packaging/build-logs/20261026-082053-portable/

    artifact : apps/sixmic-desktop/dist/portable/echo-Portable-x64-0.1.0.zip
    size     : 98,224,614 bytes
    sha256   : d1153150535dc665ba95389250eeffb058eed1aaaa1fc953c27eacb7aac02c1d
    contents : echo/ (584-file GUI bundle), BackendCheck/ (130 files),
               licenses/ (9 files), README-PORTABLE.txt
    verified : extracted then run: self-test PASS, offscreen GUI exit 0
               (SMOKE_GUI_OK, no QML errors), BackendCheck self-test PASS

### 3.5 Backend diagnostic (backend-stage artifact, unchanged)

    dist/SixMic3D-BackendCheck/SixMic3D-BackendCheck.exe
    exe sha256 30a7247a7a6ac36e3625a8f92c18cdf6de5ea8b32cf7d53c40442144887a310e
    self-test: exit 0, 11/11 checks, final line SELF-TEST PASS (lane 20261024-152305)
    Frozen backend marker: backendSha256=e84469e2faa5b145262b7c8dd7e4da6b2cf57d9f18fbc34949f8dd0f33fbd58c

---

## 4. Environment limitation: installer EXECUTION is blocked on this host

This is the single open item and an environment property, not a product defect.
Exact evidence:

1. Real silent install of the compiled installer to a throw-away workspace dir:
   setup exit code 4. Setup log blocking lines (verbatim):

       IPersistFile::Save failed; code 0x80070005.
       Setup was unable to create the directory
         "C:\Users\sunxi\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\echo".
       Error 5: access denied.
       RegCreateKeyEx failed; code 5. (HKCU ...\Uninstall\{7C1E5A2B-...}_is1)

2. Reproduced with a minimal official-Inno probe installer (one file + two Start
   Menu shortcuts), with the official Inno Setup 6.7.3 installer itself, and with
   portable NSIS 3.09 probe installers.
3. Root cause: this sandbox runs unsigned executables under a restricted profile
   (Start Menu / HKCU / user-profile writes are denied; the packaged GUI used to
   crash on %LOCALAPPDATA% because of it). Microsoft-signed powershell can write
   the same locations, so only installer-stub processes are blocked.
4. Since the main.py fix, the PRODUCT no longer crashes on that restriction (3.2).
   The INSTALLER process is still blocked, so real install/uninstall remains
   unverified here. What IS verified instead: compiled installer payload is
   byte-identical to the verified bundles and the extracted installed layout runs.

To close this item, on a normal Windows 11 machine / clean VM run:

    powershell -NoProfile -ExecutionPolicy Bypass -File apps/sixmic-desktop/packaging/smoke_test_installer.ps1

---

## 5. Reproduce (from the repo root C:/Users/sunxi/Desktop/sixmic3D)

    # 0) environment/inputs (venv python, no external installs)
    apps/sixmic-desktop/.venv/Scripts/python.exe apps/sixmic-desktop/packaging/tools/preflight.py --mode desktop

    # 1) GUI bundle + offscreen smoke + hashes + UI freeze marker
    powershell -NoProfile -ExecutionPolicy Bypass -File apps/sixmic-desktop/packaging/build_desktop.ps1

    # 1b) startup-crash regression test (no override / unwritable override)
    powershell -NoProfile -ExecutionPolicy Bypass -File apps/sixmic-desktop/packaging/verify_packaged_startup.ps1

    # 2) installer (vendored Inno Setup 6.0.5; provenance re-verified)
    powershell -NoProfile -ExecutionPolicy Bypass -File apps/sixmic-desktop/packaging/build_installer.ps1

    # 3) installer payload proof + startup/restriction diagnosis
    powershell -NoProfile -ExecutionPolicy Bypass -File apps/sixmic-desktop/packaging/verify_installer_payload.ps1

    # 4) supplementary portable ZIP + extract/run verification
    powershell -NoProfile -ExecutionPolicy Bypass -File apps/sixmic-desktop/packaging/build_portable_zip.ps1

    # 5) REAL install/uninstall smoke - normal Windows machine / clean VM
    powershell -NoProfile -ExecutionPolicy Bypass -File apps/sixmic-desktop/packaging/smoke_test_installer.ps1

    # 6) OPTIONAL Authenticode signing with a CA-issued certificate
    powershell -NoProfile -ExecutionPolicy Bypass -File apps/sixmic-desktop/packaging/sign_artifacts.ps1 -PfxPath C:/secure/codesign.pfx

---

## 6. Qt / QML deployment strategy (no cross-major mixing)

* Only the Qt 6 runtime inside the build venv PySide6 wheel is bundled
  (assert_qt6 fails the build on any non-Qt6 runtime; no system Qt, no Qt5, no PyQt).
* The real wheel layout is resolved from QLibraryInfo at build time; PySide6 6.12
  uses the flat Windows layout (Qt6*.dll in PySide6/, plugins in PySide6/plugins,
  QML in PySide6/qml); older layouts (PySide6/Qt/...) are supported too.
* QML modules are discovered by scanning the application's own .qml/.js imports;
  only that closure is copied. PyInstaller's built-in hook collects the whole Qt
  QML tree (WebEngine/3D/media) - packaging overrides it with
  pyi/hook-PySide6.QtQml.py so no forbidden module can be swept in.
* The Qt 6 runtime DLL closure is computed from PE import tables by
  tools/qt_runtime.py (24 Qt6 DLLs in the final bundle); every bundled Qt6 DLL and
  platforms/qwindows.dll is verified byte-identical to the build venv wheel by
  tools/bundle_evidence.py --profile desktop.
* Windowed exe has no console: pyi/rth_gui_log.py is an OPT-IN runtime hook
  (SIXMIC_PACKAGING_GUI_LOG=<file>) used ONLY by smoke tests; unset in normal launches.
* Product icon assets/branding/sixmic3d.ico is embedded in exe and installer.

---

## 7. Installer and user-data policy

* Per-user install (PrivilegesRequired=lowest): {autopf} resolves to
  %LOCALAPPDATA%\Programs\echo; no admin prompt; /VERYSILENT automation.
* Installed files: echo\ (GUI bundle incl. protocol\), BackendCheck\ (headless
  diagnostic + protocol, frozen SixMic3D-BackendCheck.exe name), licenses\.
  Start Menu group echo + desktop shortcut echo + uninstall entry are created by
  Inno Setup.
* Writable product data (settings, SQLite DB, recordings, events, exports, logs)
  lives in %LOCALAPPDATA%\echo. main.py prefers that directory, falls back to an
  existing legacy %LOCALAPPDATA%\SixMic3D (one-time best-effort copy, legacy kept),
  then <app>/user-data, %TEMP%/echo, cwd/echo-user-data or ~/echo
  (SIXMIC_USER_DATA_DIR override honoured first); this behaviour is verified in 3.2.
* Uninstall preserves %LOCALAPPDATA%\echo and legacy %LOCALAPPDATA%\SixMic3D unless
  the user confirms or passes /DELETEUSERDATA=1; /VERYSILENT never deletes user data
  (review-only here).
* Silent switches: setup /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR=... /LOG=...;
  uninstaller /VERYSILENT /SUPPRESSMSGBOXES /NORESTART [/DELETEUSERDATA=1].

---

## 8. Why Inno Setup 6.0.5 (acquisition path and fallbacks tried)

1. Official innosetup-6.7.3.exe (latest): cannot install here (per-user rollback,
   HKCU uninstall-key Access Denied / exit 4); winget install also fails.
2. Official innoextract 1.9 cannot parse Inno 6.7 archives.
3. Official older release with innoextract support: Inno Setup 6.0.5 is the newest
   official release that innoextract 1.9 (up to 6.0.5) can unpack. Its signed
   installer was hash-verified against the GitHub release digest, Authenticode
   verified, unpacked offline and vendored. Stated honestly: NOT 6.3+; the .iss
   adapts itself.
4. NSIS fallback for the INSTALL-EXECUTION problem: official portable NSIS 3.09
   obtained and probe installers compiled; blocked by the same environment
   restriction, so NSIS is not the shipped installer.
5. No approval prompts were bypassed, no admin rights/system installs were used,
   and no installer was faked. Everything is logged under build-logs/.

---

## 9. Licensing (including the bundled font)

* Third-party notices shipped inside the installer/portable payload under
  licenses/: LGPL-3.0 and GPL-3.0 full texts, Python PSF license, PyInstaller
  bootloader license/exception, Qt/PySide6 notice, SIXMIC_PROTOCOL_NOTICE.txt,
  THIRD_PARTY_LICENSES.txt, LICENSES.sha256.
* **Bundled font**: Noto Sans CJK SC Medium (NotoSansCJKsc-Medium.otf, 16,523,632 B,
  sha256 ca094f6b0001fb048ca39ddd797a0cdb0179e1e55c6561e111c49c3e6a61d7b7) is
  distributed under the SIL Open Font License 1.1. The OFL text ships next to the
  font at assets/fonts/OFL.txt, which is inside the GUI bundle
  (_internal/assets/fonts/ in the installed/portable payload), satisfying the OFL
  requirement that the license accompany the font. The font is redistributed
  unmodified.
* Build-time tools (used to build, not shipped in the product payload):
  Inno Setup 6.0.5 (license retained at packaging/vendor/InnoSetup6/license.txt),
  innoextract 1.9, NSIS 3.09 (evaluation only) - see packaging/vendor/.
* The protocol data under interfaces/pc_backend_v1 has no declared open-source
  license yet; SIXMIC_PROTOCOL_NOTICE.txt flags this as a release blocker for
  public distribution. This is not legal advice - a license review is required
  before release.

## 10. Signing status (honest)

* All distribution artifacts are UNSIGNED: echo.exe Authenticode NotSigned,
  echo-Setup-x64.exe NotSigned, portable ZIP unsigned. SmartScreen reputation
  is therefore unknown. No signing is claimed.
* packaging/sign_artifacts.ps1 implements the signing step for a CA-issued
  certificate (PFX or cert-store thumbprint, SHA-256, optional RFC3161 timestamp,
  JSON evidence, verification via Get-AuthenticodeSignature).
* A SELF-SIGNED pipeline test was run by the Lead and its evidence is kept under
  dist/authenticode-test/ (certificate CN=SixMic3D Test Signing (NOT FOR
  DISTRIBUTION), selfSigned=true, trustedOnThisMachine=false). Those files are
  NOT distribution artifacts and must not be shipped.
* No CA-issued code-signing certificate exists in this environment, so real
  signing and SmartScreen reputation remain unverified.

---

## 11. Unverified / not claimed (explicit list)

1. Real install/uninstall execution: BLOCKED_BY_ENVIRONMENT on this host; must be
   run with smoke_test_installer.ps1 on a normal Windows machine/clean VM.
2. Uninstaller (unins000.exe) behaviour, shortcut/registry removal and user-data
   preservation: review-only here, not runtime-verified.
3. Default %LOCALAPPDATA%\echo creation on the real user profile: sandbox-denied
   for unsigned exes; redirected-LOCALAPPDATA selection/migration and the startup
   fallback chain are verified instead (3.2). Re-verify on a normal machine.
4. Interactive startup QMessageBox error-dialog rendering: code-verified only
   (requires all user-data candidates to be unwritable).
5. Authenticode signing / SmartScreen reputation: distribution artifacts NotSigned;
   only a self-signed pipeline test exists (NOT for distribution).
6. Clean Windows 11 VM test (no developer Python/Qt): not performed.
7. Visual/interactive GUI acceptance and real desktop GPU/compositor rendering:
   offscreen smoke only; owned by the frontend acceptance report.
8. Compiler is official Inno Setup 6.0.5, not 6.3+ (no 6.3+-only feature used).
9. Font rendering sharpness (NativeRendering/ClearType), DemiBold weight and the
   3840x2160 screenshot evidence were produced by the frontend owner; packaging
   verifies the font + OFL ship (sha256 recorded) and the packaged GUI loads with
   0 QML errors, not visual sharpness on a real display.
10. The echo DisplayName / Start-menu / install-dir changes are compile-time verified but
    not install-runtime verified here (installer execution is sandbox-blocked);
    smoke_test_installer.ps1 expectations were updated to DisplayName echo and
    Programs\echo for the normal-machine run.
11. Runtime taskbar/window display: main.py now sets setApplicationName /
    setApplicationDisplayName / setOrganizationName = echo and the QML window title
    is "echo"; offscreen headless windows expose no MainWindowTitle, so the
    interactive OS display is source/metadata-verified here, not runtime-observed.
12. PyInstaller outputs are not bit-for-bit reproducible; exact hashes are recorded.
13. Real board/network integration is out of scope; the backend self-test uses
    deterministic fixtures and no livePCM/board acceptance is claimed.

---

## 12. Evidence index (build-logs lanes)

* 20261026-081909 - FINAL 51-feature wiring GUI build (frozen UI c75dbc9d...): preflight, ui_marker.json
  (before/after identical), pyinstaller.log, protocol manifests, bundle_evidence.json,
  HASHES.sha256, desktop-selftest.capture.log (SELF-TEST PASS), gui-smoke.capture.log
  (SMOKE_GUI_OK), bundle diet reasons.
* 20261026-082007-scope-compliance - device-scope compliance proof: zero offline_reference in bundle names/contents/PYZ TOC/QML, runOfflineAnalysis comments/stub only, report page removed, nav/TimelineBar checks; scope_compliance.json.
* 20261026-082010-startup-robustness - packaged startup crash-fix regression:
  no-override GUI (SMOKE_GUI_OK), fallback dir evidence, unwritable-override GUI
  (SMOKE_GUI_OK), no-override self-test (SELF-TEST PASS), main.py static guards,
  pristine-bundle cleanup; packaged_startup_verification.json.
* 20261026-082024 - installer compile: inno_vendor provenance, iscc-compile.log,
  HASHES.sha256, build_installer.json (Inno 6.0.5, NotSigned).
* 20261026-082106-installer-payload - real install attempt + setup log (blocked),
  innoextract payload equality (589/130/9), extracted installed-layout smoke,
  startup-fallback probes on the packaged exe, installer_payload_verification.json.
* 20261026-082053-portable - portable ZIP build + extract/run verification,
  build_portable_zip.json, zip sha256.
* 20261026-082156-release-evidence - FINAL 51-FEATURE PC WIRING BUILD evidence:
  consolidated RELEASE_EVIDENCE.json/.md incl. feature wiring proof
  (feature_page_map.json 51 features/7 pages bundled, FeatureRibbon/FeaturePanel/
  FeatureChart components bundled + hosted from main.qml, feature_codec frozen into
  the PYZ with actualProducerLayout precedence/mixed encodings/unavailable fallback,
  AppViewModel featureRibbon/featureChart/openFeature/closeFeaturePanel, codec tests
  5 passed), pc_client packaging proof (embedded PYZ.pyz pc_client modules +
  FeatureBackendBridge class constant), NativeRendering=0 proof (71 bundled QML
  files), echo naming/data-policy evidence, 14 page screenshots (13x2560x1440 +
  1x1280x800 incl. 03b_spectrum_feature_panel) + 13 chart hashes, font weight
  hashes, protocol ports + PC-side mock data path (honest "PL task routes not wired"
  + "device gateway deployment pending" conclusions); HASHES.sha256 (echo.exe/
  echo-Setup/echo-Portable/all page shots/all chart PNGs/3 font OTFs + OFL + page
  map + codec); copies of six summaries + feature docs + carried-forward mock JSON.
* 20261024-152305 - backend-stage frozen BackendCheck build + self-test (unchanged).

---

## 13. Remaining work before public distribution

1. Run smoke_test_installer.ps1 on a normal Windows 11 machine/clean VM: real
   install -> shortcuts/registry -> GUI/backend smoke -> uninstall -> user data.
2. Authenticode-sign with a CA-issued certificate via sign_artifacts.ps1; delete
   dist/authenticode-test (self-signed, NOT for distribution); SmartScreen
   reputation will follow signing.
3. Verify default %LOCALAPPDATA%\echo creation and legacy %LOCALAPPDATA%\SixMic3D
   migration on a normal user session (primary path; fallback already verified).
4. Visual/interactive GUI acceptance on a real desktop (frontend owner), incl.
   100%/125%/150% DPI and the 13 final 3840x2160 screenshots in docs/frontend.
5. Align packaging/VERSION (0.1.0 -> installer file version 0.1.0.0) with the
   in-app version string (1.0.0-rc1) before shipping.
6. Keep the UI freeze marker, toolchain provenance and main.py robustness evidence
   in release notes; rebuild bundle + installer whenever the frozen UI changes.
