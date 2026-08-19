$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".venv\Scripts\voicerig.exe")) {
    throw "VoiceRig er ikke installeret endnu. Kør .\setup-windows.ps1 først."
}
& .\.venv\Scripts\voicerig.exe
