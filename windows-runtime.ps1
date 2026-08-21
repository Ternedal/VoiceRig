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
