from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import shutil
import subprocess
import time
import zipfile
from contextlib import ExitStack
from pathlib import Path
from urllib.parse import urljoin

import httpx

from voicerig.analysis.diarization import diarize_many
from voicerig.app.pipeline import SUPPORTED_EXTENSIONS
from voicerig.media.audio import validate_wav
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
        "import importlib.metadata as m,pyannote.audio,torch,torchaudio; "
        "assert not torch.cuda.is_available(), 'diarization runtime must be CPU-only'; "
        "print(pyannote.audio.__version__); print(torch.__version__); "
        "print(torchaudio.__version__); print(m.version('torchcodec'))"
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
        blockers.append("Chatterbox V3 er ikke installeret i hovedmiljøet.")
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


def _voice_service_status(base_url: str) -> dict:
    url = base_url.rstrip("/") + "/api/readiness"
    try:
        response = httpx.get(url, timeout=3.0)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("readiness payload er ikke et objekt")
        return {
            "reachable": True,
            "ready": body.get("ready") is True,
            "url": url,
            "body": body,
            "detail": None,
        }
    except (httpx.HTTPError, ValueError) as exc:
        return {
            "reachable": False,
            "ready": False,
            "url": url,
            "body": None,
            "detail": str(exc),
        }


def _probe_modelrig(base_url: str, token: str | None, expected_package: str | None = None) -> dict:
    """Probe the authenticated ModelRig backend, never the raw loopback worker."""
    url = base_url.rstrip("/") + "/api/v1/health/full"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        response = httpx.get(url, headers=headers, timeout=8.0)
        if response.status_code in {401, 403}:
            return {
                "reachable": True,
                "authenticated": False,
                "url": url,
                "tts": False,
                "provider": None,
                "package": None,
                "detail": "ModelRig kræver et gyldigt MODELRIG_TOKEN til backend-valideringen.",
            }
        response.raise_for_status()
        body = response.json()
        checks = body.get("checks") if isinstance(body, dict) else None
        tts = checks.get("tts") if isinstance(checks, dict) else None
        if not isinstance(tts, dict):
            raise ValueError("ModelRig health/full mangler checks.tts")
        provider = tts.get("provider")
        package = tts.get("package")
        package_matches = expected_package is None or package == expected_package
        return {
            "reachable": True,
            "authenticated": True,
            "url": url,
            "tts": tts.get("ok") is True,
            "provider": provider,
            "package": package,
            "package_matches": package_matches,
            "tts_status": tts,
            "detail": None,
        }
    except (httpx.HTTPError, ValueError) as exc:
        return {
            "reachable": False,
            "authenticated": False,
            "url": url,
            "tts": False,
            "provider": None,
            "package": None,
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


def _header_float(headers, name: str) -> float | None:
    value = headers.get(name)
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return round(parsed, 3) if math.isfinite(parsed) else None


def _build_via_service(
    base_url: str,
    name: str,
    sources: list[Path],
    language: str,
    timeout_s: float,
) -> dict:
    url = base_url.rstrip("/") + "/api/voices"
    started = time.perf_counter()
    try:
        with ExitStack() as stack:
            files = [
                (
                    "files",
                    (
                        source.name,
                        stack.enter_context(source.open("rb")),
                        "application/octet-stream",
                    ),
                )
                for source in sources
            ]
            response = httpx.post(
                url,
                data={
                    "name": name,
                    "language": language,
                    "install_in_modelrig": "true",
                },
                files=files,
                timeout=timeout_s,
            )
    except (httpx.HTTPError, OSError) as exc:
        raise RuntimeError(f"VoiceRig-service build kunne ikke gennemføres: {exc}") from exc

    elapsed = round(time.perf_counter() - started, 2)
    try:
        body = response.json()
    except ValueError:
        body = None
    if response.status_code == 409 and isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, dict) and detail.get("code") == "speaker_selection_required":
            count = len(detail.get("speakers") or [])
            raise RuntimeError(
                f"Fysisk acceptance kræver entydigt testmateriale; VoiceRig fandt {count} tydelige stemmer. "
                "Brug UI'et til manuel produkt-test af flerspeaker-flowet eller vælg renere acceptance-klip."
            )
    if response.status_code >= 400:
        detail = body.get("detail") if isinstance(body, dict) else response.text[:500]
        raise RuntimeError(f"VoiceRig-service build fejlede med HTTP {response.status_code}: {detail}")
    if not isinstance(body, dict) or body.get("ok") is not True:
        raise RuntimeError("VoiceRig-service returnerede ikke et gyldigt build-resultat.")
    body["build_seconds_client"] = elapsed
    return body


