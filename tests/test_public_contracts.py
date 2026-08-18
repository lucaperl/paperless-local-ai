from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_no_private_homeserver_ip_in_runtime_source():
    for path in (ROOT / "src").rglob("*.py"):
        private_ip = ".".join(("192", "168", "178", "190"))
        assert private_ip not in path.read_text(encoding="utf-8"), path


def test_ollama_is_not_bundled_as_service():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "\n  ollama:" not in compose


def test_prompt_ui_keeps_two_stage_structure_plus_central_app_settings():
    text = (ROOT / "src/core/prompt_ui.py").read_text(encoding="utf-8")
    assert "1 · Klassifizierung" in text
    assert "2 · Korrespondent-Vorschlag" in text
    assert "App-Einstellungen" in text
    assert "Pipeline &amp; Tags" in text
    assert "Aus – nur manuell testen" in text
    assert "Ein – bei leerem Korrespondenten ausführen" in text


def test_env_example_contains_only_deployment_and_secret_settings():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for forbidden in (
        "PAPERLESS_URL=",
        "OLLAMA_URL=",
        "OCR_LANGUAGE=",
        "OCR_QUEUE_TAG=",
        "POLL_INTERVAL=",
        "DRY_RUN=",
        "CORRESPONDENT_SIGNATURE_WORDS=",
    ):
        assert forbidden not in text
    assert "PAPERLESS_TOKEN=" in text
    assert "APP_DATA_DIR=" in text


def test_single_app_data_directory_in_compose():
    text = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "APP_DATA_DIR" in text
    assert "OCR_DATA_DIR" not in text
    assert "CORE_DATA_DIR" not in text
    assert "COORDINATION_DIR" not in text


def test_public_compose_defaults_to_upstream_ghcr():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "ghcr.io/lucaperl/paperless-local-ai" in compose
    assert "YOUR_GITHUB_USER" not in compose


def test_true_nas_template_uses_same_upstream_images():
    text = (ROOT / "deploy/truenas/compose.example.yaml").read_text(encoding="utf-8")
    assert "ghcr.io/lucaperl/paperless-local-ai-core:stable" in text
    assert "ghcr.io/lucaperl/paperless-local-ai-ocr:stable" in text
    assert "paperless-local-ai-core:0.1.0-alpha" not in text


def test_tested_ocr_stack_is_pinned():
    text = (ROOT / "requirements/ocr.txt").read_text(encoding="utf-8")
    for requirement in (
        "paddleocr==3.7.0",
        "paddlex==3.7.2",
        "PyMuPDF==1.28.2",
        "numpy==1.26.2",
        "opencv-contrib-python==4.10.0.84",
        "Pillow==10.1.0",
        "shapely==2.1.2",
        "pyclipper==1.4.0",
    ):
        assert requirement in text


def test_third_party_license_notice_covers_pymupdf():
    notice = (ROOT / "THIRD_PARTY_LICENSES.md").read_text(encoding="utf-8")
    assert "PyMuPDF" in notice
    assert "AGPL" in notice

    for path in (ROOT / "docker").glob("*.Dockerfile"):
        text = path.read_text(encoding="utf-8")
        assert "org.opencontainers.image.licenses=\"MIT\"" not in text
