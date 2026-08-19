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


def test_main_rig_validator_only_runs_fallback_when_explicitly_required():
    text = (ROOT / "validate-rig.ps1").read_text(encoding="utf-8")

    assert "[switch]$RequirePiperFallback" in text
    assert "-RequirePiperFallback kræver også -RequireModelRig" in text
    assert "$Code -eq 0 -and $RequirePiperFallback" in text
    assert '"test-piper-fallback.ps1"' in text
    assert "piper-fallback-report.json" in text
