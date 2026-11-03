; 140 Jahan Pour - Inno Setup installer
; Phase 13 packaging. The accounting database is stored under
; %LOCALAPPDATA%\140JahanPour by the desktop runtime and is deliberately
; NOT removed by the uninstaller.

#define MyAppName "140 Jahan Pour"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "140 Jahan Pour"
#define MyAppExeName "FuelStation.exe"

[Setup]
AppId={{9D7D6F2A-7C88-4C7E-9D9E-140JAHANPOUR01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\140JahanPour
DefaultGroupName={#MyAppName}
OutputDir=installer
OutputBaseFilename=140JahanPour-Setup
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
WizardStyle=modern
UninstallDisplayName={#MyAppName}

[Files]
Source: "dist\FuelStation\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "اجرای {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Do not delete %LOCALAPPDATA%\140JahanPour. Accounting data must survive
; application removal unless the operator explicitly deletes it separately.
