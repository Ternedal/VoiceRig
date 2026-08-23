from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(name: str, *, bom: bool = False) -> str:
    return (ROOT / name).read_text(encoding="utf-8-sig" if bom else "utf-8")


def test_start_requires_clean_same_root_same_startup_revision():
    text = _read("start-windows.ps1")

    assert "function Test-SamePath" in text
    assert "$ExpectedHead = (& git rev-parse HEAD).Trim()" in text
    assert "VoiceRig-checkoutet har lokale ændringer" in text
    assert "$Health.source.root" in text
    assert "Test-SamePath ([string]$Health.source.root) $PSScriptRoot" in text
    assert "$Health.source.revision -ne $ExpectedHead" in text
    assert "$Health.source.dirty -ne $false" in text
    assert "tilhører en anden checkout" in text
    assert "anden eller dirty Git-tilstand" in text


def test_product_installer_restart_and_final_health_are_checkout_bound():
    text = _read("install-windows.ps1", bom=True)

    assert "function Test-SamePath" in text
    assert "$Existing.source.root" in text
    assert "En VoiceRig-service fra en anden checkout svarer på port 8765" in text
    assert "$ExpectedHead = (& git rev-parse HEAD).Trim()" in text
    assert "Test-SamePath ([string]$Health.source.root) $PSScriptRoot" in text
    assert "$Health.source.revision -ne $ExpectedHead" in text
    assert "$Health.source.dirty -ne $false" in text
    assert "service-processens startup-identitet" in text
    assert "Test-SamePath ([string]$Readiness.source.root) $PSScriptRoot" in text


def test_update_verifies_new_service_root_revision_and_clean_startup_state():
    text = _read("update-windows.ps1")

    assert "function Test-SamePath" in text
    assert "$Health.source.revision -ne $NewHead" in text
    assert "$Health.source.dirty -ne $false" in text
    assert "Test-SamePath ([string]$Health.source.root) $PSScriptRoot" in text
    assert "clean nye checkout-identitet" in text


def test_uninstall_only_stops_current_checkout_and_local_launcher():
    text = _read("uninstall-windows.ps1")

    assert "function Stop-CurrentCheckoutVoiceRig" in text
    assert "$Health.source.root" in text
    assert "Test-SamePath ([string]$Health.source.root) $PSScriptRoot" in text
    assert "Legacy bridge for RC2-RC6" in text
    assert "Test-SamePath $HealthPath $LocalExe" in text
    assert "Test-SamePath $HealthPath $LocalPython" in text
    assert "En VoiceRig-service fra en anden checkout" in text
    assert 'Get-Process -Name "voicerig"' in text
    assert "Test-SamePath $CandidatePath $LocalExe" in text
    assert "runtime-filerne slettes ikke" in text


def test_autostart_uninstall_preserves_foreign_checkout():
    text = _read("uninstall-autostart.ps1")

    assert "$ExpectedRoot" in text
    assert "$ExpectedExe" in text
    assert "$OwnsAutostart" in text
    assert "tilhører en anden checkout og bevares" in text
    assert "Remove-Item -LiteralPath $vbsPath" in text
