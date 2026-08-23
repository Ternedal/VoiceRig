param(
    [switch]$SkipModelWarmup,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot

function Refresh-ProcessPath {
    $Machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $User = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = @($Machine, $User, $env:Path) -join ";"
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

function Test-Python311 {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.11 -c "import sys; assert sys.version_info[:2] == (3, 11)" 2>$null
        if ($LASTEXITCODE -eq 0) { return $true }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        & python -c "import sys; assert sys.version_info[:2] == (3, 11)" 2>$null
        if ($LASTEXITCODE -eq 0) { return $true }
    }
    return $false
}

function Install-WingetPackage([string]$Id, [string]$DisplayName) {
    $Winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $Winget) {
        throw "$DisplayName mangler, og Windows Package Manager (winget) blev ikke fundet. Installér App Installer fra Microsoft Store og kør install-windows.ps1 igen."
    }
    Write-Host "Installerer $DisplayName via winget..."
    & winget install --id $Id -e --source winget --accept-package-agreements --accept-source-agreements --silent
    if ($LASTEXITCODE -ne 0) {
        throw "winget kunne ikke installere $DisplayName ($Id). Kør 'winget install --id $Id -e --source winget' manuelt for detaljer."
    }
    Refresh-ProcessPath
}

function Set-DotEnvValue([string]$Path, [string]$Key, [string]$Value) {
    $Lines = @()
    if (Test-Path -LiteralPath $Path) {
        $Lines = @(Get-Content -LiteralPath $Path)
    }
    $Prefix = "$Key="
    $Updated = $false
    for ($i = 0; $i -lt $Lines.Count; $i++) {
        if ($Lines[$i].StartsWith($Prefix, [System.StringComparison]::Ordinal)) {
            $Lines[$i] = "$Prefix$Value"
            $Updated = $true
            break
        }
    }
    if (-not $Updated) {
        $Lines += "$Prefix$Value"
    }
    $Temp = "$Path.tmp"
    [System.IO.File]::WriteAllLines(
        $Temp,
        [string[]]$Lines,
        [System.Text.UTF8Encoding]::new($false)
    )
    Move-Item -LiteralPath $Temp -Destination $Path -Force
}

function Read-HuggingFaceToken {
    Write-Host ""
    Write-Host "pyannote community-1 kræver én gang, at modellens vilkår accepteres på Hugging Face."
    if (-not $NoBrowser) {
        Start-Process "https://huggingface.co/pyannote/speaker-diarization-community-1"
    } else {
        Write-Host "Åbn: https://huggingface.co/pyannote/speaker-diarization-community-1"
    }
    Write-Host "Acceptér vilkårene, opret/kopiér et Hugging Face read-token og indsæt det nedenfor."
    Write-Host "Tokenet vises ikke på skærmen og gemmes kun i VoiceRigs lokale .env."
    $Secure = Read-Host "Hugging Face read-token (Enter = stop installationen her)" -AsSecureString
    if (-not $Secure -or $Secure.Length -eq 0) { return $null }
    $Ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Ptr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Ptr)
    }
}

function Invoke-ModelWarmup([string]$Python) {
    # Windows PowerShell 5.1 turns native stderr into non-terminating ErrorRecord
    # objects. Under the installer's global ErrorActionPreference=Stop, ordinary
    # Python warnings or an expected warmup failure would otherwise terminate the
    # script before LASTEXITCODE and the captured diagnostics can be inspected.
    $PreviousPreference = $ErrorActionPreference
    $Output = @()
    $ExitCode = 1
    try {
        $ErrorActionPreference = "Continue"
        $Output = @(& $Python -m voicerig.model_warmup 2>&1)
        $ExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $PreviousPreference
    }
    foreach ($Line in $Output) { Write-Host $Line }
    return @{
        Ok = ($ExitCode -eq 0)
        Text = ($Output -join "`n")
    }
}

function Restart-VoiceRigService([string]$Exe) {
    $Existing = $null
    try {
        $Existing = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 2
    } catch {
        $Existing = $null
    }

    if ($Existing) {
        if ($Existing.ok -ne $true -or $Existing.service -ne "voicerig" -or -not $Existing.pid) {
            throw "Port 8765 svarer, men processen identificerer sig ikke sikkert som VoiceRig. Installationen stopper uden at røre processen."
        }
        if (-not $Existing.source -or -not $Existing.source.root -or -not (Test-SamePath ([string]$Existing.source.root) $PSScriptRoot)) {
            throw "En VoiceRig-service fra en anden checkout svarer på port 8765. Installationen stopper uden at røre processen."
        }
        Stop-Process -Id ([int]$Existing.pid) -Force -ErrorAction Stop
        $Stopped = $false
        for ($i = 0; $i -lt 40; $i++) {
            Start-Sleep -Milliseconds 250
            try {
                $Probe = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 1
                if (-not $Probe) { $Stopped = $true; break }
            } catch {
                $Stopped = $true
                break
            }
        }
        if (-not $Stopped) {
            throw "Den eksisterende VoiceRig-service stoppede ikke rent; starter ikke en ekstra proces."
        }
    }

    Start-Process -FilePath $Exe -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
}

