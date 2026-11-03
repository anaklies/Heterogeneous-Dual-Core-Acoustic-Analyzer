; ============================================================================
; echo (SixMic3D codebase) Windows installer (Inno Setup 6.x; verified with official 6.0.5)
; ============================================================================
; Built by: apps/sixmic-desktop/packaging/build_installer.ps1
; Output  : SixMic3D-Setup-x64.exe (product display name is echo; file names stay SixMic3D*)
;
; What this installs
;   * echo.exe                   - Qt Quick/QML desktop application (onedir
;                                  PyInstaller bundle: runtime DLLs, Qt 6 Bin,
;                                  Qt platform/QML/imageformats plugins, QML
;                                  modules, app UI resources)
;   * BackendCheck...           - headless SixMic3D-BackendCheck.exe diagnostic
;                                  (--self-test), Qt-free
;   * protocol                  - sixmic-analysis v1 protocol data
;                                  (PROTOCOL.md, schema/, golden/, errors/,
;                                  features/, device/, dto/) next to each exe
;   * licenses                  - third-party notices (Qt/PySide6 LGPL,
;                                  Python PSF, protocol schema notice)
;
; Install model (deliberate):
;   * per-user install (PrivilegesRequired=lowest) -> no admin prompt, works
;     with /VERYSILENT in automated smoke tests; {autopf} = %LOCALAPPDATA%Programs
;   * all writable user data (recordings, events, exports, logs, db) lives in
;     %LOCALAPPDATA%SixMic3D and is NEVER written into {app}
;   * uninstall preserves user data unless the user explicitly confirms, or
;     passes /DELETEUSERDATA=1 (never implied by /VERYSILENT)
;
; Command-line (for smoke_test_installer.ps1 and IT deployment):
;   /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="<target>" /LOG="<file>"
;   unins000.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
;   unins000.exe /VERYSILENT /DELETEUSERDATA=1   (explicit data deletion)
;
; ============================================================================

#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#ifndef MyAppVersion4
  #define MyAppVersion4 MyAppVersion + ".0"
#endif
#ifndef AppSourceDir
  #define AppSourceDir "..\..\dist\echo"
#endif
#ifndef BackendSourceDir
  #define BackendSourceDir "..\..\dist\SixMic3D-BackendCheck"
#endif
#ifndef LicenseDir
  #define LicenseDir "..\licenses"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\dist\installer"
#endif
#ifndef SetupIconFile
  #define SetupIconFile ""
#endif

; Architecture identifiers: Inno Setup 6.3+ understands "x64compatible" while
; 6.0.x-6.2.x only understand "x64". ISPP's Ver works on both, so the same .iss
; compiles with either compiler. The vendored build-time compiler is the
; official Inno Setup 6.0.5 (see packaging/vendor/README.md); on 6.3+ the newer
; identifier is selected automatically.
#if Ver >= EncodeVer(6,3,0)
  #define ArchIdent "x64compatible"
#else
  #define ArchIdent "x64"
#endif

; Fail at compile time with an exact message instead of producing a broken installer.
#if !FileExists(AppSourceDir + "\echo.exe")
  #error echo desktop bundle not found. Build it first: powershell -File apps/sixmic-desktop/packaging/build_desktop.ps1
#endif
#if !FileExists(BackendSourceDir + "\SixMic3D-BackendCheck.exe")
  #error BackendCheck bundle not found. Build it first: powershell -File apps/sixmic-desktop/packaging/build_backend_check.ps1
#endif
#if !FileExists(LicenseDir + "\THIRD_PARTY_LICENSES.txt")
  #error License files not found in LicenseDir. Expected packaging/licenses/THIRD_PARTY_LICENSES.txt.
#endif
#if !FileExists(LicenseDir + "\LICENSE-LGPL-3.0.txt")
  #error LGPL-3.0 text missing: licensing must be complete before an installer is built.
#endif

