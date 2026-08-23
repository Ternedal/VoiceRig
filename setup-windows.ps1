param(
    [switch]$SkipModelWarmup
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Test-NativeCommand([string]$FilePath, [string[]]$Arguments) {
    $PreviousPreference = $ErrorActionPreference
    try {
        # Windows PowerShell 5.1 converts native stderr into PowerShell error
        # records. With ErrorActionPreference=Stop an expected probe failure
        # (for example importing torch before it is installed) becomes a
        # terminating NativeCommandError before LASTEXITCODE can be checked.
        $ErrorActionPreference = "Continue"
        & $FilePath @Arguments *> $null
        return ($LASTEXITCODE -eq 0)
    } finally {
        $ErrorActionPreference = $PreviousPreference
    }
}

function Get-ProcessExecutablePath($Process) {
    try {
        if ($Process.Path) { return [string]$Process.Path }
    } catch {
        # Fall back to CIM below. Accessing Process.Path can fail on some hosts.
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

function Stop-LocalVoiceRigForRuntimeMutation(
    [string]$ExpectedExe,
    [string]$ExpectedPython,
    [string]$ExpectedRoot
) {
    $ExpectedFull = [System.IO.Path]::GetFullPath($ExpectedExe)
    $ExpectedPythonFull = [System.IO.Path]::GetFullPath($ExpectedPython)
    $ExpectedRootFull = [System.IO.Path]::GetFullPath($ExpectedRoot)
    $StoppedIds = @{}

    $Health = $null
    try {
        $Health = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 2
    } catch {
        $Health = $null
    }

    if ($Health) {
        if ($Health.ok -ne $true -or $Health.service -ne "voicerig" -or -not $Health.pid) {
            throw "Port 8765 svarer, men processen identificerer sig ikke sikkert som VoiceRig. Runtime-installationen stopper uden at røre processen."
        }

        $HealthPid = [int]$Health.pid
        $HealthProcess = Get-Process -Id $HealthPid -ErrorAction Stop
        $SameCheckout = $false

        # New VoiceRig versions report the resolved checkout root directly.
        # This is the primary identity because it is independent of how the
        # Windows console-script launcher happens to spawn Python.
        if ($Health.source -and $Health.source.root) {
            $SameCheckout = Test-SamePath ([string]$Health.source.root) $ExpectedRootFull
        } else {
            # Backward-compatible bridge for an already running RC2-RC6
            # service: distlib may expose either voicerig.exe or this venv's
            # python.exe as the HTTP PID. Both paths uniquely identify this
            # checkout's private virtual environment.
            $HealthPath = Get-ProcessExecutablePath $HealthProcess
            $SameCheckout = (Test-SamePath $HealthPath $ExpectedFull) -or
                (Test-SamePath $HealthPath $ExpectedPythonFull)
        }

        if (-not $SameCheckout) {
            throw "En VoiceRig-service svarer på port 8765, men den kører ikke fra denne checkout. Runtime-installationen stopper uden at røre processen."
        }

        Write-Host "Stopper eksisterende lokal VoiceRig-service PID $HealthPid før runtime-opdatering..."
        if ($HealthPid -ne $PID) {
            Stop-Process -Id $HealthPid -Force -ErrorAction Stop
            $StoppedIds[$HealthPid] = $true
        }
    }

    # A previous failed install can leave the distlib launcher alive after its
    # Python child stops. Stop only the launcher whose executable path is
    # exactly this checkout's .venv\Scripts\voicerig.exe.
    foreach ($Candidate in @(Get-Process -Name "voicerig" -ErrorAction SilentlyContinue)) {
        if ($StoppedIds.ContainsKey([int]$Candidate.Id)) { continue }
        $CandidatePath = Get-ProcessExecutablePath $Candidate
        if (Test-SamePath $CandidatePath $ExpectedFull) {
            Write-Host "Stopper hængende lokal VoiceRig-launcher PID $($Candidate.Id) før runtime-opdatering..."
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
            throw "VoiceRig-proces PID $StoppedPid frigav ikke runtime-filerne inden for 10 sekunder."
        }
    }
}

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

$Python = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    if (Test-NativeCommand -FilePath "py" -Arguments @("-3.11", "-c", "import sys; assert sys.version_info[:2] == (3, 11)")) {
        $Python = @("py", "-3.11")
    }
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

New-Venv ".venv"
$MainPy = ".\.venv\Scripts\python.exe"
$VoiceRigExePath = Join-Path $PSScriptRoot ".venv\Scripts\voicerig.exe"
$MainPythonPath = (Resolve-Path $MainPy).Path
Stop-LocalVoiceRigForRuntimeMutation $VoiceRigExePath $MainPythonPath $PSScriptRoot

& $MainPy -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw "Kunne ikke opdatere pip i VoiceRig-miljøet." }

$CudaReady = Test-NativeCommand -FilePath $MainPy -Arguments @(
    "-c",
    "import torch,sys; sys.exit(0 if torch.__version__.startswith('2.6.0') and torch.cuda.is_available() else 1)"
)
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
if ($LASTEXITCODE -ne 0) { throw "VoiceRig fandt ikke en fungerende CUDA-GPU efter installationen." }

New-Venv ".venv-diarization"
$DiarPy = ".\.venv-diarization\Scripts\python.exe"
& $DiarPy -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw "Kunne ikke opdatere pip i diarization-miljøet." }

# Version probes deliberately use importlib.metadata instead of importing
# pyannote.audio. Importing the package triggers TorchCodec's optional Windows
# FFmpeg-DLL discovery even though VoiceRig feeds pyannote in-memory PCM16 and
# never uses TorchCodec for decoding.
$DiarReady = Test-NativeCommand -FilePath $DiarPy -Arguments @(
    "-c",
    "import importlib.metadata as m,torch,torchaudio,sys; ok=(m.version('pyannote.audio')=='4.0.7' and torch.__version__.startswith('2.8.0') and torchaudio.__version__.startswith('2.8.0') and m.version('torchcodec')=='0.7.0' and not torch.cuda.is_available()); sys.exit(0 if ok else 1)"
)
if (-not $DiarReady) {
    Write-Host "Installerer verificeret CPU-runtime til speaker-analyse..."
    & $DiarPy -m pip install --upgrade --force-reinstall `
        torch==2.8.0 torchaudio==2.8.0 torchcodec==0.7.0 `
        --index-url https://download.pytorch.org/whl/cpu
    if ($LASTEXITCODE -ne 0) { throw "CPU-PyTorch/TorchCodec til diarization kunne ikke installeres." }
    & $DiarPy -m pip install "pyannote.audio==4.0.7"
    if ($LASTEXITCODE -ne 0) { throw "pyannote.audio 4.0.7 kunne ikke installeres." }
}

& $DiarPy -c "import importlib.metadata as m,torch,torchaudio; assert m.version('pyannote.audio')=='4.0.7'; assert torch.__version__.startswith('2.8.0'); assert torchaudio.__version__.startswith('2.8.0'); assert m.version('torchcodec')=='0.7.0'; assert not torch.cuda.is_available(); print('pyannote {} CPU runtime OK | torch {} | torchaudio {} | torchcodec {}'.format(m.version('pyannote.audio'), torch.__version__, torchaudio.__version__, m.version('torchcodec')))"
if ($LASTEXITCODE -ne 0) { throw "Det separate pyannote CPU-miljø matcher ikke den verificerede runtime-kontrakt." }

if (-not $SkipModelWarmup) {
    Write-Host ""
    Write-Host "Henter og verificerer Chatterbox V3 + pyannote community-1..."
    & $MainPy -m voicerig.model_warmup
    if ($LASTEXITCODE -ne 0) {
        throw "Model-warmup fejlede. Hvis pyannote mangler adgang: acceptér community-1-vilkårene, sæt HF_TOKEN i .env og kør setup-windows.ps1 igen."
    }
} else {
    Write-Warning "Model-warmup er sprunget over. Voice creation forbliver låst indtil setup køres med model-warmup."
}

& .\install-autostart.ps1

function Get-VoiceRigHealth {
    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 2
    } catch {
        return $null
    }
}

