#define AppVersion "0.2.0"
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

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{tmp}\UniversalDashboardAgent-bundle\scripts\install-windows.ps1"" -BundleDir ""{tmp}\UniversalDashboardAgent-bundle"" -InstallDir ""{app}"""; WorkingDir: "{tmp}\UniversalDashboardAgent-bundle"; Flags: waituntilterminated

[Icons]
Name: "{group}\Universal Dashboard Agent"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\dashboard-start.ps1"""; WorkingDir: "{app}"
Name: "{group}\Configure AI provider"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\dashboard-first-run.ps1"""; WorkingDir: "{app}"
Name: "{group}\Uninstall Universal Dashboard Agent"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\uninstall-windows.ps1"" -InstallDir ""{app}"" -ConfirmUninstall"; WorkingDir: "{app}"
