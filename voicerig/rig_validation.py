from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx

from voicerig.analysis.diarization import diarize_many
from voicerig.app.pipeline import SUPPORTED_EXTENSIONS, create_voice
from voicerig.engines.package_runtime import synthesize
from voicerig.media.audio import validate_wav
from voicerig.modelrig.client import install_local
from voicerig.profiles.package import validate_package
from voicerig.runtime import voice_build_readiness


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError):
        return False


def _diarization_python() -> Path | None:
    explicit = os.getenv("VOICERIG_DIARIZATION_PYTHON", "").strip()
    if explicit:
        path = Path(explicit).expanduser().resolve()
        return path if path.is_file() else None
    root = Path(__file__).resolve().parents[1]
    for path in (
        root / ".venv-diarization" / "Scripts" / "python.exe",
        root / ".venv-diarization" / "bin" / "python",
    ):
        if path.is_file():
            return path
    return None


def _probe_diarization_runtime() -> dict:
    python = _diarization_python()
    if python is None:
        return {"ok": False, "python": None, "detail": "separat Python-runtime mangler"}
    code = (
        "import pyannote.audio,torch; "
        "assert not torch.cuda.is_available(), 'diarization runtime must be CPU-only'; "
        "print(pyannote.audio.__version__); print(torch.__version__)"
    )
    try:
        proc = subprocess.run(
            [str(python), "-c", code],
            capture_output=True,
            text=True,
            check=False,
            timeout=30.0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "python": str(python), "detail": str(exc)}
    detail = (proc.stderr or proc.stdout or "").strip()[:500]
    return {
        "ok": proc.returncode == 0,
        "python": str(python),
        "detail": detail or None,
    }


def preflight() -> dict:
    readiness = voice_build_readiness()
    diarization = _probe_diarization_runtime()
    checks = {
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "git": shutil.which("git") is not None,
        "chatterbox": _module_available("chatterbox.mtl_tts"),
        "torchaudio": _module_available("torchaudio"),
        "diarization": diarization["ok"],
    }
    blockers = list(readiness["blockers"])
    if not checks["ffmpeg"]:
        blockers.append("FFmpeg blev ikke fundet på PATH.")
    if not checks["git"]:
        blockers.append("Git blev ikke fundet på PATH.")
    if not checks["chatterbox"]:
        blockers.append("chatterbox-tts er ikke installeret i hovedmiljøet.")
    if not checks["torchaudio"]:
        blockers.append("torchaudio er ikke installeret i hovedmiljøet.")
    if not checks["diarization"]:
        blockers.append(
            "Den separate pyannote CPU-runtime kan ikke importeres korrekt. "
            f"Detalje: {diarization.get('detail') or 'ukendt fejl'}"
        )

    return {
        "ok": not blockers,
        "checks": checks,
        "diarization": diarization,
        "readiness": readiness,
        "blockers": blockers,
        "warnings": list(readiness["warnings"]),
    }


def _cuda_peaks() -> dict:
    try:
        import torch
    except Exception:
        return {"peak_allocated_gb": None, "peak_reserved_gb": None}
    if not torch.cuda.is_available():
        return {"peak_allocated_gb": None, "peak_reserved_gb": None}
    return {
        "peak_allocated_gb": round(torch.cuda.max_memory_allocated() / (1024 ** 3), 2),
        "peak_reserved_gb": round(torch.cuda.max_memory_reserved() / (1024 ** 3), 2),
    }


def _reset_cuda_peaks() -> None:
    try:
        import torch
    except Exception:
        return
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()


def _probe_modelrig(base_url: str) -> dict:
    url = base_url.rstrip("/") + "/capabilities"
    try:
        response = httpx.get(url, timeout=3.0)
        response.raise_for_status()
        body = response.json()
        return {
            "reachable": True,
            "url": url,
            "tts": bool(body.get("tts")),
            "capabilities": body,
        }
    except (httpx.HTTPError, ValueError) as exc:
        return {
            "reachable": False,
            "url": url,
            "tts": False,
            "detail": str(exc),
        }


