from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_no_private_homeserver_ip_in_runtime_source():
    for path in (ROOT / "src").rglob("*.py"):
        private_ip = ".".join(("192", "168", "178", "190"))
        assert private_ip not in path.read_text(encoding="utf-8"), path


def test_ollama_is_not_bundled_as_service():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "\n  ollama:" not in compose


def test_control_center_keeps_complete_ui_contract():
    text = (ROOT / "src/core/prompt_ui.py").read_text(encoding="utf-8")
    for required in (
        "paperless-local-ai Control Center",
        "Overview",
        "Classification",
        "Correspondent fallback",
        "App Settings",
        "Pipeline &amp; Tags",
        "Test before production.",
        "What do Validate and Save do?",
        "Available placeholders",
        "System message sent to the model",
        "User message sent to the model",
        "Model response and validation",
        "Test request details",
        "Expected JSON output",
        "Off — manual testing only",
        "On — run when correspondent is empty",
        "No correspondent · fallback disabled",
        "No correspondent · fallback enabled",
        "Load preset into draft",
        "classPromptPreset",
        "corrPromptPreset",
        "ocrLanguageOptions",
    ):
        assert required in text
    assert "Prompt Studio" not in text


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
    lines = [
        line.strip()
        for line in (ROOT / "requirements/ocr.txt").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    expected_packages = {
        "paddleocr",
        "paddlex",
        "PyMuPDF",
        "requests",
        "numpy",
        "opencv-contrib-python",
        "Pillow",
        "shapely",
        "pyclipper",
    }

    pinned_packages = set()

    for line in lines:
        assert "==" in line, f"Dependency is not exactly pinned: {line}"

        package, version = line.split("==", 1)

        assert package, f"Missing package name: {line}"
        assert version, f"Missing pinned version: {line}"
        assert package not in pinned_packages, f"Duplicate dependency: {package}"

        pinned_packages.add(package)

    assert pinned_packages == expected_packages


def test_third_party_license_notice_covers_pymupdf():
    notice = (ROOT / "THIRD_PARTY_LICENSES.md").read_text(encoding="utf-8")
    assert "PyMuPDF" in notice
    assert "AGPL" in notice

    for path in (ROOT / "docker").glob("*.Dockerfile"):
        text = path.read_text(encoding="utf-8")
        assert "org.opencontainers.image.licenses=\"MIT\"" not in text
