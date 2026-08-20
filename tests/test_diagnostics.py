from __future__ import annotations

import io
import json
import logging
import zipfile
from pathlib import Path

import voicerig.diagnostics as diagnostics
from voicerig.app.ops_api import _safe_job


def test_redacting_formatter_removes_tokens():
    formatter = diagnostics._RedactingFormatter("%(message)s")
    record = logging.LogRecord(
        name="voicerig.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Authorization: Bearer supersecret HF_TOKEN=abc MODELRIG_TOKEN=def token=ghi",
        args=(),
        exc_info=None,
    )

    text = formatter.format(record)

    assert "supersecret" not in text
    assert "abc" not in text
    assert "def" not in text
    assert "ghi" not in text
    assert text.count("[REDACTED]") >= 4


def test_support_bundle_contains_metadata_and_log_only(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(diagnostics, "data_dir", lambda: tmp_path)
    log = tmp_path / "logs" / "voicerig.log"
    log.parent.mkdir(parents=True)
    log.write_text("MODELRIG_TOKEN=secret\nnormal line\n", encoding="utf-8")
    # Files that must never be swept into the support bundle.
    (tmp_path / "secret.mrvoice").write_bytes(b"profile")
    (tmp_path / "source.wav").write_bytes(b"RIFF-private")

    raw = diagnostics.build_support_bundle(
        {"version": "1.0", "privacy": {"contains_source_audio": False}}
    )

    with zipfile.ZipFile(io.BytesIO(raw), "r") as zf:
        assert set(zf.namelist()) == {"diagnostics.json", "voicerig.log", "README.txt"}
        assert json.loads(zf.read("diagnostics.json"))["version"] == "1.0"
        text = zf.read("voicerig.log").decode("utf-8")
        assert "secret" not in text
        assert "[REDACTED]" in text
        assert b"RIFF-private" not in raw
        assert b"profile" not in raw


def test_safe_job_excludes_original_files_and_speaker_audio():
    safe = _safe_job(
        {
            "id": "a" * 32,
            "state": "needs_speaker",
            "progress": 40,
            "stage": "speaker_selection",
            "message": "choose",
            "name": "Test",
            "language": "da",
            "files": ["private-interview.mp4"],
            "speaker_choices": [
                {"anchor": "0:1.0", "preview_wav_base64": "PRIVATE_AUDIO"}
            ],
            "result": None,
        }
    )

    encoded = json.dumps(safe)
    assert "private-interview" not in encoded
    assert "PRIVATE_AUDIO" not in encoded
    assert "speaker_choices" not in safe
    assert "files" not in safe
