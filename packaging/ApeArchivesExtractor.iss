#define MyAppName "ApeArchivesExtractor"
#define MyAppVersion "1.0.3"
#define MyAppPublisher "GiancaGIS"
#define MyAppExeName "ApeArchivesExtractor.exe"
#if FileExists(SourcePath + "..\dist\ApeArchivesExtractor\ApeArchivesExtractorShellExtension.dll")
  #define WithArchiveProperties
#endif

[Setup]
AppId={{0F96F7F9-3D53-4B5B-9B3D-78C168BB4E9E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=ApeArchivesExtractorSetup-{#MyAppVersion}
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
ChangesEnvironment=yes
LicenseFile=..\dist\ApeArchivesExtractor\_internal\apearchivesextractor\legal\generated\INSTALLER_LICENSE.txt
InfoAfterFile=..\SOURCES.md

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"

[Tasks]
Name: "desktopicon"; Description: "Crea icona sul desktop"; GroupDescription: "Collegamenti:"; Flags: unchecked
Name: "addtopath"; Description: "Rendi disponibile ape-arch dal terminale (aggiungi al PATH)"; GroupDescription: "Riga di comando:"
#ifdef WithArchiveProperties
Name: "archiveproperties"; Description: "Mostra la scheda Archivio APE nelle proprieta degli archivi"; GroupDescription: "Esplora file:"
#endif
Name: "setdefault"; Description: "Prova a impostare ApeArchivesExtractor come app predefinita per ZIP, 7Z, RAR e volumi"; GroupDescription: "Associazioni file:"; Flags: unchecked

[Files]
Source: "..\dist\ApeArchivesExtractor\*"; DestDir: "{app}"; Excludes: "*.pdb,*.lib,*.exp"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\scripts\register_file_associations.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\scripts\register_windows11_context_menu.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\scripts\register_cli_path.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\scripts\register_archive_properties.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Registry]
Root: HKA; Subkey: "Software\GiancaGIS\ApeArchivesExtractor\Installer"; Flags: uninsdeletekeyifempty

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\register_file_associations.ps1"" -InstallPath ""{app}\{#MyAppExeName}"""; Flags: runhidden waituntilterminated runasoriginaluser; Check: not WizardIsTaskSelected('setdefault')
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\register_file_associations.ps1"" -InstallPath ""{app}\{#MyAppExeName}"" -SetDefault"; Flags: runhidden waituntilterminated runasoriginaluser; Check: WizardIsTaskSelected('setdefault')
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\register_windows11_context_menu.ps1"" -InstallDir ""{app}"" -PackagePath ""{app}\ApeArchivesExtractorIdentity.msix"""; Flags: runhidden waituntilterminated

[UninstallRun]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\register_archive_properties.ps1"" -InstallDir ""{app}"" -Scope {code:CliPathScope} -Unregister"; Flags: runhidden waituntilterminated; RunOnceId: "ApeArchivesExtractorUnregisterArchiveProperties"
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\register_cli_path.ps1"" -InstallPath ""{app}"" -Scope {code:CliPathScope} -Unregister"; Flags: runhidden waituntilterminated; RunOnceId: "ApeArchivesExtractorUnregisterCliPath"
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\register_windows11_context_menu.ps1"" -InstallDir ""{app}"" -PackagePath ""{app}\ApeArchivesExtractorIdentity.msix"" -Unregister"; Flags: runhidden waituntilterminated; RunOnceId: "ApeArchivesExtractorUnregisterWindows11"
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\register_file_associations.ps1"" -Unregister"; Flags: runhidden waituntilterminated; RunOnceId: "ApeArchivesExtractorUnregister"

[Code]
function CliPathScope(Param: String): String;
begin
  if IsAdminInstallMode then Result := 'Machine' else Result := 'User';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  Parameters: String;
begin
  if CurStep = ssPostInstall then
  begin
    Parameters := '-NoProfile -ExecutionPolicy Bypass -File "' +
      ExpandConstant('{app}\register_cli_path.ps1') + '" -InstallPath "' +
      ExpandConstant('{app}') + '" -Scope ' + CliPathScope('');
    if not WizardIsTaskSelected('addtopath') then
      Parameters := Parameters + ' -Unregister';
    if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      Parameters, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      RaiseException('Impossibile avviare la registrazione di ape-arch nel PATH.');
    if ResultCode <> 0 then
      RaiseException('Registrazione di ape-arch nel PATH fallita. Codice: ' + IntToStr(ResultCode));
    Parameters := '-NoProfile -ExecutionPolicy Bypass -File "' +
      ExpandConstant('{app}\register_archive_properties.ps1') + '" -InstallDir "' +
      ExpandConstant('{app}') + '" -Scope ' + CliPathScope('');
#ifdef WithArchiveProperties
    if not WizardIsTaskSelected('archiveproperties') then
      Parameters := Parameters + ' -Unregister';
#else
    Parameters := Parameters + ' -Unregister';
#endif
    if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      Parameters, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      RaiseException('Impossibile configurare la scheda proprieta degli archivi.');
    if ResultCode <> 0 then
      RaiseException('Configurazione scheda proprieta fallita. Codice: ' + IntToStr(ResultCode));
  end;
end;
