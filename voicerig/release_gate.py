from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from voicerig.source_control import source_status


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Kunne ikke læse {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} indeholder ikke et JSON-objekt.")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _artifact(path_value: object, label: str, blockers: list[str]) -> dict | None:
    if not isinstance(path_value, str) or not path_value.strip():
        blockers.append(f"{label} mangler i acceptance-rapporten.")
        return None
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        blockers.append(f"{label} findes ikke længere: {path}")
        return {"path": str(path), "exists": False}
    return {
        "path": str(path),
        "exists": True,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def evaluate_release(
    validation: dict,
    fallback: dict,
    *,
    quality_pass: bool,
    quality_note: str,
) -> dict:
    blockers: list[str] = []
    warnings: list[str] = []
    source = source_status()
    revision = source.get("revision")

    if source.get("available") is not True or not revision:
        blockers.append("Git HEAD kunne ikke aflæses; release-gaten kræver et Git-checkout.")
    if source.get("dirty") is not False:
        blockers.append("Checkoutet er dirty; release-gaten kræver et clean checkout.")

    if validation.get("ok") is not True or validation.get("stage") != "complete":
        blockers.append("validation-report.json er ikke et komplet PASS.")
    if validation.get("blockers"):
        blockers.append("validation-report.json indeholder blockers.")

    evidence = validation.get("source_evidence") or {}
    checkout = evidence.get("checkout") or {}
    service = evidence.get("service") or {}
    service_source = service.get("source") or {}
    if evidence.get("same_revision") is not True:
        blockers.append("VoiceRig-service og acceptance-checkout var ikke på samme revision.")
    if revision and checkout.get("revision") != revision:
        blockers.append("Acceptance-rapportens checkout revision matcher ikke nuværende Git HEAD.")
    if checkout.get("dirty") is not False:
        blockers.append("Acceptance-rapportens checkout var dirty.")
    if revision and service_source.get("revision") != revision:
        blockers.append("Acceptance-rapportens aktive VoiceRig-service matcher ikke nuværende Git HEAD.")
    if service_source.get("dirty") is not False:
        blockers.append("Acceptance-rapportens VoiceRig-service kørte fra et dirty checkout.")

    voice = validation.get("voice") or {}
    if voice.get("diarization_used") is not True:
        blockers.append("Den fysiske voice-build brugte ikke speaker-diarization.")

    package = _artifact(voice.get("package"), ".mrvoice package", blockers)
    reference = _artifact(voice.get("reference"), "reference WAV", blockers)
    validation_wav = _artifact(voice.get("validation_wav"), "validation WAV", blockers)

    synthesis = validation.get("synthesis") or {}
    synthesis_headers = synthesis.get("headers") or {}
    if synthesis_headers.get("device") != "cuda":
        blockers.append("Den fysiske testsyntese rapporterede ikke CUDA.")
    package_name = Path(str(voice.get("package") or "")).name
    if package_name and synthesis_headers.get("package") != package_name:
        blockers.append("Testsyntesen brugte ikke den .mrvoice-pakke, som acceptance byggede.")

    readiness = ((validation.get("preflight") or {}).get("readiness") or {})
    hardware = readiness.get("hardware") or {}
    total_vram = hardware.get("vram_total_gb")
    gpu = validation.get("gpu") or {}
    for label, sample in (("build", gpu.get("after_build") or {}), ("syntese", gpu.get("after_synthesis") or {})):
        peak = sample.get("peak_reserved_gb")
        if not isinstance(peak, (int, float)) or peak <= 0:
            blockers.append(f"Peak VRAM mangler for {label}.")
        elif isinstance(total_vram, (int, float)) and peak > total_vram + 0.25:
            blockers.append(f"Rapporteret peak VRAM for {label} overstiger kortets totale VRAM.")

    modelrig = validation.get("modelrig") or {}
    if modelrig.get("reachable") is not True:
        blockers.append("ModelRig-backenden var ikke reachable i final acceptance.")
    if modelrig.get("authenticated") is not True:
        blockers.append("ModelRig-backenden var ikke autentificeret i final acceptance.")
    if modelrig.get("tts") is not True or modelrig.get("provider") != "voicerig":
        blockers.append("ModelRig rapporterede ikke VoiceRig som fungerende TTS-provider.")
    if modelrig.get("package_matches") is not True:
        blockers.append("ModelRig brugte ikke den netop byggede .mrvoice-pakke.")

    if fallback.get("ok") is not True:
        blockers.append("piper-fallback-report.json er ikke PASS.")
    if revision and fallback.get("checkout_revision") != revision:
        blockers.append("Piper fallback blev ikke testet på nuværende Git HEAD.")
    fallback_status = fallback.get("fallback") or {}
    if fallback_status.get("ok") is not True or fallback_status.get("provider") != "piper":
        blockers.append("ModelRig skiftede ikke dokumenteret til Piper under fallback-testen.")
    piper = fallback.get("piper_synthesis") or {}
    if piper.get("provider") != "piper" or piper.get("riff") is not True:
        blockers.append("Piper fallback producerede ikke en dokumenteret RIFF/WAV.")
    piper_wav = _artifact(piper.get("output"), "Piper fallback WAV", blockers)
    if piper_wav and piper_wav.get("exists") and int(piper_wav.get("bytes") or 0) <= 44:
        blockers.append("Piper fallback WAV er tom eller ugyldigt kort.")
    if fallback.get("restarted") is not True:
        blockers.append("VoiceRig blev ikke dokumenteret genstartet efter Piper fallback-testen.")
    if revision and fallback.get("restarted_service_revision") != revision:
        blockers.append("Den genstartede VoiceRig-service matcher ikke nuværende Git HEAD.")
    restored = fallback.get("restored") or {}
    if restored.get("ok") is not True or restored.get("provider") != "voicerig":
        blockers.append("ModelRig vendte ikke dokumenteret tilbage til VoiceRig efter fallback-testen.")

    note = quality_note.strip()
    if quality_pass is not True:
        blockers.append("Manuel lyttekontrol er ikke eksplicit godkendt.")
    if quality_pass and not note:
        blockers.append("Manuel lyttekontrol kræver en kort kvalitetsnote.")

    similarity = validation.get("speaker_similarity") or {}
    if similarity.get("available") is not True:
        warnings.append("Speaker similarity var ikke automatisk tilgængelig; den manuelle kvalitetsgodkendelse er derfor eneste identity-vurdering.")

    artifacts = {
        "validation_report": None,
        "fallback_report": None,
        "package": package,
        "reference_wav": reference,
        "validation_wav": validation_wav,
        "piper_fallback_wav": piper_wav,
    }

    return {
        "ok": not blockers,
        "stage": "release-ready" if not blockers else "release-blocked",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "quality": {"pass": bool(quality_pass), "note": note or None},
        "speaker_similarity": similarity,
        "gpu": gpu,
        "modelrig": modelrig,
        "fallback": {
            "provider": fallback_status.get("provider"),
            "piper_synthesis": piper,
            "restored_provider": restored.get("provider"),
        },
        "artifacts": artifacts,
        "blockers": blockers,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="VoiceRig final physical release gate")
    parser.add_argument("--validation-report", default="validation-report.json")
    parser.add_argument("--fallback-report", default="piper-fallback-report.json")
    parser.add_argument("--quality-pass", action="store_true")
    parser.add_argument("--quality-note", default="")
    parser.add_argument("--output", default="release-acceptance.json")
    args = parser.parse_args()

    validation_path = Path(args.validation_report).expanduser().resolve()
    fallback_path = Path(args.fallback_report).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    try:
        validation = _read_json(validation_path)
        fallback = _read_json(fallback_path)
        report = evaluate_release(
            validation,
            fallback,
            quality_pass=args.quality_pass,
            quality_note=args.quality_note,
        )
    except RuntimeError as exc:
        report = {
            "ok": False,
            "stage": "release-blocked",
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "blockers": [str(exc)],
            "warnings": [],
        }

    artifacts = report.setdefault("artifacts", {})
    if validation_path.is_file():
        artifacts["validation_report"] = {
            "path": str(validation_path),
            "bytes": validation_path.stat().st_size,
            "sha256": _sha256(validation_path),
        }
    if fallback_path.is_file():
        artifacts["fallback_report"] = {
            "path": str(fallback_path),
            "bytes": fallback_path.stat().st_size,
            "sha256": _sha256(fallback_path),
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("VoiceRig release gate: " + ("PASS" if report.get("ok") else "FAIL"))
    for warning in report.get("warnings", []):
        print(f"WARN: {warning}")
    for blocker in report.get("blockers", []):
        print(f"BLOCKER: {blocker}")
    print(f"Report: {output_path}")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
