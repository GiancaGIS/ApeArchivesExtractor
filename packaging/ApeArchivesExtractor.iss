#define MyAppName "ApeArchivesExtractor"
#define MyAppVersion "1.0.1"
#define MyAppPublisher "GiancaGIS"
#define MyAppExeName "ApeArchivesExtractor.exe"

[Setup]
AppId={{0F96F7F9-3D53-4B5B-9B3D-78C168BB4E9E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
#ifdef DevelopmentBuild
OutputBaseFilename=ApeArchivesExtractorSetup-{#MyAppVersion}-development
InfoBeforeFile=RELEASE_REVIEW_PENDING.txt
#else
OutputBaseFilename=ApeArchivesExtractorSetup-{#MyAppVersion}
#endif
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
UsePreviousPrivileges=no
UsePreviousAppDir=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\src\apearchivesextractor\assets\apearchivesextractor_app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
#ifdef DevelopmentBuild
LicenseFile=..\LICENSE
#else
LicenseFile=..\dist\ApeArchivesExtractor\_internal\apearchivesextractor\legal\generated\INSTALLER_LICENSE.txt
#endif
InfoAfterFile=..\SOURCES.md

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"

[Tasks]
Name: "desktopicon"; Description: "Crea icona sul desktop"; GroupDescription: "Collegamenti:"; Flags: unchecked
Name: "setdefault"; Description: "Prova a impostare ApeArchivesExtractor come app predefinita per ZIP, 7Z, RAR e volumi"; GroupDescription: "Associazioni file:"; Flags: unchecked

[Files]
Source: "..\dist\ApeArchivesExtractor\*"; DestDir: "{app}"; Excludes: "*.pdb,*.lib,*.exp"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\scripts\register_file_associations.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\scripts\register_windows11_context_menu.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\register_file_associations.ps1"" -InstallPath ""{app}\{#MyAppExeName}"""; Flags: runhidden waituntilterminated runasoriginaluser; Check: not WizardIsTaskSelected('setdefault')
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\register_file_associations.ps1"" -InstallPath ""{app}\{#MyAppExeName}"" -SetDefault"; Flags: runhidden waituntilterminated runasoriginaluser; Check: WizardIsTaskSelected('setdefault')
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\register_windows11_context_menu.ps1"" -InstallDir ""{app}"" -PackagePath ""{app}\ApeArchivesExtractorIdentity.msix"""; Flags: runhidden waituntilterminated

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\register_windows11_context_menu.ps1"" -InstallDir ""{app}"" -PackagePath ""{app}\ApeArchivesExtractorIdentity.msix"" -Unregister"; Flags: runhidden waituntilterminated; RunOnceId: "ApeArchivesExtractorUnregisterWindows11"
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\register_file_associations.ps1"" -Unregister"; Flags: runhidden waituntilterminated; RunOnceId: "ApeArchivesExtractorUnregister"
