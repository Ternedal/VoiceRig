param(
    [switch]$SkipModelWarmup
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    throw "FFmpeg blev ikke fundet på PATH. Installér FFmpeg først."
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git blev ikke fundet på PATH. VoiceRig installerer den verificerede Chatterbox V3-kilde fra GitHub og kræver Git."
}

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Oprettede .env fra .env.example. HF_TOKEN kan sættes her ved første pyannote-download."
}

# Chatterbox is upstream-tested on Python 3.11, and pyannote also supports it.
# Use one exact interpreter for both isolated environments so Windows launcher
# order cannot silently change the runtime under us.
$Python = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3.11 -c "import sys; assert sys.version_info[:2] == (3, 11)" 2>$null
    if ($LASTEXITCODE -eq 0) { $Python = @("py", "-3.11") }
}
if (-not $Python -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $Version = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($Version -eq "3.11") { $Python = @("python") }
}
if (-not $Python) {
    throw "VoiceRig kræver Python 3.11. Installér Python 3.11 og prøv igen."
}

function New-Venv([string]$Path) {
    if (-not (Test-Path $Path)) {
        if ($Python.Count -eq 2) { & $Python[0] $Python[1] -m venv $Path }
        else { & $Python[0] -m venv $Path }
        if ($LASTEXITCODE -ne 0) { throw "Kunne ikke oprette $Path" }
    }
}

# ---------------------------------------------------------------------------
# Main VoiceRig runtime: verified Chatterbox Multilingual V3 source revision +
# explicit CUDA-enabled PyTorch 2.6.0. Installing the official cu126 wheels
# first prevents pip on Windows from silently landing on CPU-only torch.
# ---------------------------------------------------------------------------
New-Venv ".venv"
$MainPy = ".\.venv\Scripts\python.exe"
& $MainPy -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw "Kunne ikke opdatere pip i VoiceRig-miljøet." }

$CudaReady = $false
& $MainPy -c "import torch,sys; sys.exit(0 if torch.__version__.startswith('2.6.0') and torch.cuda.is_available() else 1)" 2>$null
if ($LASTEXITCODE -eq 0) { $CudaReady = $true }
if (-not $CudaReady) {
    Write-Host "Installerer PyTorch 2.6.0 med CUDA 12.6 support..."
    & $MainPy -m pip install --upgrade --force-reinstall `
        torch==2.6.0 torchaudio==2.6.0 `
        --index-url https://download.pytorch.org/whl/cu126
    if ($LASTEXITCODE -ne 0) { throw "CUDA-PyTorch kunne ikke installeres." }
}

& $MainPy -m pip install -e ".[voice]"
if ($LASTEXITCODE -ne 0) { throw "Chatterbox/VoiceRig kunne ikke installeres." }

& $MainPy -c "import torch; assert torch.cuda.is_available(), 'CUDA unavailable'; p=torch.cuda.get_device_properties(0); print(f'GPU OK: {p.name} | VRAM {p.total_memory/1024**3:.1f} GB | torch {torch.__version__}')"
if ($LASTEXITCODE -ne 0) {
    throw "VoiceRig fandt ikke en fungerende CUDA-GPU efter installationen."
}

# ---------------------------------------------------------------------------
# Diarization runtime: current pyannote requires torch >=2.8, which conflicts
# with Chatterbox's exact torch 2.6 pin. Keep it in a separate CPU-only venv.
# This also guarantees that speaker analysis cannot consume GPU VRAM.
# ---------------------------------------------------------------------------
New-Venv ".venv-diarization"
$DiarPy = ".\.venv-diarization\Scripts\python.exe"
& $DiarPy -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw "Kunne ikke opdatere pip i diarization-miljøet." }

$DiarReady = $false
& $DiarPy -c "import pyannote.audio,torch,sys; sys.exit(0 if not torch.cuda.is_available() else 1)" 2>$null
if ($LASTEXITCODE -eq 0) { $DiarReady = $true }
if (-not $DiarReady) {
    Write-Host "Installerer separat CPU-runtime til speaker-analyse..."
    & $DiarPy -m pip install --upgrade torch torchaudio --index-url https://download.pytorch.org/whl/cpu
    if ($LASTEXITCODE -ne 0) { throw "CPU-PyTorch til diarization kunne ikke installeres." }
    & $DiarPy -m pip install "pyannote.audio>=4.0.7,<5"
    if ($LASTEXITCODE -ne 0) { throw "pyannote.audio kunne ikke installeres." }
}

& $DiarPy -c "import pyannote.audio,torch; assert not torch.cuda.is_available(); print(f'pyannote CPU runtime OK | torch {torch.__version__}')"
if ($LASTEXITCODE -ne 0) { throw "Det separate pyannote CPU-miljø er ikke funktionsdygtigt." }

# Download and actually load both ML stacks now. This makes setup fail early
# with an actionable error instead of turning the first 'Opret stemme' click
# into an implicit model installation.
if (-not $SkipModelWarmup) {
    Write-Host ""
    Write-Host "Henter og verificerer Chatterbox V3 + pyannote community-1..."
    & $MainPy -m voicerig.model_warmup
    if ($LASTEXITCODE -ne 0) {
        throw "Model-warmup fejlede. Hvis pyannote mangler adgang: acceptér community-1-vilkårene, sæt HF_TOKEN i .env og kør setup-windows.ps1 igen."
    }
} else {
    Write-Warning "Model-warmup er sprunget over. Første voice-build kan derfor skulle hente modeller."
}

& .\install-autostart.ps1

function Test-VoiceRig {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 1
        return ($r.ok -eq $true)
    } catch {
        return $false
    }
}
if (-not (Test-VoiceRig)) {
    Start-Process -FilePath (Resolve-Path ".venv\Scripts\voicerig.exe").Path -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
}

Write-Host ""
Write-Host "VoiceRig er installeret, modellerne er verificeret og autostart er sat for din Windows-bruger."
Write-Host "GPU-plan: Chatterbox V3 = CUDA i .venv; pyannote = CPU i .venv-diarization."
Write-Host "Åbn VoiceRig med: .\start-windows.ps1"
