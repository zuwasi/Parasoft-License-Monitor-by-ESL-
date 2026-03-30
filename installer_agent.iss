; ESL License Monitor Agent - Installer Script
; Requires Inno Setup 6+

#define MyAppName "ESL License Monitor Agent"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "ESL - Engineering Software Lab"
#define MyAppURL "https://www.esl-sw.com"
#define MyAppExeName "esl-license-agent.exe"

[Setup]
AppId={{B2C3D4E5-F6A7-8901-BCDE-F12345678901}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\ESL\LicenseAgent
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=ESL-License-Agent-Setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "dist\esl-license-agent.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\agent_config.json.sample"; DestDir: "{app}"; DestName: "agent_config.json"; Flags: onlyifdoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Configure Agent"; Filename: "{app}\agent_config.json"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--generate-token"; Description: "Generate auth token"; Flags: postinstall runascurrentuser nowait skipifsilent unchecked
Filename: "{app}\{#MyAppExeName}"; Parameters: "--install-service"; Description: "Install as Windows Service"; Flags: postinstall runascurrentuser nowait skipifsilent unchecked

[UninstallRun]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--remove-service"; Flags: runhidden

[Code]
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
    'The agent component runs as an HTTP server that exposes license log files. Ensure proper firewall rules are in place.' + #13#10 +
    #13#10 +
    '- The software is provided "AS IS" without any warranty.' + #13#10 +
    '- ESL shall not be held liable for any damages arising from its use.');
end;
