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


def test_setup_stops_only_the_local_voicerig_launcher_before_mutating_runtime():
    text = Path("setup-windows.ps1").read_text(encoding="utf-8-sig")

    assert 'function Stop-LocalVoiceRigForRuntimeMutation' in text
    assert 'Get-ProcessExecutablePath' in text
    assert '[System.StringComparison]::OrdinalIgnoreCase' in text
    assert 'Port 8765 svarer, men processen identificerer sig ikke sikkert som VoiceRig' in text
    assert 'den kører ikke fra denne checkout' in text
    assert 'Get-Process -Name "voicerig"' in text

    stop_call = 'Stop-LocalVoiceRigForRuntimeMutation $VoiceRigExePath'
    install_call = '& $MainPy -m pip install -e ".[voice]"'
    assert stop_call in text
    assert install_call in text
    assert text.index(stop_call) < text.index(install_call), (
        "the local VoiceRig launcher must be stopped before pip replaces voicerig.exe"
    )
