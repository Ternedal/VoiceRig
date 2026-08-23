from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import wave
from pathlib import Path

from voicerig.config import data_dir
from voicerig.engines.chatterbox import _MODEL_RUN_LOCK, release_shared_model
from voicerig.model_contract import (
    OMNIVOICE_ASR_MODEL,
    OMNIVOICE_ASR_REVISION,
    OMNIVOICE_CUDA_INDEX,
    OMNIVOICE_MODEL,
    OMNIVOICE_MODEL_REVISION,
    OMNIVOICE_PACKAGE_VERSION,
    OMNIVOICE_SOURCE_REVISION,
    OMNIVOICE_TORCH_VERSION,
    OMNIVOICE_TORCHAUDIO_VERSION,
)

_RUNTIME_LOCK = threading.Lock()
_RESULT_MARKER = "VOICERIG_OMNIVOICE_RESULT="
_RUNTIME_TIMEOUT_SECONDS = 1800
_INFERENCE_TIMEOUT_SECONDS = 3600


class OmniVoiceUnavailable(RuntimeError):
    pass


def _runtime_root() -> Path:
    # Keep the alternative engine outside the Git checkout and outside the
    # verified Chatterbox venv. This survives normal source updates without
    # polluting either dependency graph.
    return data_dir() / "runtimes" / "omnivoice-py311-cu128"


def _runtime_python(root: Path | None = None) -> Path:
    base = root or _runtime_root()
    if os.name == "nt":
        return base / "Scripts" / "python.exe"
    return base / "bin" / "python"


