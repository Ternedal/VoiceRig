from __future__ import annotations

import ipaddress
import os


def allow_lan() -> bool:
    return os.getenv("VOICERIG_ALLOW_LAN", "0").strip() == "1"


def is_loopback_client(host: str | None) -> bool:
    """Return True only for a concrete loopback peer address.

    Uvicorn supplies numeric peer addresses for real sockets. Unknown/non-IP
    peer labels are deliberately rejected rather than trusted. Tests that need
    synthetic clients can exercise this helper directly or opt in explicitly
    with VOICERIG_ALLOW_LAN=1 at the app boundary.
    """
    value = (host or "").strip()
    if not value:
        return False
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False
