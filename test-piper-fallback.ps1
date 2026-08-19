param(
    [string]$VoiceRigUrl = "http://127.0.0.1:8765",
    [string]$ModelRigUrl = "http://127.0.0.1:8080",
    [string]$ModelRigWorkerUrl = "http://127.0.0.1:8099",
    [string]$ModelRigToken = $env:MODELRIG_TOKEN,
    [string]$Report = (Join-Path $PSScriptRoot "piper-fallback-report.json")
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$WorkerUri = [Uri]$ModelRigWorkerUrl
if ($WorkerUri.Scheme -ne "http" -or $WorkerUri.Host -notin @("127.0.0.1", "localhost", "::1")) {
    throw "Piper fallback-testen må kun kalde ModelRig-worker på loopback."
}

function Get-VoiceRigHealth {
    try {
        return Invoke-RestMethod -Uri ($VoiceRigUrl.TrimEnd('/') + "/api/health") -TimeoutSec 3
    } catch {
        return $null
    }
}

function Get-ModelRigHealth {
    if (-not $ModelRigToken) {
        throw "MODELRIG_TOKEN mangler. Piper fallback acceptance bruger ModelRigs autentificerede backend."
    }
    $Headers = @{ Authorization = "Bearer $ModelRigToken" }
    return Invoke-RestMethod -Uri ($ModelRigUrl.TrimEnd('/') + "/api/v1/health/full") -Headers $Headers -TimeoutSec 8
}

function Get-TtsStatus($Health) {
    if (-not $Health -or -not $Health.checks -or -not $Health.checks.tts) {
        throw "ModelRig health/full mangler checks.tts."
    }
    return $Health.checks.tts
}

function Wait-VoiceRigDown {
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 250
        if (-not (Get-VoiceRigHealth)) { return }
    }
    throw "VoiceRig-service stoppede ikke inden for 10 sekunder."
}

function Wait-VoiceRigReady([string]$ExpectedRevision) {
    for ($i = 0; $i -lt 120; $i++) {
        Start-Sleep -Milliseconds 250
        $Health = Get-VoiceRigHealth
        if ($Health -and $Health.ok -eq $true -and $Health.service -eq "voicerig") {
            if (-not $Health.source -or $Health.source.revision -ne $ExpectedRevision) {
                throw "Genstartet VoiceRig kører forkert Git HEAD. Forventede $ExpectedRevision, fik $($Health.source.revision)."
            }
            if ($Health.source.dirty -ne $false) {
                throw "Genstartet VoiceRig rapporterer et dirty checkout."
            }
            return $Health
        }
    }
    throw "VoiceRig-service blev ikke klar igen inden for 30 sekunder."
}

function Wait-ModelRigProvider([string]$Provider) {
    $Last = $null
    for ($i = 0; $i -lt 40; $i++) {
        try {
            $Last = Get-TtsStatus (Get-ModelRigHealth)
            if ($Last.ok -eq $true -and $Last.provider -eq $Provider) { return $Last }
        } catch {
            $Last = $null
        }
        Start-Sleep -Milliseconds 500
    }
    $Actual = if ($Last) { $Last.provider } else { "ukendt" }
    throw "ModelRig skiftede ikke til provider '$Provider'. Seneste provider: '$Actual'."
}

