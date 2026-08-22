from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from voicerig.app.pipeline import (
    BuildResult,
    ReferenceSelectionRequired,
    SpeakerSelectionRequired,
    create_voice,
)
from voicerig.config import data_dir, modelrig_base_url, modelrig_token
from voicerig.modelrig.client import ModelRigUnavailable, install_voice
from voicerig.profiles.package import validate_package
from voicerig.runtime import cuda_memory_stats, reset_cuda_peaks
from voicerig.source_control import source_status

_TERMINAL = {"succeeded", "failed", "cancelled"}


class BuildCancelled(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class VoiceJobManager:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="voicerig-build")
        self._lock = threading.RLock()
        self._active: set[str] = set()
        self._cancel: set[str] = set()

    def _root(self) -> Path:
        root = data_dir() / "jobs"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _meta_path(self, job_id: str) -> Path:
        return self._root() / f"{job_id}.json"

    def _work_dir(self, job_id: str) -> Path:
        return self._root() / job_id

    @staticmethod
    def _validate_job_id(job_id: str) -> str:
        value = str(job_id or "").strip().lower()
        if len(value) != 32 or any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError("Ugyldigt job-id.")
        return value

    def _read(self, job_id: str) -> dict:
        safe = self._validate_job_id(job_id)
        path = self._meta_path(safe)
        if not path.is_file():
            raise FileNotFoundError("Voice-build-jobbet findes ikke.")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Voice-build-jobbets statusfil er beskadiget.") from exc
        if not isinstance(payload, dict) or payload.get("id") != safe:
            raise RuntimeError("Voice-build-jobbets statusfil er ugyldig.")
        return payload

    def _write(self, payload: dict) -> dict:
        payload = dict(payload)
        payload["updated_at"] = _now()
        path = self._meta_path(str(payload["id"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{payload['id']}-", suffix=".json.tmp", dir=path.parent)
        temp = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
        return payload

    @staticmethod
    def _public(payload: dict) -> dict:
        value = dict(payload)
        value.pop("inputs", None)
        value.pop("speaker_anchor", None)
        value.pop("reference_choice", None)
        return value

    def _cleanup_inputs(self, job_id: str) -> None:
        shutil.rmtree(self._work_dir(job_id), ignore_errors=True)

    def _update(self, job_id: str, **changes) -> dict:
        with self._lock:
            payload = self._read(job_id)
            payload.update(changes)
            return self._write(payload)

    def create(
        self,
        name: str,
        language: str,
        install_in_modelrig: bool,
        sources: list[tuple[str, Path]],
    ) -> dict:
        if not name.strip():
            raise ValueError("Stemmen skal have et navn.")
        if not sources:
            raise ValueError("Tilføj mindst én lyd- eller videofil.")
        job_id = uuid.uuid4().hex
        work = self._work_dir(job_id)
        work.mkdir(parents=True, exist_ok=False)
        inputs: list[str] = []
        original_names: list[str] = []
        try:
            for idx, (original_name, source) in enumerate(sources):
                suffix = source.suffix.lower()
                filename = f"input_{idx:02d}{suffix}"
                shutil.copy2(source, work / filename)
                inputs.append(filename)
                original_names.append(Path(original_name).name)
            payload = {
                "id": job_id,
                "kind": "voice-build",
                "state": "queued",
                "progress": 0,
                "stage": "queued",
                "message": "Venter på VoiceRig GPU-køen…",
                "name": name.strip(),
                "language": language,
                "install_in_modelrig": bool(install_in_modelrig),
                "files": original_names,
                "inputs": inputs,
                "speaker_anchor": None,
                "speaker_choices": None,
                "reference_choice": None,
                "reference_choices": None,
                "result": None,
                "error": None,
                "created_at": _now(),
                "updated_at": _now(),
            }
            self._write(payload)
            self._submit(job_id)
            return self._public(payload)
        except Exception:
            shutil.rmtree(work, ignore_errors=True)
            self._meta_path(job_id).unlink(missing_ok=True)
            raise

    def _submit(self, job_id: str) -> None:
        with self._lock:
            if job_id in self._active:
                return
            self._active.add(job_id)
        self._executor.submit(self._run, job_id)

    def _checkpoint(self, job_id: str, stage: str, percent: int, message: str) -> None:
        with self._lock:
            payload = self._read(job_id)
            if job_id in self._cancel or payload.get("state") == "cancelling":
                raise BuildCancelled("Voice-build blev annulleret.")
            payload.update(
                state="running",
                stage=stage,
                progress=max(0, min(100, int(percent))),
                message=message,
                error=None,
            )
            self._write(payload)

    def _run(self, job_id: str) -> None:
        try:
            payload = self._read(job_id)
            if payload.get("state") == "cancelling" or job_id in self._cancel:
                raise BuildCancelled("Voice-build blev annulleret.")
            work = self._work_dir(job_id)
            sources = [work / name for name in payload.get("inputs") or []]
            if not sources or any(not path.is_file() for path in sources):
                raise RuntimeError("Jobbets midlertidige kildefiler mangler.")

            reset_cuda_peaks()
            self._checkpoint(job_id, "starting", 1, "Starter voice-build…")
            result = create_voice(
                payload["name"],
                sources,
                data_dir() / "voices",
                language=payload.get("language") or "da",
                speaker_anchor=payload.get("speaker_anchor"),
                reference_choice=payload.get("reference_choice"),
                progress=lambda stage, percent, message: self._checkpoint(job_id, stage, percent, message),
            )
            self._checkpoint(job_id, "installing", 96, "Installerer profilen i ModelRig…")

            installed = False
            install_detail = None
            base_url = modelrig_base_url()
            if payload.get("install_in_modelrig") and base_url:
                try:
                    install_voice(base_url, result.package, token=modelrig_token())
                    installed = True
                except ModelRigUnavailable as exc:
                    install_detail = str(exc)

            manifest = validate_package(result.package)
            final_result = {
                "voice": {
                    "id": manifest["id"],
                    "name": manifest["name"],
                    "language": manifest["language"],
                },
                "package": result.package.name,
                "download_url": f"/api/packages/{result.package.name}",
                "installed_in_modelrig": installed,
                "modelrig_detail": install_detail,
                "diarization_used": result.diarization_used,
                "gpu": cuda_memory_stats(),
                "source": source_status(),
                "pid": os.getpid(),
            }
            self._update(
                job_id,
                state="succeeded",
                progress=100,
                stage="complete",
                message="Stemmen er klar.",
                speaker_choices=None,
                reference_choices=None,
                result=final_result,
                error=None,
            )
            self._cleanup_inputs(job_id)
        except SpeakerSelectionRequired as exc:
            self._update(
                job_id,
                state="needs_speaker",
                progress=40,
                stage="speaker_selection",
                message=str(exc),
                speaker_choices=exc.choices,
                reference_choices=None,
                reference_choice=None,
                error=None,
            )
        except ReferenceSelectionRequired as exc:
            self._update(
                job_id,
                state="needs_reference",
                progress=65,
                stage="reference_selection",
                message=str(exc),
                speaker_choices=None,
                reference_choices=exc.choices,
                error=None,
            )
        except BuildCancelled as exc:
            self._update(
                job_id,
                state="cancelled",
                stage="cancelled",
                message=str(exc),
                speaker_choices=None,
                reference_choices=None,
                result=None,
                error=None,
            )
            self._cleanup_inputs(job_id)
        except Exception as exc:  # noqa: BLE001 - job boundary must persist useful failure state
            self._update(
                job_id,
                state="failed",
                stage="failed",
                message="Voice-build fejlede.",
                speaker_choices=None,
                reference_choices=None,
                result=None,
                error=str(exc),
            )
            self._cleanup_inputs(job_id)
        finally:
            with self._lock:
                self._active.discard(job_id)
                self._cancel.discard(job_id)

    def get(self, job_id: str) -> dict:
        with self._lock:
            return self._public(self._read(job_id))

    def recent(self, limit: int = 20) -> list[dict]:
        limit = max(1, min(100, int(limit)))
        jobs: list[dict] = []
        for path in self._root().glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict) and payload.get("id"):
                    jobs.append(self._public(payload))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
        jobs.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return jobs[:limit]

    def choose_speaker(self, job_id: str, anchor: str) -> dict:
        with self._lock:
            payload = self._read(job_id)
            if payload.get("state") != "needs_speaker":
                raise ValueError("Jobbet venter ikke på et speaker-valg.")
            choices = payload.get("speaker_choices") or []
            valid_anchors = {str(item.get("anchor")) for item in choices if isinstance(item, dict)}
            if anchor not in valid_anchors:
                raise ValueError("Det valgte speaker-anker hører ikke til dette job.")
            payload.update(
                state="queued",
                progress=40,
                stage="queued",
                message="Speaker valgt. Venter på GPU-køen…",
                speaker_anchor=anchor,
                speaker_choices=None,
                reference_choice=None,
                reference_choices=None,
                error=None,
            )
            self._write(payload)
        self._submit(job_id)
        return self.get(job_id)

    def choose_reference(self, job_id: str, choice: int) -> dict:
        with self._lock:
            payload = self._read(job_id)
            if payload.get("state") != "needs_reference":
                raise ValueError("Jobbet venter ikke på et referencevalg.")
            choices = payload.get("reference_choices") or []
            valid_choices = {
                int(item.get("choice"))
                for item in choices
                if isinstance(item, dict) and isinstance(item.get("choice"), int)
            }
            if choice not in valid_choices:
                raise ValueError("Det valgte referenceklip hører ikke til dette job.")
            payload.update(
                state="queued",
                progress=65,
                stage="queued",
                message="Reference valgt. Bygger den endelige stemme…",
                reference_choice=int(choice),
                reference_choices=None,
                error=None,
            )
            self._write(payload)
        self._submit(job_id)
        return self.get(job_id)

    def cancel(self, job_id: str) -> dict:
        with self._lock:
            payload = self._read(job_id)
            state = payload.get("state")
            if state in _TERMINAL:
                return self._public(payload)
            if state in {"needs_speaker", "needs_reference"}:
                payload.update(
                    state="cancelled",
                    stage="cancelled",
                    message="Voice-build blev annulleret.",
                    speaker_choices=None,
                    reference_choices=None,
                    error=None,
                )
                self._write(payload)
                self._cleanup_inputs(job_id)
                return self._public(payload)
            self._cancel.add(job_id)
            payload.update(state="cancelling", message="Annullerer ved næste sikre checkpoint…")
            self._write(payload)
            return self._public(payload)

    def recover(self) -> None:
        """Recover interrupted local jobs after a service restart.

        Jobs that were running are safe to restart from the original local
        uploads because package writes are atomic. Speaker/reference selection
        jobs stay paused with their local choices until the user decides.
        """
        for path in self._root().glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict) or not payload.get("id"):
                continue
            job_id = str(payload["id"])
            state = payload.get("state")
            if state == "cancelling":
                self._update(
                    job_id,
                    state="cancelled",
                    stage="cancelled",
                    message="Jobbet var ved at blive annulleret, da VoiceRig genstartede.",
                    speaker_choices=None,
                    reference_choices=None,
                )
                self._cleanup_inputs(job_id)
                continue
            if state in {"needs_speaker", "needs_reference"}:
                if not self._work_dir(job_id).is_dir():
                    self._update(
                        job_id,
                        state="failed",
                        stage="failed",
                        message="VoiceRig genstartede, og de midlertidige kildefiler mangler.",
                        speaker_choices=None,
                        reference_choices=None,
                        error="Job recovery failed: source files missing",
                    )
                continue
            if state in {"queued", "running"}:
                inputs = payload.get("inputs") or []
                work = self._work_dir(job_id)
                if inputs and all((work / name).is_file() for name in inputs):
                    self._update(
                        job_id,
                        state="queued",
                        stage="queued",
                        message="Genoptager jobbet efter VoiceRig-genstart…",
                    )
                    self._submit(job_id)
                else:
                    self._update(
                        job_id,
                        state="failed",
                        stage="failed",
                        message="VoiceRig kunne ikke genoptage jobbet efter genstart.",
                        error="Job recovery failed: source files missing",
                    )
                    self._cleanup_inputs(job_id)


job_manager = VoiceJobManager()
