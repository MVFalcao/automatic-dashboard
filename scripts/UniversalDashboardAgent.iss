#define AppVersion "0.2.1"
#ifndef BundleDir
  #define BundleDir "release-bundle"
#endif

[Setup]
AppId={{B8E3C2C8-0EEB-4C0D-A7E3-0D5E4A1D1A7E}
AppName=Universal Dashboard Agent
AppVersion={#AppVersion}
AppPublisher=Universal Dashboard Agent
DefaultDirName={localappdata}\UniversalDashboardAgent
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
Uninstallable=no
OutputDir=dist
OutputBaseFilename=UniversalDashboardAgent-{#AppVersion}-windows-x64-setup
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
WizardStyle=modern
SetupLogging=yes

[Files]
Source: "{#BundleDir}\*"; DestDir: "{tmp}\UniversalDashboardAgent-bundle"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Universal Dashboard Agent"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\dashboard-start.ps1"""; WorkingDir: "{app}"
Name: "{group}\Configure AI provider"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\dashboard-first-run.ps1"""; WorkingDir: "{app}"
Name: "{group}\Uninstall Universal Dashboard Agent"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\uninstall-windows.ps1"" -InstallDir ""{app}"" -ConfirmUninstall"; WorkingDir: "{app}"

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  PowerShellPath: String;
  InstallScript: String;
  BundlePath: String;
  Parameters: String;
  ResultCode: Integer;
begin
  if CurStep <> ssPostInstall then
    exit;

  PowerShellPath := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
  BundlePath := ExpandConstant('{tmp}\UniversalDashboardAgent-bundle');
  InstallScript := BundlePath + '\scripts\install-windows.ps1';
  Parameters := '-NoProfile -ExecutionPolicy Bypass -File "' + InstallScript +
    '" -BundleDir "' + BundlePath + '" -InstallDir "' + ExpandConstant('{app}') + '"';

  if not ExecAndLogOutput(PowerShellPath, Parameters, BundlePath, SW_SHOWNORMAL,
    ewWaitUntilTerminated, ResultCode, nil) then
    RaiseException('Unable to start the application installer: ' + SysErrorMessage(ResultCode));
  if ResultCode <> 0 then
    RaiseException(Format('Application installation failed with exit code %d. Review the Setup log.', [ResultCode]));
end;
