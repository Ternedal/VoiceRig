$ErrorActionPreference = "Stop"
$startup = [Environment]::GetFolderPath("Startup")
$vbsPath = Join-Path $startup "VoiceRig.vbs"
if (Test-Path $vbsPath) {
    Remove-Item -LiteralPath $vbsPath -Force
    Write-Host "VoiceRig autostart er fjernet."
} else {
    Write-Host "VoiceRig autostart var ikke installeret."
}
