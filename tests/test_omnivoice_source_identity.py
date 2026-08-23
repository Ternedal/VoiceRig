from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import voicerig.engines.omnivoice_worker as worker
from voicerig.model_contract import OMNIVOICE_SOURCE_REVISION


class _Distribution:
    def __init__(self, direct_url: dict):
        self.direct_url = direct_url

    def read_text(self, name: str) -> str | None:
        assert name == "direct_url.json"
        return json.dumps(self.direct_url)


def test_worker_returns_actual_matching_pep610_commit(monkeypatch):
    direct_url = {
        "url": "https://github.com/k2-fsa/OmniVoice.git",
        "vcs_info": {
            "vcs": "git",
            "requested_revision": OMNIVOICE_SOURCE_REVISION,
            "commit_id": OMNIVOICE_SOURCE_REVISION,
        },
    }
    monkeypatch.setattr(worker.metadata, "distribution", lambda name: _Distribution(direct_url))

    actual = worker._installed_source_revision(OMNIVOICE_SOURCE_REVISION.upper())

    assert actual == OMNIVOICE_SOURCE_REVISION.lower()


def test_worker_fails_closed_on_different_omnivoice_commit(monkeypatch):
    wrong = "0" * 40
    direct_url = {
        "url": "https://github.com/k2-fsa/OmniVoice.git",
        "vcs_info": {
            "vcs": "git",
            "requested_revision": wrong,
            "commit_id": wrong,
        },
    }
    monkeypatch.setattr(worker.metadata, "distribution", lambda name: _Distribution(direct_url))

    with pytest.raises(RuntimeError, match="source-identitet"):
        worker._installed_source_revision(OMNIVOICE_SOURCE_REVISION)


def test_worker_fails_closed_without_vcs_metadata(monkeypatch):
    monkeypatch.setattr(worker.metadata, "distribution", lambda name: _Distribution({"url": "local"}))

    with pytest.raises(RuntimeError, match="source-identitet"):
        worker._installed_source_revision(OMNIVOICE_SOURCE_REVISION)


def test_worker_requires_omnivoice_import_to_resolve_inside_isolated_runtime(tmp_path: Path, monkeypatch):
    runtime = tmp_path / "isolated-runtime"
    origin = runtime / "Lib" / "site-packages" / "omnivoice" / "__init__.py"
    monkeypatch.setattr(worker.sys, "prefix", str(runtime))
    monkeypatch.setattr(
        worker.importlib.util,
        "find_spec",
        lambda name: SimpleNamespace(origin=str(origin)),
    )

    actual = worker._external_import_origin()

    assert Path(actual) == origin.resolve()


def test_worker_rejects_shadowed_omnivoice_import_outside_runtime(tmp_path: Path, monkeypatch):
    runtime = tmp_path / "isolated-runtime"
    shadow = tmp_path / "checkout" / "voicerig" / "engines" / "omnivoice.py"
    monkeypatch.setattr(worker.sys, "prefix", str(runtime))
    monkeypatch.setattr(
        worker.importlib.util,
        "find_spec",
        lambda name: SimpleNamespace(origin=str(shadow)),
    )

    with pytest.raises(RuntimeError, match="shadowed"):
        worker._external_import_origin()
