; ESL License Monitor - Installer Script
; Requires Inno Setup 6+

#define MyAppName "ESL License Monitor"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "ESL - Engineering Software Lab"
#define MyAppURL "https://www.esl-sw.com"
#define MyAppExeName "esl-license-monitor.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\ESL\LicenseMonitor
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=
OutputDir=installer_output
OutputBaseFilename=ESL-License-Monitor-Setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "dist\esl-license-monitor.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\esl_logo.png"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\servers.json.sample"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Run]
Filename: "{app}\README.md"; Description: "View README"; Flags: postinstall shellexec skipifsilent unchecked

[Code]
// Show a disclaimer page during installation
procedure InitializeWizard;
var
  DisclaimerPage: TOutputMsgMemoWizardPage;
begin
  DisclaimerPage := CreateOutputMsgMemoPage(wpLicense,
    'DEMO SOFTWARE DISCLAIMER',
    'Please read the following important information before continuing.',
    'By installing this software, you acknowledge and agree to the following:',
    'DISCLAIMER: This software is provided by ESL (Engineering Software Lab) strictly as a DEMONSTRATION TOOL.' + #13#10 +
    #13#10 +
    'THIS IS NOT PRODUCTION SOFTWARE.' + #13#10 +
    #13#10 +
    'ESL makes no warranties or representations of any kind, express or implied, regarding the accuracy, completeness, reliability, security, or fitness for any particular purpose of this software or any data it produces.' + #13#10 +
    #13#10 +
    'By using this tool you acknowledge that:' + #13#10 +
    '- All output is approximate and may be inaccurate.' + #13#10 +
    '- ESL assumes no responsibility or liability for any decisions made based on the data shown.' + #13#10 +
    '- This tool has no security guarantees.' + #13#10 +
    '- The software is provided "AS IS" without any obligation of support, maintenance, or updates.' + #13#10 +
    '- ESL shall not be held liable for any direct, indirect, incidental, or consequential damages arising from its use.');
end;