def _download_package(base_url: str, download_url: str, destination: Path) -> Path:
    url = urljoin(base_url.rstrip("/") + "/", download_url.lstrip("/"))
    response = httpx.get(url, timeout=60.0)
    response.raise_for_status()
    destination.write_bytes(response.content)
    validate_package(destination)
    return destination


def _extract_reference(package: Path, destination: Path) -> Path:
    # validate_package has already checked archive paths, sizes and checksums.
    validate_package(package)
    with zipfile.ZipFile(package, "r") as zf:
        destination.write_bytes(zf.read("reference.wav"))
    validate_wav(destination, min_duration_s=5.4, max_duration_s=11.5, require_audible=True)
    return destination


def _synthesize_via_service(base_url: str, package_name: str, output: Path, timeout_s: float) -> dict:
    url = base_url.rstrip("/") + "/api/tts/synthesize"
    started = time.perf_counter()
    response = httpx.post(
        url,
        json={
            "text": "Hej. Dette er VoiceRigs fysiske end-to-end test af den nye stemmeprofil.",
            "voice_package": package_name,
        },
        timeout=timeout_s,
    )
    elapsed = round(time.perf_counter() - started, 2)
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = response.text[:500]
        raise RuntimeError(f"VoiceRig TTS fejlede med HTTP {response.status_code}: {detail}")
    output.write_bytes(response.content)
    audio = validate_wav(output, min_duration_s=0.5, max_duration_s=90.0, require_audible=True)
    gpu = {
        "available": response.headers.get("X-VoiceRig-Peak-Allocated-GB") is not None,
        "allocated_gb": _header_float(response.headers, "X-VoiceRig-Allocated-GB"),
        "reserved_gb": _header_float(response.headers, "X-VoiceRig-Reserved-GB"),
        "peak_allocated_gb": _header_float(response.headers, "X-VoiceRig-Peak-Allocated-GB"),
        "peak_reserved_gb": _header_float(response.headers, "X-VoiceRig-Peak-Reserved-GB"),
    }
    return {
        "seconds_client": elapsed,
        "audio": audio,
        "gpu": gpu,
        "headers": {
            "voice": response.headers.get("X-VoiceRig-Voice"),
            "voice_id": response.headers.get("X-VoiceRig-Voice-ID"),
            "package": response.headers.get("X-VoiceRig-Package"),
            "device": response.headers.get("X-VoiceRig-Device"),
            "sample_rate": response.headers.get("X-VoiceRig-Sample-Rate"),
            "duration": response.headers.get("X-VoiceRig-Duration"),
        },
    }


