$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot

$Exe = ".venv\Scripts\voicerig.exe"
if (-not (Test-Path -LiteralPath $Exe)) {
    throw "VoiceRig er ikke installeret endnu. Kør .\install-windows.ps1 først."
}

function Get-VoiceRigHealth {
    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 1
    } catch {
        return $null
    }
}

$Health = Get-VoiceRigHealth
if ($Health) {
    if ($Health.ok -ne $true -or $Health.service -ne "voicerig") {
        throw "Port 8765 svarer, men servicen identificerer sig ikke som VoiceRig. VoiceRig starter ikke oven i en fremmed lokal service."
    }
} else {
    Start-Process -FilePath (Resolve-Path $Exe).Path -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
    $Ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 250
        $Health = Get-VoiceRigHealth
        if ($Health -and $Health.ok -eq $true -and $Health.service -eq "voicerig") {
            $Ready = $true
            break
        }
    }
    if (-not $Ready) {
        throw "VoiceRig startede ikke korrekt. Hent en supportpakke efter manuel start, eller kør .\install-windows.ps1 for at reparere installationen."
    }
}

Start-Process "http://127.0.0.1:8765/"
Write-Host "VoiceRig kører lokalt og UI er åbnet i browseren."