def _dominant_embedding(result) -> tuple[float, ...] | None:
    candidates = [speaker for speaker in result.speakers if speaker.embedding is not None]
    if not candidates:
        return None
    return max(candidates, key=lambda speaker: speaker.duration).embedding


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float | None:
    if not a or len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return None
    return dot / (na * nb)


def _measure_speaker_similarity(reference: Path, synthesis: Path) -> dict:
    """Informational metric only until calibrated on real Danish rig samples."""
    try:
        results = diarize_many([reference, synthesis])
        if len(results) != 2:
            raise RuntimeError("speaker-målingen returnerede forkert antal resultater")
        ref_embedding = _dominant_embedding(results[0])
        synth_embedding = _dominant_embedding(results[1])
        if ref_embedding is None or synth_embedding is None:
            return {
                "available": False,
                "cosine": None,
                "calibrated_threshold": None,
                "detail": "pyannote returnerede ikke speaker embeddings for begge filer",
            }
        similarity = _cosine(ref_embedding, synth_embedding)
        return {
            "available": similarity is not None,
            "cosine": round(similarity, 4) if similarity is not None else None,
            "calibrated_threshold": None,
            "detail": None if similarity is not None else "embedding-dimensioner kunne ikke sammenlignes",
        }
    except Exception as exc:
        return {
            "available": False,
            "cosine": None,
            "calibrated_threshold": None,
            "detail": f"{type(exc).__name__}: {exc}",
        }


def run_end_to_end(
    name: str,
    sources: list[Path],
    output_dir: Path,
    *,
    language: str = "da",
    modelrig_url: str = "http://127.0.0.1:8099",
    require_modelrig: bool = False,
) -> dict:
    before = preflight()
    if not before["ok"]:
        return {"ok": False, "stage": "preflight", "preflight": before}

    resolved: list[Path] = []
    input_errors: list[str] = []
    for source in sources:
        path = source.expanduser().resolve()
        if not path.is_file():
            input_errors.append(f"Filen findes ikke: {path}")
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            input_errors.append(f"Filtypen understøttes ikke: {path.name}")
            continue
        resolved.append(path)
    if input_errors or not resolved:
        return {
            "ok": False,
            "stage": "input",
            "preflight": before,
            "errors": input_errors or ["Tilføj mindst én lyd- eller videofil."],
        }

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    _reset_cuda_peaks()
    started = time.perf_counter()
    try:
        build = create_voice(name, resolved, output_dir, language=language)
    except Exception as exc:
        return {
            "ok": False,
            "stage": "voice-build",
            "preflight": before,
            "error": f"{type(exc).__name__}: {exc}",
            "gpu": _cuda_peaks(),
        }
    build_seconds = round(time.perf_counter() - started, 2)

    try:
        manifest = validate_package(build.package)
        install = install_local(build.package)
        speech = output_dir / f"{build.package.stem}-validation.wav"
        synth_started = time.perf_counter()
        synth_meta = synthesize(
            build.package,
            "Hej. Dette er VoiceRigs fysiske end-to-end test af den nye stemmeprofil.",
            speech,
        )
        synth_seconds = round(time.perf_counter() - synth_started, 2)
        speech_audio = validate_wav(
            speech,
            min_duration_s=0.5,
            max_duration_s=90.0,
            require_audible=True,
        )
    except Exception as exc:
        return {
            "ok": False,
            "stage": "package-runtime",
            "preflight": before,
            "package": str(build.package),
            "diarization_used": build.diarization_used,
            "build_seconds": build_seconds,
            "error": f"{type(exc).__name__}: {exc}",
            "gpu": _cuda_peaks(),
        }

    speaker_similarity = _measure_speaker_similarity(build.reference, speech)
    modelrig = _probe_modelrig(modelrig_url)
    blockers: list[str] = []
    warnings: list[str] = []
    if not build.diarization_used:
        blockers.append(
            "Speaker-diarization blev ikke brugt. Kontrollér HF_TOKEN, accepter community-1-vilkårene og modelcachen."
        )
    if not speaker_similarity["available"]:
        warnings.append(
            "Speaker-similarity kunne ikke måles automatisk; manuel lyttekontrol er stadig påkrævet."
        )
    if require_modelrig and not modelrig["reachable"]:
        blockers.append("ModelRig-worker kunne ikke kontaktes på loopback under sluttesten.")
    elif require_modelrig and not modelrig["tts"]:
        blockers.append("ModelRig-worker svarer, men rapporterer ikke TTS som tilgængelig.")
    elif not modelrig["reachable"]:
        warnings.append("ModelRig-worker kørte ikke; `.mrvoice` blev stadig installeret lokalt.")
    elif not modelrig["tts"]:
        warnings.append("ModelRig-worker kører, men TTS-capability er endnu ikke aktiv.")

    return {
        "ok": not blockers,
        "stage": "complete",
        "preflight": before,
        "voice": {
            "id": manifest.get("id"),
            "name": manifest.get("name"),
            "language": manifest.get("language"),
            "package": str(build.package),
            "reference": str(build.reference),
            "validation_wav": str(speech),
            "diarization_used": build.diarization_used,
        },
        "timing": {
            "build_seconds": build_seconds,
            "synthesis_seconds": synth_seconds,
        },
        "gpu": _cuda_peaks(),
        "synthesis": synth_meta,
        "synthesis_audio": speech_audio,
        "speaker_similarity": speaker_similarity,
        "install": install,
        "modelrig": modelrig,
        "blockers": blockers,
        "warnings": warnings,
    }


