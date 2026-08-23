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

function Get-ProcessExecutablePath($Process) {
    try {
        if ($Process.Path) { return [string]$Process.Path }
    } catch {
        # Fall back to CIM below.
    }
    try {
        $Cim = Get-CimInstance Win32_Process -Filter "ProcessId = $($Process.Id)" -ErrorAction Stop
        if ($Cim -and $Cim.ExecutablePath) { return [string]$Cim.ExecutablePath }
    } catch {
        return $null
    }
    return $null
}

function Test-SamePath([string]$Left, [string]$Right) {
    if ([string]::IsNullOrWhiteSpace($Left) -or [string]::IsNullOrWhiteSpace($Right)) { return $false }
    try {
        return [string]::Equals(
            [System.IO.Path]::GetFullPath($Left).TrimEnd('\'),
            [System.IO.Path]::GetFullPath($Right).TrimEnd('\'),
            [System.StringComparison]::OrdinalIgnoreCase
        )
    } catch {
        return $false
    }
}

function Stop-CurrentCheckoutVoiceRig {
    $LocalExe = Join-Path $PSScriptRoot ".venv\Scripts\voicerig.exe"
    $LocalPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    $StoppedIds = @{}

    $Health = Get-VoiceRigHealth
    if ($Health) {
        if ($Health.ok -ne $true -or $Health.service -ne "voicerig" -or -not $Health.pid) {
            Write-Warning "Port 8765 svarer, men er ikke en sikkert identificeret VoiceRig. Processen røres ikke."
        } else {
            $HealthPid = [int]$Health.pid
            $SameCheckout = $false
            if ($Health.source -and $Health.source.root) {
                $SameCheckout = Test-SamePath ([string]$Health.source.root) $PSScriptRoot
            } elseif ((Test-Path -LiteralPath $LocalExe) -or (Test-Path -LiteralPath $LocalPython)) {
                # Legacy bridge for RC2-RC6, which did not expose source.root.
                try {
                    $HealthProcess = Get-Process -Id $HealthPid -ErrorAction Stop
                    $HealthPath = Get-ProcessExecutablePath $HealthProcess
                    $SameCheckout = (Test-SamePath $HealthPath $LocalExe) -or (Test-SamePath $HealthPath $LocalPython)
                } catch {
                    $SameCheckout = $false
                }
            }

            if ($SameCheckout) {
                if ($HealthPid -ne $PID) {
                    Write-Host "Stopper VoiceRig-service fra denne checkout, PID $HealthPid..."
                    Stop-Process -Id $HealthPid -Force -ErrorAction Stop
                    $StoppedIds[$HealthPid] = $true
                }
            } else {
                Write-Warning "En VoiceRig-service fra en anden checkout kører på port 8765. Den røres ikke af denne uninstall."
            }
        }
    }

    # A distlib launcher can survive after its Python child is stopped and keep
    # voicerig.exe locked. Remove only the launcher belonging to this checkout.
    foreach ($Candidate in @(Get-Process -Name "voicerig" -ErrorAction SilentlyContinue)) {
        if ($StoppedIds.ContainsKey([int]$Candidate.Id)) { continue }
        $CandidatePath = Get-ProcessExecutablePath $Candidate
        if (Test-SamePath $CandidatePath $LocalExe) {
            Write-Host "Stopper lokal VoiceRig-launcher PID $($Candidate.Id)..."
            Stop-Process -Id ([int]$Candidate.Id) -Force -ErrorAction Stop
            $StoppedIds[[int]$Candidate.Id] = $true
        }
    }

    foreach ($StoppedPid in @($StoppedIds.Keys)) {
        $Exited = $false
        for ($i = 0; $i -lt 40; $i++) {
            if (-not (Get-Process -Id ([int]$StoppedPid) -ErrorAction SilentlyContinue)) {
                $Exited = $true
                break
            }
            Start-Sleep -Milliseconds 250
        }
        if (-not $Exited) {
            throw "VoiceRig-proces PID $StoppedPid stoppede ikke inden for 10 sekunder; runtime-filerne slettes ikke."
        }
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

Stop-CurrentCheckoutVoiceRig

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

Write-Host "VoiceRig runtime og denne checkouts autostart er fjernet. Repo-filerne er ikke slettet."
