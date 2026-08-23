from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi.responses import FileResponse

from voicerig.app import ops_api


UI_DIR = Path(__file__).resolve().parents[1] / "voicerig" / "ui"


def test_index_references_packaged_assets_and_modelrig_secret_controls():
    html = (UI_DIR / "index.html").read_text(encoding="utf-8")

    assert 'href="/ui/styles.css"' in html
    assert 'src="/ui/app.js"' in html
    assert 'src="/ui/reference-flow.js"' in html
    assert 'src="/ui/danish-engine-compare.js"' in html
    assert "1–20 lyd- eller videoklip" in html
    assert "ca. 3,2 GB" in html
    assert 'id="modelrigToken"' in html
    assert 'type="password"' in html
    assert 'id="saveModelrigToken"' in html
    assert 'id="clearModelrigToken"' in html
    assert 'id="voiceTester"' in html
    assert 'id="compareRostVoice"' in html
    assert 'id="rostCompareAudio"' in html
    assert 'id="compareOmniVoice"' in html
    assert 'id="omnivoiceCompareAudio"' in html
    assert 'id="compareRostReferences"' in html
    assert 'id="rostReferencePanel"' in html
    assert 'id="rostReferenceChoices"' in html
    assert "Kun den gemte reference skifter" in html


def test_javascript_uses_secret_safe_modelrig_configuration_contract():
    javascript = (UI_DIR / "app.js").read_text(encoding="utf-8")

    assert "fetch('/api/modelrig/config')" in javascript
    assert "form.append('token', token)" in javascript
    assert "token_configured" in javascript
    assert "modelrigTokenInput.value = ''" in javascript
    assert "state.modelrigConfig" in javascript
    assert "state.modelrigToken" not in javascript


def test_reference_flow_exposes_real_auditions_and_additive_twenty_file_selection():
    javascript = (UI_DIR / "reference-flow.js").read_text(encoding="utf-8")

    assert "MAX_UI_FILES = 20" in javascript
    assert "job.state === 'needs_reference'" in javascript
    assert "reference.preview_wav_base64" in javascript
    assert "reference.source_clip_count" in javascript
    assert "samlet fra ${sourceCount} klip" in javascript
    assert "Brug denne reference" in javascript
    assert "/reference`" in javascript
    assert "resumeReferenceJob" in javascript
    assert "function addFiles(files)" in javascript
    assert "const merged = [...state.files]" in javascript
    assert "fileIdentity" in javascript
    assert "picker.value = ''" in javascript
    assert "stopImmediatePropagation" in javascript
    assert "filer valgt" in javascript


def test_danish_engine_compare_flow_is_non_mutating_until_explicit_rost_promotion():
    javascript = (UI_DIR / "danish-engine-compare.js").read_text(encoding="utf-8")

    assert "endpoint: '/api/tts/compare/rost'" in javascript
    assert "endpoint: '/api/tts/compare/omnivoice'" in javascript
    assert "fetch(engine.endpoint" in javascript
    assert "voice_package: voice.package" in javascript
    assert "3,2 GB" in javascript
    assert "isoleret runtime-miljø" in javascript
    assert "setComparisonBusy(true)" in javascript
    assert "synthesizeVoiceButton.disabled = busy" in javascript
    assert "state[`${engine.key}CompareAudioUrl`]" in javascript
    assert "'/api/tts/compare/rost/references'" in javascript
    assert "'/api/tts/compare/rost/reference'" in javascript
    assert "reference_index: reference.index" in javascript
    assert "samme Røst-model og parametre" in javascript
    assert "Brug ${reference.label} med Røst" in javascript
    assert "window.confirm" in javascript
    assert "'/api/tts/rost/promote-reference'" in javascript
    assert "Pakken erstattes først efter fuld validering" in javascript
    assert "Afspil nuværende motor" in javascript
    assert "refreshLibrary()" in javascript
    assert "refreshSystem()" in javascript


def test_ui_javascript_parses_when_node_is_available():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed in this test environment")
    for filename in ("reference-flow.js", "danish-engine-compare.js"):
        subprocess.run(
            [node, "--check", str(UI_DIR / filename)],
            check=True,
            capture_output=True,
            text=True,
        )


def test_ui_asset_routes_are_fixed_files():
    js = ops_api.ui_app_js()
    reference_js = ops_api.ui_reference_flow_js()
    compare_js = ops_api.ui_danish_engine_compare_js()
    css = ops_api.ui_styles_css()

    assert isinstance(js, FileResponse)
    assert isinstance(reference_js, FileResponse)
    assert isinstance(compare_js, FileResponse)
    assert isinstance(css, FileResponse)
    assert Path(js.path).resolve() == (UI_DIR / "app.js").resolve()
    assert Path(reference_js.path).resolve() == (UI_DIR / "reference-flow.js").resolve()
    assert Path(compare_js.path).resolve() == (UI_DIR / "danish-engine-compare.js").resolve()
    assert Path(css.path).resolve() == (UI_DIR / "styles.css").resolve()
    assert js.media_type == "text/javascript"
    assert reference_js.media_type == "text/javascript"
    assert compare_js.media_type == "text/javascript"
    assert css.media_type == "text/css"