Write-Host "VoiceRig V1 — Windows installation"
Write-Host "Kontrollerer nødvendige systemkomponenter..."

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Install-WingetPackage "Git.Git" "Git for Windows"
}
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Install-WingetPackage "Gyan.FFmpeg" "FFmpeg"
}
if (-not (Test-Python311)) {
    Install-WingetPackage "Python.Python.3.11" "Python 3.11"
}

Refresh-ProcessPath
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Git blev installeret, men kan stadig ikke findes på PATH. Genstart terminalen og kør scriptet igen." }
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { throw "FFmpeg blev installeret, men kan stadig ikke findes på PATH. Genstart terminalen og kør scriptet igen." }
if (-not (Test-Python311)) { throw "Python 3.11 blev installeret, men kan stadig ikke findes. Genstart terminalen og kør scriptet igen." }

Write-Host "Systemafhængigheder er klar. Installerer VoiceRig-runtime..."
# The product installer owns the user-facing model warmup flow. setup-windows
# still supports direct warmup for development/acceptance, but installing the
# runtime first lets us recover from gated Hugging Face access without repeating
# every dependency installation step.
& (Join-Path $PSScriptRoot "setup-windows.ps1") -SkipModelWarmup
if ($LASTEXITCODE -ne 0) { throw "VoiceRig runtime-setup fejlede." }

$MainPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$VoiceRigExe = Join-Path $PSScriptRoot ".venv\Scripts\voicerig.exe"
if (-not (Test-Path -LiteralPath $MainPy)) { throw "VoiceRig Python-runtime mangler efter setup." }
if (-not (Test-Path -LiteralPath $VoiceRigExe)) { throw "VoiceRig service-entrypoint mangler efter setup." }

if (-not $SkipModelWarmup) {
    Write-Host ""
    Write-Host "Henter og verificerer VoiceRig-modeller..."
    $Warmup = Invoke-ModelWarmup $MainPy
    if (-not $Warmup.Ok) {
        if ($Warmup.Text -notmatch "pyannote community-1") {
            throw "Model-warmup fejlede af en anden årsag end Hugging Face-adgang. Se fejlen ovenfor og kør install-windows.ps1 igen efter rettelse."
        }

        $Token = Read-HuggingFaceToken
        if ([string]::IsNullOrWhiteSpace($Token)) {
            throw "VoiceRig-runtime er installeret, men modellerne er ikke klar. Acceptér pyannote-vilkårene og kør install-windows.ps1 igen."
        }
        try {
            Set-DotEnvValue (Join-Path $PSScriptRoot ".env") "HF_TOKEN" $Token.Trim()
            $env:HF_TOKEN = $Token.Trim()
            Write-Host "HF-adgang er gemt lokalt. Prøver model-warmup igen..."
            $Warmup = Invoke-ModelWarmup $MainPy
        } finally {
            $Token = $null
        }
        if (-not $Warmup.Ok) {
            throw "Model-warmup fejlede stadig efter HF-token blev gemt. Kontrollér at community-1-vilkårene er accepteret, og at tokenet har read-adgang."
        }
    }

    # setup-windows starts the service before this user-facing warmup. Restart
    # after warmup so a newly persisted HF_TOKEN and the verified readiness
    # marker are observed by the long-lived process and all child workers.
    Restart-VoiceRigService $VoiceRigExe
} else {
    Write-Warning "Model-warmup er sprunget over. Voice creation forbliver låst, indtil modellerne er verificeret."
}

$Health = $null
for ($i = 0; $i -lt 30; $i++) {
    try {
        $Health = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 2
        if ($Health.ok -eq $true -and $Health.service -eq "voicerig") { break }
    } catch {
        $Health = $null
    }
    Start-Sleep -Milliseconds 500
}
if (-not $Health -or $Health.ok -ne $true) { throw "VoiceRig blev installeret, men den lokale service svarer ikke." }

$ExpectedHead = (& git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or -not $ExpectedHead) { throw "Kunne ikke aflæse Git HEAD efter installationen." }
if (-not $Health.source -or -not $Health.source.root -or -not (Test-SamePath ([string]$Health.source.root) $PSScriptRoot)) {
    throw "VoiceRig blev startet efter installationen, men den aktive service tilhører ikke denne checkout."
}
if ($Health.source.revision -ne $ExpectedHead -or $Health.source.dirty -ne $false) {
    throw "VoiceRig blev startet efter installationen, men service-processens startup-identitet matcher ikke det clean installerede Git HEAD $ExpectedHead."
}

if (-not $SkipModelWarmup) {
    $Readiness = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/readiness" -TimeoutSec 5
    if ($Readiness.ready -ne $true) {
        $Reason = @($Readiness.blockers) -join "; "
        throw "Modellerne blev verificeret, men den kørende VoiceRig-service er ikke build-klar: $Reason"
    }
    if (-not $Readiness.source -or $Readiness.source.revision -ne $ExpectedHead -or -not (Test-SamePath ([string]$Readiness.source.root) $PSScriptRoot)) {
        throw "VoiceRig readiness kommer ikke fra den installerede service-identitet."
    }
}

Write-Host ""
Write-Host "VoiceRig er klar. Service PID $($Health.pid), version $($Health.version), commit $($Health.source.revision)."
if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:8765/"
}
