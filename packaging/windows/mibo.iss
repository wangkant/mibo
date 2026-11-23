; Inno Setup 6: the frozen folder (PyInstaller, dist\mibo) as
; dist\mibo-<version>-setup.exe. build.ps1 passes the version:
;   ISCC.exe /DAppVersion=0.2.0 mibo.iss
; Per user, no administrator. The shortcuts are the ones `mibo shortcut`
; writes, so the app's own settings see them as its own; the data home
; (~\mibo, as the pip install has it) is never removed.

#ifndef AppVersion
  #error Pass the version: ISCC /DAppVersion=x.y.z mibo.iss
#endif
#define AppGuid "AF8FF5B8-8FFF-4334-8BA1-90764370CEC9"

[Setup]
AppId={{{#AppGuid}}
AppName=Mibo
AppVersion={#AppVersion}
AppVerName=Mibo {#AppVersion}
AppPublisher=Qiankang Wang
AppPublisherURL=https://github.com/wangkant/mibo
AppSupportURL=https://github.com/wangkant/mibo/issues
PrivilegesRequired=lowest
DefaultDirName={userpf}\mibo
DisableProgramGroupPage=yes
; Always {userpf}: a folder typed elsewhere (D:\...) inherits "Authenticated
; Users: Modify", and another account could replace mibo.exe, which
; the Startup link runs as this person.
DisableDirPage=yes
OutputDir=..\..\dist
OutputBaseFilename=mibo-{#AppVersion}-setup
SetupIconFile=..\..\mibo\static\app.ico
UninstallDisplayIcon={app}\mibo.exe
UninstallDisplayName=Mibo
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
en.StartAtSignIn=Start Mibo when I sign in

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
; Only on a first install: after that the app's own setting decides, and an
; upgrade leaves the Startup link as it is.
Name: "startup"; Description: "{cm:StartAtSignIn}"; GroupDescription: "{cm:AutoStartProgramGroupDescription}"; Check: not IsUpgrade

[InstallDelete]
; A new version's files replace the old ones whole.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\mibo\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
; The shortcuts start in it; the app fills it, and it stays after an uninstall.
Name: "{code:DataHome}"; Flags: uninsneveruninstall

[Icons]
Name: "{userprograms}\Mibo"; Filename: "{app}\mibo.exe"; Parameters: "start --home ""{code:DataHome}"""; WorkingDir: "{code:DataHome}"; IconFilename: "{app}\_internal\mibo\static\app.ico"; Comment: "Mibo"
Name: "{userdesktop}\Mibo"; Filename: "{app}\mibo.exe"; Parameters: "start --home ""{code:DataHome}"""; WorkingDir: "{code:DataHome}"; IconFilename: "{app}\_internal\mibo\static\app.ico"; Comment: "Mibo"; Tasks: desktopicon
; At sign-in it stays behind its notification-area icon, as the app's own setting makes it.
Name: "{userstartup}\Mibo"; Filename: "{app}\mibo.exe"; Parameters: "start --home ""{code:DataHome}"" --background"; WorkingDir: "{code:DataHome}"; IconFilename: "{app}\_internal\mibo\static\app.ico"; Comment: "Mibo"; Tasks: startup

[Run]
Filename: "{app}\mibo.exe"; Parameters: "start --home ""{code:DataHome}"""; WorkingDir: "{code:DataHome}"; Description: "{cm:LaunchProgram,Mibo}"; Flags: nowait postinstall skipifsilent

[Code]
{ The home the app uses with no --home: AGENT_HOME, else ~\mibo,
  written as the app writes it (~ expanded, backslashes, none at the end). }
function DataHome(Param: String): String;
var
  Home: String;
begin
  Home := Trim(GetEnv('AGENT_HOME'));
  StringChangeEx(Home, '/', '\', True);
  if Home = '' then
    Home := '~\mibo';
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
  if CompareText(Link.TargetPath, ExpandConstant('{app}\mibo.exe')) = 0 then
    DeleteFile(Path);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Shell: Variant;
begin
  if CurUninstallStep <> usUninstall then
    Exit;
  Shell := CreateOleObject('WScript.Shell');
  RemoveOwnLink(Shell, ExpandConstant('{userdesktop}\Mibo.lnk'));
  RemoveOwnLink(Shell, ExpandConstant('{userprograms}\Mibo.lnk'));
  RemoveOwnLink(Shell, ExpandConstant('{userstartup}\Mibo.lnk'));
end;
