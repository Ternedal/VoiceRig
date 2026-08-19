param(
    [string[]]$Source = @(),
    [string]$Name = "VoiceRig Validation",
    [switch]$RequireModelRig,
    [switch]$RequirePiperFallback,
    [string]$VoiceRigUrl = "http://127.0.0.1:8765",
    [string]$ModelRigUrl = "http://127.0.0.1:8080",
    [string]$ModelRigWorkerUrl = "http://127.0.0.1:8099",
    [string]$ModelRigToken = $env:MODELRIG_TOKEN
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "VoiceRig-miljøet findes ikke. Kør .\setup-windows.ps1 først."
}
if ($RequirePiperFallback -and $Source.Count -eq 0) {
    throw "-RequirePiperFallback kræver en fuld E2E-kørsel med mindst én -Source."
}
if ($RequirePiperFallback -and -not $RequireModelRig) {
    throw "-RequirePiperFallback kræver også -RequireModelRig."
}
if (($RequireModelRig -or $RequirePiperFallback) -and -not $ModelRigToken) {
    throw "MODELRIG_TOKEN mangler. Sæt token i sessionen eller brug -ModelRigToken."
}

$ArgsList = @(
    "-m", "voicerig.acceptance_wrapper",
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
    Write-Host "Kører preflight: clean Git checkout, CUDA, VRAM, FFmpeg, verificerede modeller og speaker-runtime."
} else {
    Write-Host "Kører fuld produkt-E2E på $($Source.Count) mediefil(er)."
    Write-Host "Acceptance kræver clean checkout og aktiv VoiceRig-service på samme Git HEAD."
    Write-Host "VoiceRig service: $VoiceRigUrl"
    if ($RequireModelRig) {
        Write-Host "ModelRig backend: $ModelRigUrl (Bearer-token kræves)"
    }
    if ($RequirePiperFallback) {
        Write-Host "ModelRig worker: $ModelRigWorkerUrl (kun loopback; bruges til rigtig Piper-WAV)"
        Write-Host "Piper fallback: kræves; VoiceRig stoppes kortvarigt og genstartes automatisk i try/finally."
    }
    Write-Host "Output gemmes i .\validation-output"
}
Write-Host ""

& $Python @ArgsList
$Code = $LASTEXITCODE

if ($Code -eq 0 -and $RequirePiperFallback) {
    Write-Host ""
    Write-Host "Kører automatisk Piper fallback + rigtig Piper-syntese + VoiceRig restore..."
    & (Join-Path $PSScriptRoot "test-piper-fallback.ps1") `
        -VoiceRigUrl $VoiceRigUrl `
        -ModelRigUrl $ModelRigUrl `
        -ModelRigWorkerUrl $ModelRigWorkerUrl `
        -ModelRigToken $ModelRigToken `
        -Report (Join-Path $PSScriptRoot "piper-fallback-report.json")
    $Code = $LASTEXITCODE
}

Write-Host ""
if ($Code -eq 0) {
    if ($RequirePiperFallback) {
        Write-Host "VoiceRig-valideringen bestod inkl. ModelRig, rigtig Piper fallback-WAV og VoiceRig restore."
    } else {
        Write-Host "VoiceRig-valideringen bestod."
    }
} else {
    Write-Host "VoiceRig-valideringen fandt en blocker. Se validation-report.json og evt. piper-fallback-report.json."
}
exit $Code
