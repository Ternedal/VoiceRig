from __future__ import annotations

import json
import wave
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import voicerig.app.main as app_main
import voicerig.app.tts_api as tts_api
import voicerig.engines.omnivoice as omnivoice
from voicerig.model_contract import (
    OMNIVOICE_ASR_REVISION,
    OMNIVOICE_MODEL_REVISION,
    OMNIVOICE_PACKAGE_VERSION,
    OMNIVOICE_SOURCE_REVISION,
)
from voicerig.profiles.package import build_package


def _wav(path: Path, frames: int = 2400, sample_rate: int = 24000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frames)


def _package(tmp_path: Path, language: str = "da") -> Path:
    reference = tmp_path / "reference.wav"
    conditioning = tmp_path / "conditioning.pt"
    preview = tmp_path / "preview.wav"
    _wav(reference)
    conditioning.write_bytes(b"conditioning")
    _wav(preview)
    package = tmp_path / "voice.mrvoice"
    return build_package("Test", language, reference, conditioning, preview, package)


def _client(monkeypatch) -> TestClient:
    # Starlette TestClient reports a synthetic peer named "testclient" rather
    # than 127.0.0.1. Bypass only the network boundary in these endpoint unit
    # tests; dedicated netguard tests keep the production loopback gate locked.
    monkeypatch.setattr(app_main, "allow_lan", lambda: True)
    return TestClient(app_main.app)


def test_omnivoice_worker_runs_as_module_after_chatterbox_release_and_strips_hf_token(
    tmp_path: Path, monkeypatch
):
    reference = tmp_path / "reference.wav"
    output = tmp_path / "output.wav"
    _wav(reference)
    fake_python = tmp_path / "python.exe"
    fake_python.write_bytes(b"")
    events: list[str] = []
    captured_env = {}
    captured_command: list[str] = []
    captured_cwd = None

    monkeypatch.setattr(omnivoice, "ensure_runtime", lambda: fake_python)
    monkeypatch.setattr(omnivoice, "release_shared_model", lambda: events.append("release"))
    monkeypatch.setenv("HF_TOKEN", "must-not-leak")
    monkeypatch.setenv("HUGGING_FACE_HUB_TOKEN", "must-not-leak-either")

    def fake_run(command, **kwargs):
        nonlocal captured_cwd
        events.append("worker")
        captured_command[:] = command
        captured_cwd = kwargs.get("cwd")
        captured_env.update(kwargs["env"])
        out = Path(command[command.index("--output") + 1])
        _wav(out, frames=4800)
        result = {
            "engine": "OmniVoice",
            "model": "k2-fsa/OmniVoice",
            "model_revision": OMNIVOICE_MODEL_REVISION,
            "source_revision": OMNIVOICE_SOURCE_REVISION,
            "sample_rate": 24000,
            "duration": 0.2,
            "language": "da",
        }
        return SimpleNamespace(
            returncode=0,
            stdout=omnivoice._RESULT_MARKER + json.dumps(result) + "\n",
            stderr="",
        )

    monkeypatch.setattr(omnivoice.subprocess, "run", fake_run)
    result = omnivoice.synthesize_omnivoice_danish(reference, "Hej verden", output)

    assert events == ["release", "worker"]
    assert captured_command[0] == str(fake_python)
    assert captured_command[1:3] == ["-m", "voicerig.engines.omnivoice_worker"]
    assert str(Path(omnivoice.__file__).with_name("omnivoice_worker.py")) not in captured_command
    assert captured_cwd == str(Path(omnivoice.__file__).resolve().parents[2])
    assert "HF_TOKEN" not in captured_env
    assert "HUGGING_FACE_HUB_TOKEN" not in captured_env
    assert captured_env["HF_HUB_DISABLE_TELEMETRY"] == "1"
    assert output.is_file()
    assert result["model_revision"] == OMNIVOICE_MODEL_REVISION


