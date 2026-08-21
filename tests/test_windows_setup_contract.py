from pathlib import Path


def test_setup_is_windows_powershell_51_safe_and_uses_nonterminating_native_probes():
    raw = Path("setup-windows.ps1").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "setup-windows.ps1 must keep a UTF-8 BOM for Windows PowerShell 5.1"

    text = raw.decode("utf-8-sig")
    assert 'function Test-NativeCommand' in text
    assert '$ErrorActionPreference = "Continue"' in text
    assert '$CudaReady = Test-NativeCommand' in text
    assert '$DiarReady = Test-NativeCommand' in text

    # These are expected-failure probes. They must not be executed directly
    # under the script-level ErrorActionPreference=Stop on Windows PowerShell 5.1.
    assert '& $MainPy -c "import torch,sys; sys.exit' not in text
    assert '& $DiarPy -c "import importlib.metadata as m,pyannote.audio,torch,torchaudio,sys; ok=' not in text


def test_product_installer_captures_model_warmup_stderr_without_ps51_termination():
    raw = Path("install-windows.ps1").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "install-windows.ps1 must keep a UTF-8 BOM for Windows PowerShell 5.1"

    text = raw.decode("utf-8-sig")
    start = text.index("function Invoke-ModelWarmup")
    end = text.index("function Restart-VoiceRigService", start)
    warmup = text[start:end]

    assert '$PreviousPreference = $ErrorActionPreference' in warmup
    assert '$ErrorActionPreference = "Continue"' in warmup
    assert '$Output = @(& $Python -m voicerig.model_warmup 2>&1)' in warmup
    assert '$ExitCode = $LASTEXITCODE' in warmup
    assert '$ErrorActionPreference = $PreviousPreference' in warmup

    workflow = Path(".github/workflows/windows-lifecycle.yml").read_text(encoding="utf-8")
    assert "Model warmup stderr capture smoke" in workflow
    assert 'shell: powershell' in workflow
    assert 'synthetic warmup stderr' in workflow
    assert 'synthetic warning stderr' in workflow
    assert 'Invoke-ModelWarmup $FakePython' in workflow


def test_setup_identifies_retry_service_by_checkout_root_or_private_python_before_mutating_runtime():
    text = Path("setup-windows.ps1").read_text(encoding="utf-8-sig")

    assert 'function Stop-LocalVoiceRigForRuntimeMutation' in text
    assert 'function Test-SamePath' in text
    assert 'Get-ProcessExecutablePath' in text
    assert '[System.StringComparison]::OrdinalIgnoreCase' in text
    assert 'Port 8765 svarer, men processen identificerer sig ikke sikkert som VoiceRig' in text
    assert 'den kører ikke fra denne checkout' in text
    assert 'Get-Process -Name "voicerig"' in text

    # Current services expose an authoritative resolved checkout root.
    assert '$Health.source.root' in text
    assert 'Test-SamePath ([string]$Health.source.root) $ExpectedRootFull' in text

    # RC2-RC6 did not expose source.root. Their health PID may be either the
    # distlib launcher or this checkout's private venv Python process.
    assert '$ExpectedPythonFull' in text
    assert 'Test-SamePath $HealthPath $ExpectedFull' in text
    assert 'Test-SamePath $HealthPath $ExpectedPythonFull' in text

    # A stale launcher from this checkout is also removed before pip replaces it.
    assert 'Stopper hængende lokal VoiceRig-launcher' in text

    stop_call = 'Stop-LocalVoiceRigForRuntimeMutation $VoiceRigExePath $MainPythonPath $PSScriptRoot'
    install_call = '& $MainPy -m pip install -e ".[voice]"'
    assert stop_call in text
    assert install_call in text
    assert text.index(stop_call) < text.index(install_call), (
        "the local VoiceRig runtime must be stopped before pip replaces voicerig.exe"
    )

    # New installations must prove the restarted service belongs to this root.
    assert '$Ready.source.root' in text
    assert 'VoiceRig-processen rapporterer ikke den installerede checkout-root' in text
