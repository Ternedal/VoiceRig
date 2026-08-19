param(
    [string[]]$Source = @(),
    [string]$Name = "VoiceRig Validation",
    [switch]$RequireModelRig,
    [string]$VoiceRigUrl = "http://127.0.0.1:8765",
    [string]$ModelRigUrl = "http://127.0.0.1:8080",
    [string]$ModelRigToken = $env:MODELRIG_TOKEN
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "VoiceRig-miljøet findes ikke. Kør .\setup-windows.ps1 først."
}

$ArgsList = @(
    "-m", "voicerig.rig_validation",
    "--name", $Name,
    "--voicerig-url", $VoiceRigUrl,
    "--modelrig-url", $ModelRigUrl,
    "--report", (Join-Path $PSScriptRoot "validation-report.json"),
    "--output-dir", (Join-Path $PSScriptRoot "validation-output")
)

if ($ModelRigToken) {
    $ArgsList += @("--modelrig-token", $ModelRigToken)
}
foreach ($Item in $Source) {
    $Resolved = Resolve-Path -LiteralPath $Item -ErrorAction Stop
    $ArgsList += @("--source", $Resolved.Path)
}
if ($RequireModelRig) {
    $ArgsList += "--require-modelrig"
}

Write-Host "VoiceRig fysisk rig-validering"
if ($Source.Count -eq 0) {
    Write-Host "Kører preflight: CUDA, VRAM, FFmpeg, verificerede modeller og speaker-runtime."
} else {
    Write-Host "Kører fuld produkt-E2E på $($Source.Count) mediefil(er)."
    Write-Host "VoiceRig service: $VoiceRigUrl"
    if ($RequireModelRig) {
        Write-Host "ModelRig backend: $ModelRigUrl (Bearer-token kræves)"
    }
    Write-Host "Output gemmes i .\validation-output"
}
Write-Host ""

& $Python @ArgsList
$Code = $LASTEXITCODE

Write-Host ""
if ($Code -eq 0) {
    Write-Host "VoiceRig-valideringen bestod."
} else {
    Write-Host "VoiceRig-valideringen fandt en blocker. Se validation-report.json."
}
exit $Code
