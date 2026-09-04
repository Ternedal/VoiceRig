param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Export", "Import", "Verify")]
    [string]$Action,

    [string]$Archive,
    [string]$OutDir,
    [switch]$ForceRestore,
    [switch]$NoRestart
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot

function Test-SamePath([string]$Left, [string]$Right) {
    if ([string]::IsNullOrWhiteSpace($Left) -or [string]::IsNullOrWhiteSpace($Right)) {
        return $false
    }
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

function Get-ProcessExecutablePath($Process) {
    try {
        if ($Process.Path) { return [string]$Process.Path }
    } catch {}
    try {
        $Cim = Get-CimInstance Win32_Process -Filter "ProcessId = $($Process.Id)" -ErrorAction Stop
        if ($Cim -and $Cim.ExecutablePath) { return [string]$Cim.ExecutablePath }
    } catch {}
    return $null
}

function Get-VoiceRigHealth {
    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 2
    } catch {
        return $null
    }
}

function Assert-CleanCheckout {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git mangler. Kør .\install-windows.ps1 først."
    }
    $Head = (& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $Head) {
        throw "Kunne ikke aflæse VoiceRig Git HEAD."
    }
    $Dirty = (& git status --porcelain)
    if ($LASTEXITCODE -ne 0) {
        throw "Kunne ikke aflæse VoiceRig Git-status."
    }
    if ($Dirty) {
        throw "VoiceRig-checkoutet har lokale ændringer. Migration kræver et clean checkout."
    }
    return $Head
}

function Get-VoiceRigPython {
    $Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw "VoiceRig Python-runtime mangler. Kør .\install-windows.ps1 først."
    }
    return (Resolve-Path -LiteralPath $Python).Path
}

function Invoke-StateMigrationPython {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    $Output = @(& $Python -m voicerig.state_migration @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) {
        $Detail = ($Output -join "`n").Trim()
        throw "VoiceRig state-migration fejlede: $Detail"
    }
    return (($Output -join "`n").Trim())
}

function Stop-OwnedVoiceRig {
    $LocalExe = Join-Path $PSScriptRoot ".venv\Scripts\voicerig.exe"
    $Health = Get-VoiceRigHealth
    $WasRunning = $false
    $Stopped = @{}

    if ($Health) {
        if ($Health.ok -ne $true -or $Health.service -ne "voicerig" -or -not $Health.pid) {
            throw "Port 8765 svarer, men processen kan ikke identificeres sikkert som VoiceRig. Migration stopper."
        }
        if (-not $Health.source -or -not $Health.source.root -or -not (Test-SamePath ([string]$Health.source.root) $PSScriptRoot)) {
            throw "En VoiceRig-service fra en anden checkout kører på port 8765. Den røres ikke."
        }
        $WasRunning = $true
        $HealthPid = [int]$Health.pid
        if ($HealthPid -ne $PID) {
            Write-Host "Stopper VoiceRig-service PID $HealthPid før state-migration..."
            Stop-Process -Id $HealthPid -Force -ErrorAction Stop
            $Stopped[$HealthPid] = $true
        }
    }

    foreach ($Candidate in @(Get-Process -Name "voicerig" -ErrorAction SilentlyContinue)) {
        if ($Stopped.ContainsKey([int]$Candidate.Id)) { continue }
        $CandidatePath = Get-ProcessExecutablePath $Candidate
        if (Test-SamePath $CandidatePath $LocalExe) {
            $WasRunning = $true
            Write-Host "Stopper lokal VoiceRig-launcher PID $($Candidate.Id)..."
            Stop-Process -Id ([int]$Candidate.Id) -Force -ErrorAction Stop
            $Stopped[[int]$Candidate.Id] = $true
        }
    }

    foreach ($StoppedPid in @($Stopped.Keys)) {
        $Exited = $false
        for ($i = 0; $i -lt 40; $i++) {
            if (-not (Get-Process -Id ([int]$StoppedPid) -ErrorAction SilentlyContinue)) {
                $Exited = $true
                break
            }
            Start-Sleep -Milliseconds 250
        }
        if (-not $Exited) {
            throw "VoiceRig-proces PID $StoppedPid stoppede ikke inden for 10 sekunder. Migration nægtes."
        }
    }

    $Remaining = Get-VoiceRigHealth
    if ($Remaining) {
        throw "VoiceRig svarer stadig på port 8765 efter stop. State-migration nægtes."
    }
    return $WasRunning
}

