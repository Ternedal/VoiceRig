$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$exe = (Resolve-Path ".venv\Scripts\voicerig.exe").Path
$working = (Resolve-Path ".").Path
$startup = [Environment]::GetFolderPath("Startup")
if ([string]::IsNullOrWhiteSpace($startup)) {
    throw "Windows Startup-mappen kunne ikke findes."
}

# A tiny per-user VBS launcher keeps the local sidecar alive after login without
# opening a console window. No administrator rights or machine-wide service.
function VbsEscape([string]$value) { return $value.Replace('"', '""') }
$vbsPath = Join-Path $startup "VoiceRig.vbs"
$content = @"
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = "$(VbsEscape $working)"
shell.Run """$(VbsEscape $exe)""", 0, False
"@
Set-Content -LiteralPath $vbsPath -Value $content -Encoding Unicode
Write-Host "VoiceRig autostart installeret for denne bruger: $vbsPath"