def run_end_to_end(
    name: str,
    sources: list[Path],
    output_dir: Path,
    *,
    language: str = "da",
    voicerig_url: str = "http://127.0.0.1:8765",
    modelrig_url: str = "http://127.0.0.1:8080",
    modelrig_token: str | None = None,
    require_modelrig: bool = False,
    service_timeout_s: float = 1800.0,
) -> dict:
    before = preflight()
    if not before["ok"]:
        return {"ok": False, "stage": "preflight", "preflight": before}

    service = _voice_service_status(voicerig_url)
    if not service["reachable"]:
        return {
            "ok": False,
            "stage": "voicerig-service",
            "preflight": before,
            "service": service,
            "error": "VoiceRig-service svarer ikke på 127.0.0.1:8765. Start den med start-windows.ps1.",
        }
    if not service["ready"]:
        return {
            "ok": False,
            "stage": "voicerig-service",
            "preflight": before,
            "service": service,
            "error": "VoiceRig-service kører, men readiness er ikke grøn.",
        }

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
            "service": service,
            "errors": input_errors or ["Tilføj mindst én lyd- eller videofil."],
        }

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        build = _build_via_service(
            voicerig_url,
            name,
            resolved,
            language,
            service_timeout_s,
        )
        package_name = str(build["package"])
        package = _download_package(
            voicerig_url,
            str(build["download_url"]),
            output_dir / package_name,
        )
        manifest = validate_package(package)
        reference = _extract_reference(package, output_dir / f"{package.stem}-reference.wav")
        speech = output_dir / f"{package.stem}-validation.wav"
        synthesis = _synthesize_via_service(
            voicerig_url,
            package_name,
            speech,
            service_timeout_s,
        )
    except Exception as exc:
        return {
            "ok": False,
            "stage": "product-e2e",
            "preflight": before,
            "service": service,
            "error": f"{type(exc).__name__}: {exc}",
        }

    speaker_similarity = _measure_speaker_similarity(reference, speech)
    token = modelrig_token or os.getenv("MODELRIG_TOKEN", "").strip() or None
    modelrig = _probe_modelrig(modelrig_url, token, expected_package=package_name)
    blockers: list[str] = []
    warnings: list[str] = []

    if build.get("diarization_used") is not True:
        blockers.append("Speaker-diarization blev ikke brugt i det rigtige VoiceRig-build.")
    if build.get("installed_in_modelrig") is not True:
        blockers.append(
            "VoiceRig-buildet blev ikke installeret i ModelRigs lokale voice-mappe: "
            + str(build.get("modelrig_detail") or "ukendt årsag")
        )
    if synthesis["headers"].get("package") != package_name:
        blockers.append("VoiceRig TTS syntetiserede ikke med den netop byggede .mrvoice-pakke.")
    if synthesis["headers"].get("device") != "cuda":
        blockers.append("VoiceRig TTS rapporterede ikke CUDA som execution device.")
    if not synthesis["gpu"].get("available"):
        blockers.append("VoiceRig-serveren returnerede ikke peak VRAM-målinger fra CUDA-processen.")
    if not speaker_similarity["available"]:
        warnings.append(
            "Speaker-similarity kunne ikke måles automatisk; manuel lyttekontrol er stadig påkrævet."
        )

    if require_modelrig:
        if not modelrig["reachable"]:
            blockers.append("ModelRig-backenden kunne ikke kontaktes på loopback under sluttesten.")
        elif not modelrig.get("authenticated"):
            blockers.append(str(modelrig.get("detail") or "ModelRig-backend authentication fejlede."))
        elif not modelrig.get("tts"):
            blockers.append("ModelRig svarer, men checks.tts er ikke klar.")
        elif modelrig.get("provider") != "voicerig":
            blockers.append(
                f"ModelRig bruger provider {modelrig.get('provider')!r}, ikke VoiceRig."
            )
        elif not modelrig.get("package_matches"):
            blockers.append(
                "ModelRig bruger VoiceRig, men ikke den .mrvoice-pakke der netop blev bygget."
            )
    else:
        if not modelrig["reachable"]:
            warnings.append("ModelRig-backenden kørte ikke; VoiceRig produkt-E2E blev stadig gennemført.")
        elif not modelrig.get("authenticated"):
            warnings.append(str(modelrig.get("detail") or "ModelRig-backend kunne ikke autentificeres."))
        elif modelrig.get("provider") != "voicerig":
            warnings.append(
                f"ModelRig TTS-provider er {modelrig.get('provider')!r}; brug -RequireModelRig til hård integrationstest."
            )

    return {
        "ok": not blockers,
        "stage": "complete",
        "preflight": before,
        "service": service,
        "voice": {
            "id": manifest.get("id"),
            "name": manifest.get("name"),
            "language": manifest.get("language"),
            "package": str(package),
            "reference": str(reference),
            "validation_wav": str(speech),
            "diarization_used": build.get("diarization_used"),
        },
        "timing": {
            "build_seconds_client": build.get("build_seconds_client"),
            "synthesis_seconds_client": synthesis["seconds_client"],
        },
        "gpu": {
            "after_build": build.get("gpu"),
            "after_synthesis": synthesis["gpu"],
        },
        "synthesis": synthesis,
        "speaker_similarity": speaker_similarity,
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
    gpu = ((report.get("gpu") or {}).get("after_synthesis") or {})
    if gpu.get("peak_allocated_gb") is not None:
        print(
            f"Server peak VRAM: {gpu['peak_allocated_gb']} GB allocated / "
            f"{gpu['peak_reserved_gb']} GB reserved"
        )
    modelrig = report.get("modelrig") or {}
    if modelrig.get("reachable"):
        print(
            f"ModelRig: provider={modelrig.get('provider')} | package={modelrig.get('package')} | "
            f"authenticated={modelrig.get('authenticated')}"
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
    parser.add_argument("--voicerig-url", default="http://127.0.0.1:8765")
    parser.add_argument("--modelrig-url", default="http://127.0.0.1:8080")
    parser.add_argument("--modelrig-token", default=None)
    parser.add_argument("--require-modelrig", action="store_true")
    parser.add_argument("--service-timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--report", default="validation-report.json")
    args = parser.parse_args()

    if args.source:
        report = run_end_to_end(
            args.name,
            [Path(value) for value in args.source],
            Path(args.output_dir),
            language=args.language,
            voicerig_url=args.voicerig_url,
            modelrig_url=args.modelrig_url,
            modelrig_token=args.modelrig_token,
            require_modelrig=args.require_modelrig,
            service_timeout_s=max(30.0, args.service_timeout_seconds),
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