def _print_summary(report: dict) -> None:
    verdict = "PASS" if report.get("ok") else "FAIL"
    print(f"VoiceRig rig-validation: {verdict}")
    print(f"Stage: {report.get('stage', 'preflight')}")
    readiness = (report.get("preflight") or report).get("readiness", {})
    hw = readiness.get("hardware", {})
    if hw.get("gpu"):
        print(
            f"GPU: {hw['gpu']} | VRAM {hw.get('vram_total_gb')} GB | "
            f"fri {hw.get('vram_free_gb')} GB | TTS {hw.get('chatterbox_device')}"
        )
    voice = report.get("voice")
    if voice:
        print(f"Voice: {voice['name']} | {voice['package']}")
        print(f"Validation WAV: {voice['validation_wav']}")
    similarity = report.get("speaker_similarity") or {}
    if similarity.get("cosine") is not None:
        print(f"Speaker similarity cosine: {similarity['cosine']} (informational; not calibrated)")
    gpu = report.get("gpu") or {}
    if gpu.get("peak_allocated_gb") is not None:
        print(
            f"Peak VRAM: {gpu['peak_allocated_gb']} GB allocated / "
            f"{gpu['peak_reserved_gb']} GB reserved"
        )
    for warning in report.get("warnings", []):
        print(f"WARN: {warning}")
    for blocker in report.get("blockers", []):
        print(f"BLOCKER: {blocker}")
    for error in report.get("errors", []):
        print(f"ERROR: {error}")
    if report.get("error"):
        print(f"ERROR: {report['error']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="VoiceRig physical rig validation")
    parser.add_argument("--source", action="append", default=[], help="Lyd-/videofil; kan angives flere gange")
    parser.add_argument("--name", default="VoiceRig Validation", help="Navn på teststemmen")
    parser.add_argument("--language", default="da")
    parser.add_argument("--output-dir", default="validation-output")
    parser.add_argument("--modelrig-url", default="http://127.0.0.1:8099")
    parser.add_argument("--require-modelrig", action="store_true")
    parser.add_argument("--report", default="validation-report.json")
    args = parser.parse_args()

    if args.source:
        report = run_end_to_end(
            args.name,
            [Path(value) for value in args.source],
            Path(args.output_dir),
            language=args.language,
            modelrig_url=args.modelrig_url,
            require_modelrig=args.require_modelrig,
        )
    else:
        report = preflight()
        report["stage"] = "preflight"

    report_path = Path(args.report).expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _print_summary(report)
    print(f"Report: {report_path}")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
