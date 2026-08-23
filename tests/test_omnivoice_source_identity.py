from __future__ import annotations

import json

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
