; Inno Setup 6: the frozen folder (PyInstaller, dist\personagent) as
; dist\personagent-<version>-setup.exe. build.ps1 passes the version:
;   ISCC.exe /DAppVersion=1.5.0 personagent.iss
; Per user, no administrator. The shortcuts are the ones `personagent shortcut`
; writes, so the app's own settings see them as its own; the data home
; (~\personagent, as the pip install has it) is never removed.

#ifndef AppVersion
  #error Pass the version: ISCC /DAppVersion=x.y.z personagent.iss
#endif
#define AppGuid "6B0F3C1E-5A47-4C8E-9B1D-2F7A9C4E8D31"

[Setup]
AppId={{{#AppGuid}}
AppName=personagent
AppVersion={#AppVersion}
AppVerName=personagent {#AppVersion}
AppPublisher=Qiankang Wang
AppPublisherURL=https://github.com/wangkant/personagent
AppSupportURL=https://github.com/wangkant/personagent/issues
PrivilegesRequired=lowest
DefaultDirName={userpf}\personagent
DisableProgramGroupPage=yes
; Always {userpf}: a folder typed elsewhere (D:\...) inherits "Authenticated
; Users: Modify", and another account could replace personagent.exe, which
; the Startup link runs as this person.
DisableDirPage=yes
OutputDir=..\..\dist
OutputBaseFilename=personagent-{#AppVersion}-setup
SetupIconFile=..\..\persona_agent\static\app.ico
UninstallDisplayIcon={app}\personagent.exe
UninstallDisplayName=personagent
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; The language the system uses, English otherwise.
ShowLanguageDialog=no
LanguageDetectionMethod=uilanguage
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
; Inno Setup ships no Simplified Chinese: this file translates the pages this setup shows.
Name: "zh"; MessagesFile: "compiler:Default.isl,ChineseSimplified.isl"

[CustomMessages]
; Chinese: in ChineseSimplified.isl.
en.StartAtSignIn=Start personagent when I sign in

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
; Only on a first install: after that the app's own setting decides, and an
; upgrade leaves the Startup link as it is.
Name: "startup"; Description: "{cm:StartAtSignIn}"; GroupDescription: "{cm:AutoStartProgramGroupDescription}"; Check: not IsUpgrade

[InstallDelete]
; A new version's files replace the old ones whole.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\personagent\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
; The shortcuts start in it; the app fills it, and it stays after an uninstall.
Name: "{code:DataHome}"; Flags: uninsneveruninstall

[Icons]
Name: "{userprograms}\personagent"; Filename: "{app}\personagent.exe"; Parameters: "start --home ""{code:DataHome}"""; WorkingDir: "{code:DataHome}"; IconFilename: "{app}\_internal\persona_agent\static\app.ico"; Comment: "personagent"
Name: "{userdesktop}\personagent"; Filename: "{app}\personagent.exe"; Parameters: "start --home ""{code:DataHome}"""; WorkingDir: "{code:DataHome}"; IconFilename: "{app}\_internal\persona_agent\static\app.ico"; Comment: "personagent"; Tasks: desktopicon
; At sign-in it stays behind its notification-area icon, as the app's own setting makes it.
Name: "{userstartup}\personagent"; Filename: "{app}\personagent.exe"; Parameters: "start --home ""{code:DataHome}"" --background"; WorkingDir: "{code:DataHome}"; IconFilename: "{app}\_internal\persona_agent\static\app.ico"; Comment: "personagent"; Tasks: startup

[Run]
Filename: "{app}\personagent.exe"; Parameters: "start --home ""{code:DataHome}"""; WorkingDir: "{code:DataHome}"; Description: "{cm:LaunchProgram,personagent}"; Flags: nowait postinstall skipifsilent

[Code]
{ The home the app uses with no --home: AGENT_HOME, else ~\personagent,
  written as the app writes it (~ expanded, backslashes, none at the end). }
function DataHome(Param: String): String;
var
  Home: String;
begin
  Home := Trim(GetEnv('AGENT_HOME'));
  StringChangeEx(Home, '/', '\', True);
  if Home = '' then
    Home := '~\personagent';
  if (Home = '~') or (Copy(Home, 1, 2) = '~\') then
    Home := GetEnv('USERPROFILE') + Copy(Home, 2, MaxInt);
  Result := RemoveBackslashUnlessRoot(Home);
end;

function IsUpgrade: Boolean;
begin
  Result := RegValueExists(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{' + '{#AppGuid}' + '}_is1', 'Inno Setup: App Path');
end;

{ The app's settings can make these links again after setup; take away the ones that open this copy. }
procedure RemoveOwnLink(Shell: Variant; Path: String);
var
  Link: Variant;
begin
  if not FileExists(Path) then
    Exit;
  Link := Shell.CreateShortcut(Path);
  if CompareText(Link.TargetPath, ExpandConstant('{app}\personagent.exe')) = 0 then
    DeleteFile(Path);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Shell: Variant;
begin
  if CurUninstallStep <> usUninstall then
    Exit;
  Shell := CreateOleObject('WScript.Shell');
  RemoveOwnLink(Shell, ExpandConstant('{userdesktop}\personagent.lnk'));
  RemoveOwnLink(Shell, ExpandConstant('{userprograms}\personagent.lnk'));
  RemoveOwnLink(Shell, ExpandConstant('{userstartup}\personagent.lnk'));
end;