function Start-OwnedVoiceRig {
    & (Join-Path $PSScriptRoot "start-windows.ps1") -NoBrowser
    $Health = Get-VoiceRigHealth
    if (-not $Health -or $Health.ok -ne $true -or $Health.service -ne "voicerig") {
        throw "VoiceRig startede ikke sikkert efter state-migration."
    }
    if (-not $Health.source -or -not $Health.source.root -or -not (Test-SamePath ([string]$Health.source.root) $PSScriptRoot)) {
        throw "VoiceRig startede efter migration, men servicen tilhører ikke denne checkout."
    }
}

function Get-ArchiveHash([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-SidecarPath([string]$Path) {
    return "$Path.migration.json"
}

function Write-MigrationSidecar {
    param(
        [Parameter(Mandatory = $true)][string]$ArchivePath,
        [Parameter(Mandatory = $true)][string]$Head,
        [Parameter(Mandatory = $true)]$Verification
    )
    $SidecarPath = Get-SidecarPath $ArchivePath
    $Payload = [ordered]@{
        schema = 1
        archive_name = [System.IO.Path]::GetFileName($ArchivePath)
        sha256 = Get-ArchiveHash $ArchivePath
        created_utc = [DateTime]::UtcNow.ToString("o")
        source_computer = $env:COMPUTERNAME
        source_revision = $Head
        voice_count = [int]$Verification.voice_count
        job_count = [int]$Verification.job_count
        default_package = $Verification.default_package
        contains_private_job_inputs = [bool]$Verification.contains_private_job_inputs
    }
    $Temp = "$SidecarPath.tmp"
    $Payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $Temp -Encoding UTF8
    Move-Item -LiteralPath $Temp -Destination $SidecarPath -Force
    return $SidecarPath
}

function Read-And-VerifySidecar([string]$ArchivePath) {
    $SidecarPath = Get-SidecarPath $ArchivePath
    if (-not (Test-Path -LiteralPath $SidecarPath -PathType Leaf)) {
        throw "Migration-sidecar mangler: $SidecarPath"
    }
    try {
        $Sidecar = Get-Content -LiteralPath $SidecarPath -Raw | ConvertFrom-Json
    } catch {
        throw "Migration-sidecar er ugyldig JSON: $SidecarPath"
    }
    if ($Sidecar.schema -ne 1) {
        throw "Ikke-understøttet VoiceRig migration-sidecar schema: $($Sidecar.schema)"
    }
    if ($Sidecar.archive_name -ne [System.IO.Path]::GetFileName($ArchivePath)) {
        throw "Migration-sidecar tilhører ikke det valgte arkiv."
    }
    $ActualHash = Get-ArchiveHash $ArchivePath
    if ([string]$Sidecar.sha256 -ne $ActualHash) {
        throw "Migration-sidecar SHA-256 matcher ikke arkivet."
    }
    return $Sidecar
}

$Python = Get-VoiceRigPython

if ($Action -eq "Verify") {
    if ([string]::IsNullOrWhiteSpace($Archive)) {
        throw "-Archive er påkrævet ved Verify."
    }
    $ResolvedArchive = (Resolve-Path -LiteralPath $Archive).Path
    $Sidecar = Read-And-VerifySidecar $ResolvedArchive
    $Verification = (Invoke-StateMigrationPython -Python $Python -Arguments @("verify", $ResolvedArchive)) | ConvertFrom-Json
    Write-Host "VoiceRig migration verificeret: $($Verification.voice_count) stemmer, $($Verification.job_count) jobs."
    if ($Verification.contains_private_job_inputs) {
        Write-Warning "Arkivet indeholder private lyd/video-inputs fra resumérbare VoiceRig-jobs. Opbevar og transporter det derefter."
    }
    return
}

$Head = Assert-CleanCheckout

if ($Action -eq "Export") {
    if ([string]::IsNullOrWhiteSpace($OutDir)) {
        $OutDir = Join-Path $PSScriptRoot "migration"
    }
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
    $ResolvedOutDir = (Resolve-Path -LiteralPath $OutDir).Path
    $WasRunning = Stop-OwnedVoiceRig
    $Failure = $null
    $CreatedArchive = $null
    try {
        $CreatedArchive = Invoke-StateMigrationPython -Python $Python -Arguments @("create", "--out", $ResolvedOutDir)
        $CreatedArchive = (Resolve-Path -LiteralPath $CreatedArchive).Path
        $Verification = (Invoke-StateMigrationPython -Python $Python -Arguments @("verify", $CreatedArchive)) | ConvertFrom-Json
        $SidecarPath = Write-MigrationSidecar -ArchivePath $CreatedArchive -Head $Head -Verification $Verification
        Write-Host "VoiceRig state eksporteret: $CreatedArchive"
        Write-Host "Migration-sidecar: $SidecarPath"
        if ($Verification.contains_private_job_inputs) {
            Write-Warning "Arkivet indeholder private lyd/video-inputs fra resumérbare VoiceRig-jobs. Behandl filen som sensitiv."
        }
    } catch {
        $Failure = $_
    } finally {
        if ($WasRunning -and -not $NoRestart) {
            try {
                Start-OwnedVoiceRig
            } catch {
                if ($Failure) {
                    Write-Warning "Eksporten fejlede, og den gamle VoiceRig kunne heller ikke genstartes: $($_.Exception.Message)"
                } else {
                    throw
                }
            }
        }
    }
    if ($Failure) { throw $Failure }
    return
}

if ($Action -eq "Import") {
    if ([string]::IsNullOrWhiteSpace($Archive)) {
        throw "-Archive er påkrævet ved Import."
    }
    $ResolvedArchive = (Resolve-Path -LiteralPath $Archive).Path
    $Sidecar = Read-And-VerifySidecar $ResolvedArchive
    $Verification = (Invoke-StateMigrationPython -Python $Python -Arguments @("verify", $ResolvedArchive)) | ConvertFrom-Json
    if ($Verification.contains_private_job_inputs) {
        Write-Warning "Importen indeholder private VoiceRig-jobinputs; de genskabes under den nye VoiceRig datamappe."
    }

    [void](Stop-OwnedVoiceRig)
    $Arguments = @("restore", $ResolvedArchive)
    if ($ForceRestore) { $Arguments += "--force" }

    # Fail closed: efter service-stop genstartes VoiceRig kun hvis hele restore-kaldet lykkes.
    $RestoreResult = (Invoke-StateMigrationPython -Python $Python -Arguments $Arguments) | ConvertFrom-Json
    Write-Host "VoiceRig state importeret: $($RestoreResult.voice_count) stemmer, $($RestoreResult.job_count) jobs."

    if (-not $NoRestart) {
        Start-OwnedVoiceRig
        try {
            $Readiness = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/readiness" -TimeoutSec 5
            if ($Readiness.ready -eq $true) {
                Write-Host "VoiceRig readiness er grøn efter import."
            } else {
                $Blockers = @($Readiness.blockers) -join "; "
                Write-Warning "VoiceRig state er importeret og servicen kører, men model-readiness er ikke grøn endnu: $Blockers"
            }
        } catch {
            Write-Warning "VoiceRig kører efter import, men readiness-endpointet kunne ikke verificeres: $($_.Exception.Message)"
        }
    }
    return
}

throw "Ukendt migration-action: $Action"
