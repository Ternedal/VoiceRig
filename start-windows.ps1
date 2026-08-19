$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$exe = ".venv\Scripts\voicerig.exe"
if (-not (Test-Path $exe)) {
    throw "VoiceRig er ikke installeret endnu. Kør .\setup-windows.ps1 først."
}

function Test-VoiceRig {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 1
        return ($r.ok -eq $true)
    } catch {
        return $false
    }
}

if (-not (Test-VoiceRig)) {
    Start-Process -FilePath (Resolve-Path $exe).Path -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 250
        if (Test-VoiceRig) { $ready = $true; break }
    }
    if (-not $ready) {
        throw "VoiceRig startede ikke korrekt. Se log/terminal ved manuel start."
    }
}

Start-Process "http://127.0.0.1:8765/"
Write-Host "VoiceRig kører lokalt og UI er åbnet i browseren."