def test_omnivoice_runtime_verifier_requires_exact_pep610_git_commit():
    code = omnivoice._runtime_verification_code()

    assert "direct_url.json" in code
    assert "vcs_info" in code
    assert "commit_id" in code
    assert "v.get('vcs')=='git'" in code
    assert OMNIVOICE_SOURCE_REVISION.lower() in code
    assert OMNIVOICE_PACKAGE_VERSION in code


def test_omnivoice_runtime_repairs_a_wrong_or_unverified_source_without_forcing_dependencies(
    tmp_path: Path, monkeypatch
):
    root = tmp_path / "omnivoice-runtime"
    python = root / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")
    readiness = iter([False, False, True])
    commands: list[list[str]] = []

    monkeypatch.setattr(omnivoice, "_runtime_root", lambda: root)
    monkeypatch.setattr(omnivoice, "_runtime_python", lambda _root=None: python)
    monkeypatch.setattr(omnivoice, "_runtime_ready", lambda _python: next(readiness))
    monkeypatch.setattr(omnivoice, "_run_checked", lambda command, **_kwargs: commands.append(command))

    assert omnivoice.ensure_runtime() == python

    requirement = f"git+https://github.com/k2-fsa/OmniVoice.git@{OMNIVOICE_SOURCE_REVISION}"
    vcs_commands = [command for command in commands if requirement in command]
    assert len(vcs_commands) == 2

    dependency_command, source_repair_command = vcs_commands
    assert "--force-reinstall" not in dependency_command
    assert "--no-deps" not in dependency_command
    assert "--force-reinstall" in source_repair_command
    assert "--no-deps" in source_repair_command
    assert "--upgrade" not in source_repair_command


def test_omnivoice_contract_uses_immutable_source_model_and_asr_revisions():
    assert len(OMNIVOICE_SOURCE_REVISION) == 40
    assert len(OMNIVOICE_MODEL_REVISION) == 40
    assert len(OMNIVOICE_ASR_REVISION) == 40
    assert OMNIVOICE_SOURCE_REVISION != OMNIVOICE_MODEL_REVISION


def test_omnivoice_compare_api_uses_same_profile_reference(tmp_path: Path, monkeypatch):
    package = _package(tmp_path, "da")
    observed = {}

    monkeypatch.setattr(tts_api, "resolve_package", lambda _name=None: package)

    def fake_synthesize(reference: Path, text: str, output: Path):
        observed["reference"] = reference.read_bytes()
        observed["text"] = text
        _wav(output, frames=7200)
        return {
            "engine": "OmniVoice",
            "model": "k2-fsa/OmniVoice",
            "model_revision": OMNIVOICE_MODEL_REVISION,
            "source_revision": OMNIVOICE_SOURCE_REVISION,
            "sample_rate": 24000,
            "duration": 0.3,
            "language": "da",
        }

    monkeypatch.setattr(tts_api, "synthesize_omnivoice_danish", fake_synthesize)
    client = _client(monkeypatch)
    response = client.post(
        "/api/tts/compare/omnivoice",
        json={"text": "Rødgrød med fløde", "voice_package": package.name},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.headers["X-VoiceRig-Engine"] == "OmniVoice"
    assert response.headers["X-VoiceRig-Revision"] == OMNIVOICE_MODEL_REVISION
    assert response.headers["X-VoiceRig-Source-Revision"] == OMNIVOICE_SOURCE_REVISION
    assert observed["text"] == "Rødgrød med fløde"
    assert observed["reference"] == (tmp_path / "reference.wav").read_bytes()


def test_omnivoice_compare_api_rejects_non_danish_profile(tmp_path: Path, monkeypatch):
    package = _package(tmp_path, "en")
    monkeypatch.setattr(tts_api, "resolve_package", lambda _name=None: package)
    called = False

    def should_not_run(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("OmniVoice must not run for non-Danish comparison")

    monkeypatch.setattr(tts_api, "synthesize_omnivoice_danish", should_not_run)
    client = _client(monkeypatch)
    response = client.post(
        "/api/tts/compare/omnivoice",
        json={"text": "Hello", "voice_package": package.name},
    )

    assert response.status_code == 422
    assert "kun til danske profiler" in response.json()["detail"]
    assert called is False
