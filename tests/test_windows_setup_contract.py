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
