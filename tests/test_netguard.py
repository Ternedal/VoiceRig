from __future__ import annotations

from voicerig.app import netguard


def test_loopback_clients_are_allowed():
    assert netguard.is_loopback_client("127.0.0.1") is True
    assert netguard.is_loopback_client("127.12.34.56") is True
    assert netguard.is_loopback_client("::1") is True


def test_lan_and_public_clients_are_rejected():
    assert netguard.is_loopback_client("192.168.1.20") is False
    assert netguard.is_loopback_client("10.0.0.5") is False
    assert netguard.is_loopback_client("8.8.8.8") is False
    assert netguard.is_loopback_client("fe80::1234") is False


def test_unknown_or_missing_peer_is_fail_closed():
    assert netguard.is_loopback_client(None) is False
    assert netguard.is_loopback_client("") is False
    assert netguard.is_loopback_client("testclient") is False


def test_lan_escape_hatch_is_explicit(monkeypatch):
    monkeypatch.delenv("VOICERIG_ALLOW_LAN", raising=False)
    assert netguard.allow_lan() is False

    monkeypatch.setenv("VOICERIG_ALLOW_LAN", "1")
    assert netguard.allow_lan() is True

    monkeypatch.setenv("VOICERIG_ALLOW_LAN", "true")
    assert netguard.allow_lan() is False
