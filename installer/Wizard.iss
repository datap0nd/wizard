; WizardSetup.exe: installs Wizard for the current Windows account (no admin rights), like Scribble's installer.
;   ISCC /DAppVersion=1.0.<run> installer\Wizard.iss      (CI: .github/workflows/desktop.yml)
; Expects the payload from scripts/build_desktop_payload.py and `dotnet build -o artifacts\desktop\payload\bar`.
;
; Program files go to %LOCALAPPDATA%\Programs\Wizard and are replaced by every update. The person's settings,
; conversations, Gemini sign-in, knowledge base and logs live in %LOCALAPPDATA%\Wizard and are kept, also on uninstall.
; Company settings: put wizard.provision next to WizardSetup.exe and setup hands it to Wizard, which imports it on its
; next start and deletes the plaintext copy. The installer itself never contains a password or token.

#define AppName "Wizard"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define Payload "..\artifacts\desktop\payload"

[Setup]
AppId={{8B0B4C3E-7E0F-4C8A-9D55-2F1E6A7C9B41}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
DefaultDirName={localappdata}\Programs\Wizard
DisableDirPage=yes
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\artifacts\desktop
OutputBaseFilename=WizardSetup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\apps\desktop\assets\wizard.ico
UninstallDisplayIcon={app}\bar\WizardBar.exe
UninstallDisplayName={#AppName}
CloseApplications=force
RestartApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription=Wizard desktop assistant setup

[Tasks]
Name: "autostart"; Description: "Start Wizard when I sign in to Windows (recommended)"
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[InstallDelete]
; A clean copy of the program on every update, so files removed upstream do not linger. Data is elsewhere.
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\bar"
Type: filesandordirs; Name: "{app}\runtime"

[Files]
Source: "{#Payload}\bar\*"; DestDir: "{app}\bar"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.pdb"
Source: "{#Payload}\app\*"; DestDir: "{app}\app"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Payload}\runtime\*"; DestDir: "{app}\runtime"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{src}\wizard.provision"; DestDir: "{localappdata}\Wizard"; Flags: external skipifsourcedoesntexist ignoreversion

[Icons]
Name: "{userprograms}\Wizard"; Filename: "{app}\bar\WizardBar.exe"; Comment: "Ask Wizard (Ctrl+Alt+W)"
Name: "{userdesktop}\Wizard"; Filename: "{app}\bar\WizardBar.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Wizard"; ValueData: """{app}\bar\WizardBar.exe"""; Tasks: autostart; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "Wizard"; ValueType: none; Flags: deletevalue; Tasks: not autostart

[Run]
; Also after a silent update (the in-app updater), unless /NOLAUNCH=1 (CI smoke test).
Filename: "{app}\bar\WizardBar.exe"; Description: "Start Wizard now"; Flags: nowait postinstall; Check: ShouldLaunch

[UninstallRun]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -NonInteractive -Command ""{code:StopCommand}"""; Flags: runhidden waituntilterminated; RunOnceId: "StopWizard"

[Code]
function ShouldLaunch: Boolean;
begin
  Result := ExpandConstant('{param:NOLAUNCH|0}') = '0';
end;

{ Stops WizardBar and the Python service that runs from this installation (never any other Python). }
function StopCommand(Param: String): String;
begin
  Result := 'Get-Process WizardBar,python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like ''' +
    ExpandConstant('{app}') + '\*'' } | Stop-Process -Force -ErrorAction SilentlyContinue';
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -NonInteractive -Command "' + StopCommand('') + '"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;
