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
        "App Settings",
        "Pipeline &amp; Tags",
        "History-assisted",
        "LLM only",
        "Recommended for small models",
        "For more capable models",
        "History health",
        "Estimated reusable history",
        "Potential tag inconsistencies",
        "Tag guidance",
        "Guidance is used for every tag decision",
        "Refresh history",
        "/api/tagging/state",
        "/api/tagging/refresh",
        "Safe test with a real document",
        "Available placeholders",
        "System message sent to the model",
        "User message sent to the model",
        "Classification result",
        "Tagging route",
        "Output schema",
        "Load preset into draft",
        "classPromptPreset",
        "ocrLanguageOptions",
        "appOcrModelProfile",
        "PaddleOCR model",
        "PP-OCRv6 Medium — Highest quality · Recommended",
        "PP-OCRv6 Small — Lower inference cost",
        "PP-OCRv6 Tiny — Lowest inference cost · Lower accuracy",
        "Maximum OCR image dimension",
        "Automatic OCR retries",
        "OCR recovery",
        "Retry now",
        "Recent OCR failures",
        "Thinking",
        "Temperature",
        "Keep alive",
        "Dry run (no metadata writes)",
        "/api/app/ocr/health",
        "appOcrRetryDelays",
    ):
        assert required in text
    for obsolete in (
        "Correspondent fallback",
        "/api/correspondent/",
        "corrPromptPreset",
        "Automatic fallback",
        "Stage 1",
        "Stage 2",
        "Prompt Studio",
        "Additional model reasoning",
        "Output randomness",
        'value="93"',
    ):
        assert obsolete not in text


def test_history_runtime_is_confidence_gated():
    text = (ROOT / "src/core/history_runtime.py").read_text(encoding="utf-8")
    assert "FAST_SIMILARITY = 0.60" in text
    assert "MIN_SUPPORT = 2" in text
    assert "MIN_WINNER_SHARE = 0.50" in text
    assert "MAX_EXAMPLES = 5" in text
    assert "MAX_EXAMPLES_PER_TAG_SET = 2" in text
    assert "EXAMPLE_MIN_SIMILARITY = 0.08" in text
    assert "AgglomerativeClustering" in text
    assert 'linkage="complete"' in text


def test_correspondent_is_resolved_without_second_llm_stage():
    worker = (ROOT / "src/core/worker.py").read_text(encoding="utf-8")
    runtime = (ROOT / "src/core/prompt_runtime.py").read_text(encoding="utf-8")
    assert "resolve_correspondent" in worker
    assert "correspondent_runtime" not in worker
    assert "correspondent_fallback" not in worker
    assert '"correspondent": {"type": "string"}' in runtime
    assert not (ROOT / "src/core/correspondent_runtime.py").exists()


def test_env_example_contains_only_deployment_and_secret_settings():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for forbidden in (
        "PAPERLESS_URL=",
        "OLLAMA_URL=",
        "OCR_LANGUAGE=",
        "OCR_QUEUE_TAG=",
        "OCR_ERROR_TAG=",
        "POLL_INTERVAL=",
        "DRY_RUN=",
        "CORRESPONDENT_SIGNATURE_WORDS=",
    ):
        assert forbidden not in text
    assert "PAPERLESS_TOKEN=" in text
    assert "OCR_SERVICE_TOKEN=" in text
    assert "APP_DATA_DIR=" in text


def test_ocr_is_service_not_queue_worker():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "\n  ocr-service:" in compose
    assert "\n  ocr-worker:" not in compose
    assert "OCR_SERVICE_TOKEN" in compose
    assert "/integration" in compose


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


def test_tested_ocr_stack_is_pinned():
    lines = [
        line.strip()
        for line in (ROOT / "requirements/ocr.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    expected_packages = {
        "paddleocr",
        "paddlex",
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
        assert package and version
        assert package not in pinned_packages
        pinned_packages.add(package)
    assert pinned_packages == expected_packages


def test_core_history_dependency_is_pinned():
    text = (ROOT / "requirements/core.txt").read_text(encoding="utf-8")
    assert "requests==2.34.2" in text
    assert "scikit-learn==1.9.0" in text


def test_third_party_license_notice_matches_current_runtime():
    notice = (ROOT / "THIRD_PARTY_LICENSES.md").read_text(encoding="utf-8")
    for name in ("PaddlePaddle", "PaddleOCR", "PaddleX", "OpenVINO", "scikit-learn"):
        assert name in notice
    assert "PyMuPDF" not in notice


def test_public_docs_use_current_pipeline_contract():
    docs = [
        ROOT / "README.md",
        ROOT / "docs/architecture.md",
        ROOT / "docs/configuration.md",
        ROOT / "docs/tagging.md",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in docs)
    assert "History-assisted" in combined
    assert "LLM only" in combined
    assert "Potential tag inconsistencies" in combined
    assert "correspondent fallback" not in combined.lower()
