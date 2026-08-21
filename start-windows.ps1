$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot

$Exe = ".venv\Scripts\voicerig.exe"
if (-not (Test-Path -LiteralPath $Exe)) {
    throw "VoiceRig er ikke installeret endnu. Kør .\install-windows.ps1 først."
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git mangler. Kør .\install-windows.ps1 for at reparere installationen."
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

function Get-VoiceRigHealth {
    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 1
    } catch {
        return $null
    }
}

$ExpectedHead = (& git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or -not $ExpectedHead) {
    throw "Kunne ikke aflæse VoiceRig Git HEAD."
}
$Dirty = (& git status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "Kunne ikke aflæse VoiceRig Git-status." }
if ($Dirty) {
    throw "VoiceRig-checkoutet har lokale ændringer. Produktstart kræver et clean checkout; commit/stash ændringerne eller kør udviklingsserveren manuelt."
}

function Assert-CurrentVoiceRigHealth($Health) {
    if (-not $Health -or $Health.ok -ne $true -or $Health.service -ne "voicerig") {
        throw "Port 8765 svarer, men servicen identificerer sig ikke sikkert som VoiceRig. VoiceRig starter ikke oven i en fremmed lokal service."
    }
    if (-not $Health.source -or -not $Health.source.root -or -not (Test-SamePath ([string]$Health.source.root) $PSScriptRoot)) {
        throw "En VoiceRig-service kører allerede på port 8765, men den tilhører en anden checkout. Stop den anden VoiceRig eller kør dens egen start/stop-flow."
    }
    if ($Health.source.revision -ne $ExpectedHead -or $Health.source.dirty -ne $false) {
        throw "Den kørende VoiceRig-proces tilhører denne checkout, men blev startet fra en anden eller dirty Git-tilstand. Kør .\install-windows.ps1 for at genstarte den verificerede runtime."
    }
}

$Health = Get-VoiceRigHealth
if ($Health) {
    Assert-CurrentVoiceRigHealth $Health
} else {
    Start-Process -FilePath (Resolve-Path $Exe).Path -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
    $Ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 250
        $Health = Get-VoiceRigHealth
        if ($Health -and $Health.ok -eq $true -and $Health.service -eq "voicerig") {
            Assert-CurrentVoiceRigHealth $Health
            $Ready = $true
            break
        }
    }
    if (-not $Ready) {
        throw "VoiceRig startede ikke korrekt. Hent en supportpakke efter manuel start, eller kør .\install-windows.ps1 for at reparere installationen."
    }
}

Start-Process "http://127.0.0.1:8765/"
Write-Host "VoiceRig kører lokalt fra den verificerede checkout og UI er åbnet i browseren."
