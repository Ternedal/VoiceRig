param(
    [switch]$RemoveData,
    [switch]$KeepSecrets
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

function Get-VoiceRigDataRoot {
    # Resolve storage through VoiceRig itself before deleting .venv. This honors
    # .env, legacy migration and future config rules instead of duplicating them
    # in PowerShell.
    $MainPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $MainPy) {
        $Output = @(& $MainPy -c "from voicerig.config import data_dir; print(data_dir())" 2>$null)
        if ($LASTEXITCODE -eq 0 -and $Output.Count -gt 0) {
            $Value = [string]$Output[-1]
            if (-not [string]::IsNullOrWhiteSpace($Value)) {
                return $Value.Trim()
            }
        }
    }

    # Fallback is intentionally conservative for already-broken/partial
    # installations. An explicit process environment path still wins; otherwise
    # use the documented stable Windows default.
    if (-not [string]::IsNullOrWhiteSpace($env:VOICERIG_DATA_DIR)) {
        return $env:VOICERIG_DATA_DIR
    }
    if ($env:LOCALAPPDATA) {
        return (Join-Path $env:LOCALAPPDATA "VoiceRig")
    }
    return (Join-Path $HOME "AppData\Local\VoiceRig")
}

function Clear-VoiceRigSecrets {
    $EnvPath = Join-Path $PSScriptRoot ".env"
    if (Test-Path -LiteralPath $EnvPath) {
        $Lines = @(Get-Content -LiteralPath $EnvPath)
        for ($i = 0; $i -lt $Lines.Count; $i++) {
            if ($Lines[$i] -match '^\s*HF_TOKEN\s*=') {
                $Lines[$i] = 'HF_TOKEN='
            } elseif ($Lines[$i] -match '^\s*MODELRIG_TOKEN\s*=') {
                $Lines[$i] = 'MODELRIG_TOKEN='
            }
        }
        $Temp = "$EnvPath.tmp"
        [System.IO.File]::WriteAllLines(
            $Temp,
            [string[]]$Lines,
            [System.Text.UTF8Encoding]::new($false)
        )
        Move-Item -LiteralPath $Temp -Destination $EnvPath -Force
    }

    # Clear only this process' copies. VoiceRig never owns or removes unrelated
    # user/machine-level environment variables configured outside the product.
    $env:HF_TOKEN = $null
    $env:MODELRIG_TOKEN = $null
}

$DataRoot = $null
if ($RemoveData) {
    $DataRoot = Get-VoiceRigDataRoot
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

if (-not $KeepSecrets) {
    Clear-VoiceRigSecrets
    Write-Host "Lokale VoiceRig-secrets (HF_TOKEN og MODELRIG_TOKEN) er ryddet fra .env."
} else {
    Write-Warning "Lokale VoiceRig-secrets bevares i .env efter eksplicit -KeepSecrets."
}

foreach ($Path in @(".venv", ".venv-diarization")) {
    $Full = Join-Path $PSScriptRoot $Path
    if (Test-Path -LiteralPath $Full) {
        Write-Host "Fjerner $Path..."
        Remove-Item -LiteralPath $Full -Recurse -Force
    }
}

if ($RemoveData) {
    if (-not [string]::IsNullOrWhiteSpace($DataRoot) -and (Test-Path -LiteralPath $DataRoot)) {
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
