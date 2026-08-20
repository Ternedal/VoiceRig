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

Write-Host "Systemafhængigheder er klar. Installerer VoiceRig-runtime og modeller..."
$SetupArgs = @()
if ($SkipModelWarmup) { $SetupArgs += "-SkipModelWarmup" }
& (Join-Path $PSScriptRoot "setup-windows.ps1") @SetupArgs
if ($LASTEXITCODE -ne 0) { throw "VoiceRig setup fejlede." }

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

Write-Host ""
Write-Host "VoiceRig er klar. Service PID $($Health.pid), version $($Health.version)."
if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:8765/"
}
