$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    throw "FFmpeg blev ikke fundet på PATH. Installér FFmpeg først."
}

# Prefer a known-good Python for the ML stack instead of silently building the
# environment with whatever `python.exe` happens to be first on PATH.
$Python = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3.11 -c "import sys; assert sys.version_info[:2] == (3, 11)" 2>$null
    if ($LASTEXITCODE -eq 0) { $Python = @("py", "-3.11") }
}
if (-not $Python -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $Version = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($Version -eq "3.11" -or $Version -eq "3.12") { $Python = @("python") }
}
if (-not $Python) {
    throw "VoiceRig kræver Python 3.11 (anbefalet) eller 3.12. Installér Python 3.11 og prøv igen."
}

if (-not (Test-Path ".venv")) {
    if ($Python.Count -eq 2) { & $Python[0] $Python[1] -m venv .venv }
    else { & $Python[0] -m venv .venv }
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[voice]"

Write-Host ""
Write-Host "VoiceRig er installeret."
Write-Host "Standard GPU-plan: Chatterbox bruger CUDA; pyannote bruger CPU for at spare VRAM."
Write-Host "Hvis pyannote-modellen ikke er hentet endnu, sæt HF_TOKEN før første speaker-analyse."
Write-Host "Start med: .\start-windows.ps1"