# An editable install can change underneath an already running Python process.
# Always restart a service that positively identifies itself as VoiceRig so the
# process serving ModelRig is guaranteed to use the freshly installed checkout.
$Existing = Get-VoiceRigHealth
if ($Existing -and $Existing.ok -eq $true -and $Existing.service -eq "voicerig" -and $Existing.pid) {
    $ExistingPid = [int]$Existing.pid
    if ($ExistingPid -ne $PID) {
        Write-Host "Genstarter eksisterende VoiceRig-proces PID $ExistingPid efter opdatering..."
        Stop-Process -Id $ExistingPid -Force -ErrorAction Stop
        for ($i = 0; $i -lt 40; $i++) {
            Start-Sleep -Milliseconds 250
            if (-not (Get-VoiceRigHealth)) { break }
        }
    }
}

$VoiceRigExe = (Resolve-Path ".venv\Scripts\voicerig.exe").Path
Start-Process -FilePath $VoiceRigExe -WorkingDirectory $PSScriptRoot -WindowStyle Hidden

$Ready = $null
for ($i = 0; $i -lt 80; $i++) {
    Start-Sleep -Milliseconds 250
    $Ready = Get-VoiceRigHealth
    if ($Ready -and $Ready.ok -eq $true -and $Ready.service -eq "voicerig") { break }
}
if (-not $Ready -or $Ready.ok -ne $true) {
    throw "VoiceRig kunne ikke startes efter installationen. Kør .\start-windows.ps1 manuelt for fejldetaljer."
}

$ExpectedHead = (& git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw "Kunne ikke aflæse Git HEAD efter installationen." }
if (-not $Ready.source -or $Ready.source.revision -ne $ExpectedHead) {
    throw "VoiceRig-processen kører ikke den installerede Git HEAD. Forventede $ExpectedHead, fik $($Ready.source.revision)."
}
if (-not $Ready.source.root -or -not (Test-SamePath ([string]$Ready.source.root) $PSScriptRoot)) {
    throw "VoiceRig-processen rapporterer ikke den installerede checkout-root efter installationen."
}

Write-Host ""
Write-Host "VoiceRig er installeret, modellerne er verificeret og autostart er sat for din Windows-bruger."
Write-Host "Aktiv service: PID $($Ready.pid) | commit $($Ready.source.revision)"
Write-Host "GPU-plan: Chatterbox V3/Røst = CUDA efter package-manifest; pyannote 4.0.7 / torch 2.8 / torchcodec 0.7 = CPU med in-memory PCM16 input."
Write-Host "Åbn VoiceRig med: .\start-windows.ps1"