def _run_checked(command: list[str], *, timeout: int = _RUNTIME_TIMEOUT_SECONDS) -> None:
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OmniVoiceUnavailable(f"OmniVoice-runtime kunne ikke klargøres: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "ukendt fejl").strip()[-1600:]
        raise OmniVoiceUnavailable(f"OmniVoice-runtime kunne ikke klargøres: {detail}")


def _runtime_verification_code() -> str:
    """Return the fail-closed verifier executed inside the isolated runtime.

    Package version alone is not a release identity: multiple VCS commits can
    all report OmniVoice 0.2.1. PEP 610 requires pip VCS installs to retain
    direct_url.json with the resolved commit_id, so physical acceptance can
    prove the runtime uses the exact source revision pinned by VoiceRig.
    """
    return (
        "import importlib.metadata as m,json,torch,torchaudio,sys; "
        "d=m.distribution('omnivoice'); "
        "raw=d.read_text('direct_url.json') or '{}'; "
        "u=json.loads(raw); v=u.get('vcs_info') or {}; "
        f"ok=(d.version=='{OMNIVOICE_PACKAGE_VERSION}' "
        "and v.get('vcs')=='git' "
        f"and (v.get('commit_id') or '').lower()=='{OMNIVOICE_SOURCE_REVISION.lower()}' "
        f"and torch.__version__.startswith('{OMNIVOICE_TORCH_VERSION}') "
        f"and torchaudio.__version__.startswith('{OMNIVOICE_TORCHAUDIO_VERSION}') "
        "and torch.cuda.is_available()); sys.exit(0 if ok else 1)"
    )


def _runtime_ready(python: Path) -> bool:
    if not python.is_file():
        return False
    try:
        proc = subprocess.run(
            [str(python), "-c", _runtime_verification_code()],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def ensure_runtime() -> Path:
    """Create/repair the isolated OmniVoice runtime on first physical use."""
    root = _runtime_root()
    python = _runtime_python(root)
    if _runtime_ready(python):
        return python

    with _RUNTIME_LOCK:
        if _runtime_ready(python):
            return python
        root.parent.mkdir(parents=True, exist_ok=True)
        if not python.is_file():
            _run_checked([sys.executable, "-m", "venv", str(root)])
        _run_checked([str(python), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
        _run_checked(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--upgrade",
                "--force-reinstall",
                f"torch=={OMNIVOICE_TORCH_VERSION}",
                f"torchaudio=={OMNIVOICE_TORCHAUDIO_VERSION}",
                "--index-url",
                OMNIVOICE_CUDA_INDEX,
            ]
        )
        vcs_requirement = f"git+https://github.com/k2-fsa/OmniVoice.git@{OMNIVOICE_SOURCE_REVISION}"
        # First resolve/install OmniVoice's normal dependency graph while the
        # explicitly pinned Torch already satisfies its torch>=2.4 contract.
        # Do not force dependencies: --force-reinstall would allow pip to
        # replace the CUDA pin with a newer generic torch build.
        _run_checked([str(python), "-m", "pip", "install", vcs_requirement])
        # Then force only the VCS root package. --no-deps makes the exact source
        # repair deterministic without touching Torch or the resolved support
        # packages installed by the preceding command.
        _run_checked(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--force-reinstall",
                "--no-deps",
                vcs_requirement,
            ]
        )
        if not _runtime_ready(python):
            raise OmniVoiceUnavailable(
                "OmniVoice-runtime blev installeret, men exact-source/CUDA/version-kontrakten kunne ikke verificeres."
            )
    return python


def _worker_environment() -> dict[str, str]:
    env = os.environ.copy()
    # Both comparison models are public. Do not forward VoiceRig's optional
    # gated-model credential into an unrelated third-party model process.
    for key in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        env.pop(key, None)
    env["HF_HUB_DISABLE_TELEMETRY"] = "1"
    env["DO_NOT_TRACK"] = "1"
    return env


def _parse_worker_result(stdout: str) -> dict:
    line = next(
        (item for item in reversed(stdout.splitlines()) if item.startswith(_RESULT_MARKER)),
        None,
    )
    if line is None:
        raise OmniVoiceUnavailable("OmniVoice-worker returnerede ikke et gyldigt resultat.")
    try:
        result = json.loads(line[len(_RESULT_MARKER) :])
    except json.JSONDecodeError as exc:
        raise OmniVoiceUnavailable("OmniVoice-worker returnerede ugyldig metadata.") from exc
    if not isinstance(result, dict):
        raise OmniVoiceUnavailable("OmniVoice-worker returnerede ugyldig metadata.")
    return result


def synthesize_omnivoice_danish(reference_wav: Path, text: str, output: Path) -> dict:
    clean_text = str(text or "").strip()
    if not clean_text:
        raise ValueError("Skriv en dansk testtekst først.")
    if len(clean_text) > 4000:
        raise ValueError("Testteksten er for lang.")
    if not reference_wav.is_file():
        raise ValueError("Stemmeprofilens reference.wav mangler.")

    python = ensure_runtime()
    worker = Path(__file__).with_name("omnivoice_worker.py")
    if not worker.is_file():
        raise OmniVoiceUnavailable("OmniVoice-worker mangler i VoiceRig-installationen.")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="voicerig-omnivoice-request-") as tmp:
        request_path = Path(tmp) / "request.json"
        request_path.write_text(
            json.dumps(
                {
                    "reference": str(reference_wav.resolve()),
                    "text": clean_text,
                    "model_repo": OMNIVOICE_MODEL,
                    "model_revision": OMNIVOICE_MODEL_REVISION,
                    "asr_repo": OMNIVOICE_ASR_MODEL,
                    "asr_revision": OMNIVOICE_ASR_REVISION,
                    "source_revision": OMNIVOICE_SOURCE_REVISION,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        # Chatterbox/Røst live in this process while OmniVoice lives in a
        # separate one. Hold the same generation lock across release + worker
        # lifetime so ModelRig cannot reload Chatterbox while OmniVoice owns the
        # 12 GB GPU.
        with _MODEL_RUN_LOCK:
            release_shared_model()
            try:
                proc = subprocess.run(
                    [
                        str(python),
                        str(worker),
                        "--request",
                        str(request_path),
                        "--output",
                        str(output),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=_INFERENCE_TIMEOUT_SECONDS,
                    env=_worker_environment(),
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise OmniVoiceUnavailable(f"OmniVoice-generation kunne ikke gennemføres: {exc}") from exc

        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "ukendt fejl").strip()[-1600:]
            raise OmniVoiceUnavailable(f"OmniVoice-generation fejlede: {detail}")
        result = _parse_worker_result(proc.stdout)

    if not output.is_file() or output.stat().st_size < 44:
        raise OmniVoiceUnavailable("OmniVoice returnerede ingen gyldig WAV-fil.")
    try:
        with wave.open(str(output), "rb") as wav_file:
            if wav_file.getnframes() <= 0 or wav_file.getframerate() <= 0:
                raise OmniVoiceUnavailable("OmniVoice returnerede en tom WAV-fil.")
    except (wave.Error, EOFError) as exc:
        raise OmniVoiceUnavailable("OmniVoice returnerede en ugyldig WAV-fil.") from exc
    return result
