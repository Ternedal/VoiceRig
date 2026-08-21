param(
    [switch]$SkipModelWarmup
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot

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

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git mangler. Kør .\install-windows.ps1 først."
}

$Dirty = (& git status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "Kunne ikke læse Git-status." }
if ($Dirty) {
    throw "VoiceRig-checkoutet har lokale ændringer. Opdatering er stoppet for ikke at overskrive dem."
}

$OldHead = (& git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or -not $OldHead) { throw "Kunne ikke læse nuværende VoiceRig revision." }

$Upstream = (& git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $Upstream) {
    throw "Den nuværende branch har ingen upstream. Sæt branchens upstream før automatisk opdatering."
}
$Upstream = $Upstream.Trim()

Write-Host "Henter opdateringer fra $Upstream..."
& git fetch --prune
if ($LASTEXITCODE -ne 0) { throw "git fetch fejlede." }
& git merge --ff-only $Upstream
if ($LASTEXITCODE -ne 0) { throw "Opdateringen kunne ikke fast-forwardes sikkert. Ingen filer er overskrevet med en merge." }

$NewHead = (& git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw "Kunne ikke læse den nye revision." }
if ($NewHead -eq $OldHead) {
    Write-Host "VoiceRig er allerede opdateret ($OldHead). Kører stadig runtime-kontrol..."
} else {
    Write-Host "Opdaterer VoiceRig $OldHead -> $NewHead"
}

$SetupArgs = @()
if ($SkipModelWarmup) { $SetupArgs += "-SkipModelWarmup" }

try {
    & (Join-Path $PSScriptRoot "setup-windows.ps1") @SetupArgs
    if ($LASTEXITCODE -ne 0) { throw "setup-windows.ps1 returnerede fejl." }
} catch {
    $UpdateError = $_
    Write-Warning "Den nye revision kunne ikke aktiveres. Ruller tilbage til $OldHead..."
    & git reset --hard $OldHead
    if ($LASTEXITCODE -ne 0) {
        throw "Opdateringen fejlede, og automatisk rollback kunne ikke gendanne $OldHead. Oprindelig fejl: $($UpdateError.Exception.Message)"
    }
    try {
        & (Join-Path $PSScriptRoot "setup-windows.ps1") @SetupArgs
        if ($LASTEXITCODE -ne 0) { throw "rollback setup returnerede fejl." }
    } catch {
        throw "Opdateringen fejlede. Git er rullet tilbage til $OldHead, men den gamle runtime kunne ikke genstartes automatisk. Kør .\setup-windows.ps1."
    }
    throw "Opdateringen blev rullet sikkert tilbage til $OldHead, fordi den nye revision ikke bestod setup/start-kontrollen. Oprindelig fejl: $($UpdateError.Exception.Message)"
}

$Health = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 5
if (
    -not $Health -or
    $Health.ok -ne $true -or
    $Health.service -ne "voicerig" -or
    -not $Health.source -or
    $Health.source.revision -ne $NewHead -or
    $Health.source.dirty -ne $false -or
    -not (Test-SamePath ([string]$Health.source.root) $PSScriptRoot)
) {
    throw "Opdateringen kørte færdig, men den aktive VoiceRig-service matcher ikke den clean nye checkout-identitet $NewHead."
}

Write-Host "VoiceRig er opdateret og verificeret på $NewHead fra denne checkout."
