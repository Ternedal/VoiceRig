from pathlib import Path

from fastapi.responses import FileResponse

from voicerig.app import ops_api


UI_DIR = Path(__file__).resolve().parents[1] / "voicerig" / "ui"


def test_index_references_packaged_assets_and_modelrig_secret_controls():
    html = (UI_DIR / "index.html").read_text(encoding="utf-8")

    assert 'href="/ui/styles.css"' in html
    assert 'src="/ui/app.js"' in html
    assert 'src="/ui/reference-flow.js"' in html
    assert "1–20 lyd- eller videoklip" in html
    assert 'id="modelrigToken"' in html
    assert 'type="password"' in html
    assert 'id="saveModelrigToken"' in html
    assert 'id="clearModelrigToken"' in html
    assert 'id="voiceTester"' in html


def test_javascript_uses_secret_safe_modelrig_configuration_contract():
    javascript = (UI_DIR / "app.js").read_text(encoding="utf-8")

    assert "fetch('/api/modelrig/config')" in javascript
    assert "form.append('token', token)" in javascript
    assert "token_configured" in javascript
    assert "modelrigTokenInput.value = ''" in javascript
    assert "state.modelrigConfig" in javascript
    assert "state.modelrigToken" not in javascript


def test_reference_flow_exposes_real_auditions_and_twenty_file_limit():
    javascript = (UI_DIR / "reference-flow.js").read_text(encoding="utf-8")

    assert "MAX_UI_FILES = 20" in javascript
    assert "job.state === 'needs_reference'" in javascript
    assert "reference.preview_wav_base64" in javascript
    assert "Brug denne reference" in javascript
    assert "/reference`" in javascript
    assert "resumeReferenceJob" in javascript


def test_ui_asset_routes_are_fixed_files():
    js = ops_api.ui_app_js()
    reference_js = ops_api.ui_reference_flow_js()
    css = ops_api.ui_styles_css()

    assert isinstance(js, FileResponse)
    assert isinstance(reference_js, FileResponse)
    assert isinstance(css, FileResponse)
    assert Path(js.path).resolve() == (UI_DIR / "app.js").resolve()
    assert Path(reference_js.path).resolve() == (UI_DIR / "reference-flow.js").resolve()
    assert Path(css.path).resolve() == (UI_DIR / "styles.css").resolve()
    assert js.media_type == "text/javascript"
    assert reference_js.media_type == "text/javascript"
    assert css.media_type == "text/css"
