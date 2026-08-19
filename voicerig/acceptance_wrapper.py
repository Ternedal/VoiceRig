from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

from voicerig import rig_validation
from voicerig.source_control import source_status


def _arg_value(flag: str, default: str | None = None) -> str | None:
    args = sys.argv[1:]
    for index, value in enumerate(args):
        if value == flag and index + 1 < len(args):
            return args[index + 1]
    return default


def _has_source_args() -> bool:
    return "--source" in sys.argv[1:]


def _service_identity(base_url: str) -> dict:
    url = base_url.rstrip("/") + "/api/readiness"
    try:
        response = httpx.get(url, timeout=5.0)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("readiness payload er ikke et objekt")
        source = body.get("source")
        if not isinstance(source, dict):
            raise ValueError("readiness payload mangler source-identitet")
        return {
            "reachable": True,
            "url": url,
            "pid": body.get("pid"),
            "source": source,
            "detail": None,
        }
    except (httpx.HTTPError, ValueError) as exc:
        return {
            "reachable": False,
            "url": url,
            "pid": None,
            "source": None,
            "detail": str(exc),
        }


def collect_source_evidence(*, require_service: bool) -> tuple[dict, list[str]]:
    checkout = source_status()
    evidence: dict = {
        "checkout": checkout,
        "service": None,
        "same_revision": None,
    }
    blockers: list[str] = []

    if checkout.get("available") is not True or not checkout.get("revision"):
        blockers.append("Git checkout-identiteten kunne ikke aflæses; acceptance kræver et Git-checkout.")
    elif checkout.get("dirty") is not False:
        blockers.append("VoiceRig-checkoutet har lokale ændringer; fysisk acceptance kræver et clean checkout.")

    if not require_service:
        return evidence, blockers

    base_url = _arg_value("--voicerig-url", "http://127.0.0.1:8765") or "http://127.0.0.1:8765"
    service = _service_identity(base_url)
    evidence["service"] = service
    if not service.get("reachable"):
        blockers.append("VoiceRig-service-identiteten kunne ikke aflæses: " + str(service.get("detail") or "ukendt fejl"))
        return evidence, blockers

    service_source = service.get("source") or {}
    if service_source.get("available") is not True or not service_source.get("revision"):
        blockers.append("Den aktive VoiceRig-service rapporterer ikke en Git source revision.")
    if service_source.get("dirty") is not False:
        blockers.append("Den aktive VoiceRig-service kører fra et dirty checkout.")

    checkout_revision = checkout.get("revision")
    service_revision = service_source.get("revision")
    same_revision = bool(checkout_revision and service_revision and checkout_revision == service_revision)
    evidence["same_revision"] = same_revision
    if not same_revision:
        blockers.append(
            "Den aktive VoiceRig-service kører ikke samme Git HEAD som checkoutet "
            f"({service_revision or 'ukendt'} != {checkout_revision or 'ukendt'}). Kør setup-windows.ps1 igen."
        )

    return evidence, blockers


def _report_path() -> Path:
    value = _arg_value("--report", "validation-report.json") or "validation-report.json"
    return Path(value).expanduser().resolve()


def _write_identity_failure(report_path: Path, evidence: dict, blockers: list[str]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "ok": False,
        "stage": "source-identity",
        "source_evidence": evidence,
        "blockers": blockers,
        "warnings": [],
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _augment_report(report_path: Path, evidence: dict) -> bool:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(report, dict):
        return False
    report["source_evidence"] = evidence
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def main() -> int:
    report_path = _report_path()
    evidence, blockers = collect_source_evidence(require_service=_has_source_args())
    if blockers:
        _write_identity_failure(report_path, evidence, blockers)
        print("VoiceRig rig-validation: FAIL")
        print("Stage: source-identity")
        for blocker in blockers:
            print(f"BLOCKER: {blocker}")
        print(f"Report: {report_path}")
        return 1

    code = rig_validation.main()
    if not _augment_report(report_path, evidence):
        print("VoiceRig rig-validation: FAIL")
        print("ERROR: validation-report.json kunne ikke udvides med source-evidence.")
        return 1
    return code


if __name__ == "__main__":
    raise SystemExit(main())
