param(
    [switch]$RemoveData
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot

function Get-VoiceRigHealth {
    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 2
    } catch {
        return $null
    }
}

$Health = Get-VoiceRigHealth
if ($Health -and $Health.ok -eq $true -and $Health.service -eq "voicerig" -and $Health.pid) {
    $VoiceRigPid = [int]$Health.pid
    if ($VoiceRigPid -ne $PID) {
        Write-Host "Stopper VoiceRig service PID $VoiceRigPid..."
        Stop-Process -Id $VoiceRigPid -Force -ErrorAction Stop
    }
}

& (Join-Path $PSScriptRoot "uninstall-autostart.ps1")

foreach ($Path in @(".venv", ".venv-diarization")) {
    $Full = Join-Path $PSScriptRoot $Path
    if (Test-Path -LiteralPath $Full) {
        Write-Host "Fjerner $Path..."
        Remove-Item -LiteralPath $Full -Recurse -Force
    }
}

if ($RemoveData) {
    $DataRoot = $env:VOICERIG_DATA_DIR
    if (-not $DataRoot) {
        if ($env:LOCALAPPDATA) {
            $DataRoot = Join-Path $env:LOCALAPPDATA "VoiceRig"
        } else {
            $DataRoot = Join-Path $HOME "AppData\Local\VoiceRig"
        }
    }
    if (Test-Path -LiteralPath $DataRoot) {
        Write-Host "Fjerner VoiceRig brugerdata: $DataRoot"
        Remove-Item -LiteralPath $DataRoot -Recurse -Force
    }
    $Legacy = Join-Path $PSScriptRoot "voicerig-data"
    if (Test-Path -LiteralPath $Legacy) {
        Remove-Item -LiteralPath $Legacy -Recurse -Force
    }
} else {
    Write-Host "Brugerdata og stemmeprofiler er bevaret. Brug -RemoveData hvis de også skal slettes."
}

Write-Host "VoiceRig runtime og autostart er fjernet. Repo-filerne er ikke slettet."
