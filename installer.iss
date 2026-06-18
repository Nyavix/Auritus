; ----------------------------------------------------------------------
; Auritus installer (Inno Setup 6.x)
;
; Builds a per-user installer (no admin required) that drops the bundle
; under %LOCALAPPDATA%\Programs\Auritus, registers a Start Menu shortcut,
; and offers optional Desktop and Startup-folder shortcuts.
;
; To compile:  installer.bat   (or run iscc.exe installer.iss directly)
; Output:      installer-output\Auritus-Setup-vX.Y.Z.exe
; ----------------------------------------------------------------------

#define MyAppName       "Auritus"
#define MyAppVersion    "0.3.2"
#define MyAppPublisher  "Nyavix"
#define MyAppURL        "https://github.com/Nyavix/Auritus"
#define MyAppExeName    "Auritus.exe"

[Setup]
; Stable AppId so future installers upgrade in place.
AppId={{099D2D24-E1D4-465F-95EC-4A69C8FF0872}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=installer-output
OutputBaseFilename=Auritus-Setup-v{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "autostart";   Description: "&Launch {#MyAppName} when Windows starts (recommended for tray apps)"; GroupDescription: "Startup:"; Flags: checkedonce

[Files]
Source: "dist\Auritus\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}";  Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}";   Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}";   Filename: "{app}\{#MyAppExeName}"; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "&Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Best-effort: kill the running tray before uninstall removes its files.
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#MyAppExeName}"; Flags: runhidden; RunOnceId: "KillAuritus"
