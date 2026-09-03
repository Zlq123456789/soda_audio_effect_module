; Inno Setup Script for Soda Audio Effect Manager
; 建议使用 Inno Setup 6.x 编译

#define MyAppName "音效管理"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Soda Audio Effect Studio"
#define MyAppURL "https://github.com/Zlq123456789/soda_audio_effect_module"
#define MyAppExeName "音效管理.exe"
#define MyAppSourceDir "release_v1.0.0\音效管理_v1.0.0_免安装绿色版"

[Setup]
; App Details
AppId={{D37B4D21-7A6F-4A9B-B85E-5F793C2A9B10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
; Architecture
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Output
OutputDir=release_v1.0.0
OutputBaseFilename=Soda_Audio_Effect_v1.0.0_Setup
SetupIconFile=app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#MyAppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