[Setup]
AppId={{7C1E5A2B-3D4F-4A6B-8C9D-0E1F2A3B4C5D}
AppName=echo
AppVersion={#MyAppVersion}
AppVerName=echo {#MyAppVersion}
AppPublisher=echo project
DefaultDirName={autopf}\echo
DefaultGroupName=echo
DisableProgramGroupPage=yes
DisableDirPage=auto
UsePreviousAppDir=no
AllowNoIcons=yes
LicenseFile={#LicenseDir}\THIRD_PARTY_LICENSES.txt
#if SetupIconFile != ""
SetupIconFile={#SetupIconFile}
#endif
OutputDir={#OutputDir}
OutputBaseFilename=echo-Setup-x64
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed={#ArchIdent}
ArchitecturesInstallIn64BitMode={#ArchIdent}
MinVersion=10.0
UninstallDisplayIcon={app}\echo.exe
UninstallDisplayName=echo
VersionInfoVersion={#MyAppVersion4}
VersionInfoCompany=echo project
VersionInfoDescription=echo acoustic analysis workstation installer
VersionInfoProductName=echo
VersionInfoProductVersion={#MyAppVersion4}
CloseApplications=yes
RestartApplications=no

[Tasks]
; no optional tasks: start menu shortcuts are always installed

[Files]
; Desktop application bundle (PyInstaller onedir: exe + _internal runtime DLLs,
; Qt6 bin, Qt plugins, QML modules, app UI resources, protocol data).
Source: "{#AppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Headless backend diagnostic + its protocol data.
Source: "{#BackendSourceDir}\*"; DestDir: "{app}\BackendCheck"; Flags: ignoreversion recursesubdirs createallsubdirs
; Third-party license texts and notices (Qt/PySide6 LGPL, Python PSF, protocol).
Source: "{#LicenseDir}\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\echo\echo"; Filename: "{app}\echo.exe"; WorkingDir: "{app}"; Comment: "echo acoustic analysis workstation"
Name: "{autodesktop}\echo"; Filename: "{app}\echo.exe"; WorkingDir: "{app}"; Comment: "echo acoustic analysis workstation"
Name: "{autoprograms}\echo\Backend diagnostics (self-test)"; Filename: "{app}\BackendCheck\SixMic3D-BackendCheck.exe"; Parameters: "--self-test"; WorkingDir: "{app}\BackendCheck"; Comment: "Run the headless echo backend self-test; prints SELF-TEST PASS/FAIL"

[Run]
Filename: "{app}\echo.exe"; Description: "{cm:LaunchProgram,echo}"; Flags: nowait postinstall skipifsilent

; NOTE: no [UninstallDelete] for %LOCALAPPDATA%\echo (or legacy %LOCALAPPDATA%\SixMic3D).
; User recordings/events/
; config are deliberately outside {app}; deletion requires explicit consent in
; [Code] below (or /DELETEUSERDATA=1).

[Code]
function UserDataDir(): String;
begin
  Result := ExpandConstant('{localappdata}\echo');
end;

function LegacyUserDataDir(): String;
begin
  Result := ExpandConstant('{localappdata}\SixMic3D');
end;

function DeleteUserDataRequested(): Boolean;
var
  Value: String;
begin
  Value := ExpandConstant('{param:DELETEUSERDATA|0}');
  Result := (Value = '1') or (Lowercase(Value) = 'true') or (Lowercase(Value) = 'yes');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
  LegacyDir: String;
  Details: String;
  DeleteIt: Boolean;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  DataDir := UserDataDir();
  LegacyDir := LegacyUserDataDir();
  if (not DirExists(DataDir)) and (not DirExists(LegacyDir)) then
    Exit;
  Details := DataDir;
  if DirExists(LegacyDir) then
    Details := Details + #13#10 + 'Legacy data: ' + LegacyDir;
  DeleteIt := False;
  if DeleteUserDataRequested() then
  begin
    DeleteIt := True;
  end
  else if not UninstallSilent then
  begin
    DeleteIt := MsgBox(
      'Also delete your echo recordings, event data and settings?' + #13#10 +
      Details + #13#10 + #13#10 +
      'Choose No to keep them (recommended).',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
  end;
  if DeleteIt then
  begin
    if DirExists(DataDir) then
      DelTree(DataDir, True, True, True);
    if DirExists(LegacyDir) then
      DelTree(LegacyDir, True, True, True);
  end
  else if not UninstallSilent then
  begin
    MsgBox('Your echo recordings and settings were kept in:' + #13#10 + Details,
      mbInformation, MB_OK);
  end;
end;