function Invoke-PiperSynthesis {
    $OutDir = Join-Path $PSScriptRoot "validation-output"
    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
    $Output = Join-Path $OutDir "piper-fallback.wav"
    Remove-Item -LiteralPath $Output -Force -ErrorAction SilentlyContinue

    $Body = @{
        text = "Hej. Dette er ModelRigs automatiske Piper fallback-test."
        out_path = $Output
    } | ConvertTo-Json

    $Result = Invoke-RestMethod `
        -Uri ($ModelRigWorkerUrl.TrimEnd('/') + "/voice/tts/synthesize") `
        -Method Post `
        -ContentType "application/json" `
        -Body $Body `
        -TimeoutSec 120

    if (-not $Result -or $Result.provider -ne "piper") {
        throw "ModelRig-worker syntetiserede ikke fallback-testen med Piper."
    }
    if (-not (Test-Path -LiteralPath $Output)) {
        throw "Piper rapporterede succes, men fallback-WAV blev ikke skrevet."
    }
    $Info = Get-Item -LiteralPath $Output
    if ($Info.Length -le 44) {
        throw "Piper fallback-WAV er tom eller for kort til at være gyldig."
    }
    $Bytes = [System.IO.File]::ReadAllBytes($Output)
    $Magic = [System.Text.Encoding]::ASCII.GetString($Bytes, 0, 4)
    if ($Magic -ne "RIFF") {
        throw "Piper fallback-output er ikke en RIFF/WAV-fil."
    }

    return [ordered]@{
        provider = $Result.provider
        voice = $Result.voice
        sample_rate = $Result.sample_rate
        duration = $Result.duration
        output = $Output
        bytes = $Info.Length
        riff = $true
    }
}

$CheckoutRevision = (& git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or -not $CheckoutRevision) {
    throw "Kunne ikke aflæse VoiceRig Git HEAD."
}
$Dirty = (& git status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "Kunne ikke aflæse VoiceRig Git status." }
if ($Dirty) { throw "Piper fallback acceptance kræver et clean VoiceRig-checkout." }

$Initial = Get-VoiceRigHealth
if (-not $Initial -or $Initial.ok -ne $true -or $Initial.service -ne "voicerig" -or -not $Initial.pid) {
    throw "VoiceRig-service skal køre og identificere sig selv før fallback-testen."
}
if (-not $Initial.source -or $Initial.source.revision -ne $CheckoutRevision -or $Initial.source.dirty -ne $false) {
    throw "Den aktive VoiceRig-service matcher ikke det clean checkout, der testes."
}

$Before = Wait-ModelRigProvider "voicerig"
$VoiceRigExe = (Resolve-Path ".venv\Scripts\voicerig.exe").Path
$StoppedPid = [int]$Initial.pid
$Restarted = $false
$Fallback = $null
$PiperSynthesis = $null
$Restored = $null
$RestartedHealth = $null
$Failure = $null

try {
    Write-Host "Stopper verificeret VoiceRig PID $StoppedPid for at bevise Piper fallback..."
    Stop-Process -Id $StoppedPid -Force -ErrorAction Stop
    Wait-VoiceRigDown

    $Fallback = Wait-ModelRigProvider "piper"
    $PiperSynthesis = Invoke-PiperSynthesis
    Write-Host "ModelRig fallback: PASS (provider=piper + rigtig WAV)"
} catch {
    $Failure = $_.Exception.Message
} finally {
    if (-not (Get-VoiceRigHealth)) {
        Write-Host "Starter VoiceRig igen fra samme checkout..."
        Start-Process -FilePath $VoiceRigExe -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
    }
    try {
        $RestartedHealth = Wait-VoiceRigReady $CheckoutRevision
        $Restarted = $true
        $Restored = Wait-ModelRigProvider "voicerig"
        Write-Host "VoiceRig restore: PASS (provider=voicerig)"
    } catch {
        if (-not $Failure) { $Failure = $_.Exception.Message }
        else { $Failure = $Failure + " | Restore-fejl: " + $_.Exception.Message }
    }
}

$Result = [ordered]@{
    ok = (-not $Failure -and $Fallback -and $Fallback.ok -eq $true -and $Fallback.provider -eq "piper" -and $PiperSynthesis -and $PiperSynthesis.provider -eq "piper" -and $PiperSynthesis.riff -eq $true -and $Restarted -and $Restored -and $Restored.ok -eq $true -and $Restored.provider -eq "voicerig")
    checkout_revision = $CheckoutRevision
    stopped_voicerig_pid = $StoppedPid
    before = $Before
    fallback = $Fallback
    piper_synthesis = $PiperSynthesis
    restarted = $Restarted
    restarted_service_pid = if ($RestartedHealth) { $RestartedHealth.pid } else { $null }
    restarted_service_revision = if ($RestartedHealth -and $RestartedHealth.source) { $RestartedHealth.source.revision } else { $null }
    restored = $Restored
    error = $Failure
}

$Result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $Report -Encoding utf8

if (-not $Result.ok) {
    Write-Host "Piper fallback acceptance: FAIL"
    Write-Host "ERROR: $Failure"
    Write-Host "Report: $Report"
    exit 1
}

Write-Host "Piper fallback acceptance: PASS"
Write-Host "Piper WAV: $($PiperSynthesis.output)"
Write-Host "Report: $Report"
exit 0
