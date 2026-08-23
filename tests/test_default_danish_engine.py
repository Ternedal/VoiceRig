from pathlib import Path

import voicerig.app.pipeline as pipeline
from voicerig.analysis.reference import ReferenceCandidate
from voicerig.engines.catalog import CURRENT_ENGINE, ROST_DANISH_ENGINE_SPEC


def test_danish_build_engine_is_rost_without_changing_other_languages():
    assert pipeline._build_engine_spec("da") == ROST_DANISH_ENGINE_SPEC
    assert pipeline._build_engine_spec("da-DK") == ROST_DANISH_ENGINE_SPEC
    assert pipeline._build_engine_spec("DA") == ROST_DANISH_ENGINE_SPEC
    assert pipeline._build_engine_spec("en") == CURRENT_ENGINE


def test_danish_artifact_builder_uses_rost(monkeypatch, tmp_path: Path):
    reference = tmp_path / "reference.wav"
    conditioning = tmp_path / "conditioning.pt"
    preview = tmp_path / "preview.wav"
    reference.write_bytes(b"reference")
    calls = []

    def fake_rost(ref, cond, out):
        calls.append((ref, cond, out))
        cond.write_bytes(b"rost-conditioning")
        out.write_bytes(b"rost-preview")
        return cond, out

    monkeypatch.setattr(pipeline, "build_rost_danish_artifacts", fake_rost)
    monkeypatch.setattr(
        pipeline,
        "ChatterboxEngine",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("general Chatterbox used for Danish build")),
    )

    result = pipeline._build_artifacts_for_language(reference, conditioning, preview, "da")

    assert result == (conditioning, preview)
    assert calls == [(reference, conditioning, preview)]


def test_reference_auditions_use_same_rost_engine_as_final_danish_profile(monkeypatch, tmp_path: Path):
    source = tmp_path / "source.wav"
    source.write_bytes(b"source")
    ranked = [
        ReferenceCandidate(source=source, start=0.0, duration=8.0, score=0.9, speaker="speaker")
    ]
    calls = []

    def fake_materialize(_candidate, target):
        target.write_bytes(b"reference")
        return target

    def fake_artifacts(reference, conditioning, preview, language, accent=None):
        calls.append((reference.name, language, accent))
        conditioning.write_bytes(b"conditioning")
        preview.write_bytes(b"preview")
        return conditioning, preview

    monkeypatch.setattr(pipeline, "_materialize_reference", fake_materialize)
    monkeypatch.setattr(pipeline, "_build_artifacts_for_language", fake_artifacts)
    monkeypatch.setattr(pipeline, "validate_wav", lambda *args, **kwargs: {"duration": 1.5})

    choices = pipeline._reference_choices(tmp_path, ranked, "da", None)

    assert calls == [("reference-choice-01.wav", "da", None)]
    assert choices[0]["engine"] == ROST_DANISH_ENGINE_SPEC.name
    assert choices[0]["engine_label"] == ROST_DANISH_ENGINE_SPEC.label


def test_new_danish_package_is_built_with_rost_manifest(monkeypatch, tmp_path: Path):
    source = tmp_path / "clip.wav"
    source.write_bytes(b"input")
    output_dir = tmp_path / "out"
    captured = {}

    def fake_extract(_source, target):
        target.write_bytes(b"wav")
        return target

    def fake_materialize(_candidate, target):
        target.write_bytes(b"reference")
        return target

    def fake_artifacts(_reference, conditioning, preview, _language, accent=None):
        assert accent is None
        conditioning.write_bytes(b"conditioning")
        preview.write_bytes(b"preview")
        return conditioning, preview

    def fake_build_package(name, language, reference, conditioning, preview, output, **kwargs):
        captured["name"] = name
        captured["language"] = language
        captured["engine_spec"] = kwargs.get("engine_spec")
        captured["accent"] = kwargs.get("accent")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"package")
        return output

    monkeypatch.setattr(pipeline, "extract_mono_wav", fake_extract)
    monkeypatch.setattr(pipeline, "diarize_many", lambda _wavs: [])
    monkeypatch.setattr(pipeline, "speaker_clusters", lambda _results: ())
    monkeypatch.setattr(pipeline, "primary_speaker_segments", lambda _results, speaker_choice=None: {})
    monkeypatch.setattr(pipeline, "allow_undiarized_fallback", lambda: True)
    monkeypatch.setattr(
        pipeline,
        "rank_references",
        lambda wavs, diarizations, limit: [
            ReferenceCandidate(source=wavs[0], start=0.0, duration=8.0, score=0.9, speaker=None)
        ],
    )
    monkeypatch.setattr(pipeline, "_materialize_reference", fake_materialize)
    monkeypatch.setattr(pipeline, "_build_artifacts_for_language", fake_artifacts)
    monkeypatch.setattr(pipeline, "validate_wav", lambda *args, **kwargs: {"duration": 1.0})
    monkeypatch.setattr(pipeline, "build_package", fake_build_package)

    result = pipeline.create_voice("Dansk standard", [source], output_dir, language="da")

    assert result.package.read_bytes() == b"package"
    assert captured["language"] == "da"
    assert captured["engine_spec"] == ROST_DANISH_ENGINE_SPEC
    assert captured["accent"] is None
