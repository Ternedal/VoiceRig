from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_piper_fallback_script_is_fail_safe_and_restores_voicerig():
    text = (ROOT / "test-piper-fallback.ps1").read_text(encoding="utf-8")

    assert 'Wait-ModelRigProvider "voicerig"' in text
    assert 'Wait-ModelRigProvider "piper"' in text
    assert "try {" in text
    assert "finally {" in text
    assert "Stop-Process -Id $StoppedPid -Force" in text
    assert "Start-Process -FilePath $VoiceRigExe" in text
    assert "Wait-VoiceRigReady $CheckoutRevision" in text
    assert "restarted_service_revision" in text
    assert "Piper fallback acceptance: PASS" in text


def test_piper_fallback_requires_real_worker_wav_on_loopback():
    text = (ROOT / "test-piper-fallback.ps1").read_text(encoding="utf-8")

    assert '[string]$ModelRigWorkerUrl = "http://127.0.0.1:8099"' in text
    assert '$WorkerUri.Host -notin @("127.0.0.1", "localhost", "::1")' in text
    assert '"/voice/tts/synthesize"' in text
    assert "Invoke-PiperSynthesis" in text
    assert '$Result.provider -ne "piper"' in text
    assert '$Magic -ne "RIFF"' in text
    assert "piper_synthesis = $PiperSynthesis" in text
    assert "piper-fallback.wav" in text


def test_main_rig_validator_only_runs_fallback_when_explicitly_required():
    text = (ROOT / "validate-rig.ps1").read_text(encoding="utf-8")

    assert "[switch]$RequirePiperFallback" in text
    assert "-RequirePiperFallback kræver også -RequireModelRig" in text
    assert "$Code -eq 0 -and $RequirePiperFallback" in text
    assert '"test-piper-fallback.ps1"' in text
    assert "-ModelRigWorkerUrl $ModelRigWorkerUrl" in text
    assert "piper-fallback-report.json" in text


def test_main_rig_validator_keeps_modelrig_token_off_python_command_line():
    text = (ROOT / "validate-rig.ps1").read_text(encoding="utf-8")

    assert '"--modelrig-token"' not in text
    assert "$PreviousModelRigToken = $env:MODELRIG_TOKEN" in text
    assert "$env:MODELRIG_TOKEN = $ModelRigToken" in text
    assert "Remove-Item Env:MODELRIG_TOKEN" in text
    assert "finally {" in text
