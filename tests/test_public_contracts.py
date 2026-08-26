import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _is_rfc1918(value: str) -> bool:
    parts = [int(part) for part in value.split(".")]
    return (
        parts[0] == 10
        or (parts[0] == 172 and 16 <= parts[1] <= 31)
        or (parts[0] == 192 and parts[1] == 168)
    )


def test_no_literal_rfc1918_addresses_in_public_text_files():
    ipv4 = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
    text_suffixes = {".py", ".md", ".yaml", ".yml", ".txt", ".json"}
    text_names = {".env.example", "Makefile", "VERSION"}
    public_dirs = ("src", "tests", "docs", ".github", "deploy", "requirements", "docker", "scripts")
    paths = [
        path
        for path in ROOT.iterdir()
        if path.is_file() and (path.suffix in text_suffixes or path.name in text_names)
    ]
    for dirname in public_dirs:
        directory = ROOT / dirname
        if directory.exists():
            paths.extend(
                path
                for path in directory.rglob("*")
                if path.is_file() and (path.suffix in text_suffixes or path.name in text_names)
            )
    for path in paths:
        content = path.read_text(encoding="utf-8")
        for match in ipv4.finditer(content):
            value = match.group(0)
            parts = value.split(".")
            if any(int(part) > 255 for part in parts):
                continue
            assert not _is_rfc1918(value), f"literal RFC1918 address in {path}: {value}"


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
        "Hybrid tagging",
        "LLM direct",
        "Recommended for small models",
        "For more capable models",
        "How Hybrid tagging works",
        "History health",
        "Advanced History matching",
        "Minimum similarity",
        "Minimum support",
        "Minimum winner share",
        "Save History matching",
        "Retrospective history reuse",
        "History depth by tag",
        "Potential tag inconsistencies",
        "review hint, not an error detector",
        "Tag guidance",
        "Tagging prompt",
        "taggingPrompt",
        "omitted entirely",
        "Refresh reviewed history",
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
        "Maximum OCR image side",
        "Automatic OCR retries",
        "OCR recovery",
        "Retry now",
        "Recent OCR failures",
        "Thinking",
        "Temperature",
        "Keep alive",
        "Dry run (no metadata writes)",
        "Document text limit (characters)",
        "Classification settings",
        "App settings",
        "New sender candidate · not auto-created",
        "PAPERLESS_SETUP_DOCS_URL",
        "/api/app/ocr/health",
        "appOcrRetryDelays",
    ):
        assert required in text
    for obsolete in (
        "History-assisted",
        "LLM only",
        "Correspondent fallback",
        "/api/correspondent/",
        "corrPromptPreset",
        "Automatic fallback",
        "Stage 1",
        "Stage 2",
        "Prompt Studio",
        "Additional model reasoning",
        "Output randomness",
        "The settings most likely to matter during normal operation.",
        "Maximum OCR image dimension",
        "Estimated reusable history",
    ):
        assert obsolete not in text
    doc_input = re.search(r'<input[^>]+id="docId"[^>]*>', text)
    assert doc_input is not None
    assert not re.search(r'\bvalue\s*=', doc_input.group(0))


def test_control_center_docs_links_follow_built_app_version():
    ui = (ROOT / "src/core/prompt_ui.py").read_text(encoding="utf-8")
    dockerfile = (ROOT / "docker/core.Dockerfile").read_text(encoding="utf-8")
    assert 'APP_VERSION = os.getenv("APP_VERSION", "dev")' in ui
    assert 'DOCS_REF = "main" if APP_VERSION in {"dev", "main"}' in ui
    assert 'PAPERLESS_SETUP_DOCS_URL' in ui
    assert 'ENV APP_VERSION="${APP_VERSION}"' in dockerfile


def test_history_runtime_is_confidence_gated():
    common = (ROOT / "src/core/history_common.py").read_text(encoding="utf-8")
    runtime = (ROOT / "src/core/history_runtime.py").read_text(encoding="utf-8")
    combined = common + "\n" + runtime
    assert "HISTORY_MATCH_SIMILARITY_DEFAULT = 0.62" in (ROOT / "src/common/app_config.py").read_text(encoding="utf-8")
    assert "HISTORY_MIN_SUPPORT_DEFAULT = 2" in (ROOT / "src/common/app_config.py").read_text(encoding="utf-8")
    assert "HISTORY_MIN_WINNER_SHARE_DEFAULT = 0.50" in (ROOT / "src/common/app_config.py").read_text(encoding="utf-8")
    assert "complete_leaf_tag_set" in combined
    assert "tuple(entry[\"tags\"])" in runtime
    assert "MAX_EXAMPLES = 5" in combined
    assert "MAX_EXAMPLES_PER_TAG_SET = 2" in combined
    assert "EXAMPLE_MIN_SIMILARITY = 0.08" in combined
    assert "AgglomerativeClustering" in runtime
    assert 'linkage="complete"' in runtime
    assert "NearestNeighbors" in runtime
    assert 'metric="cosine"' in runtime
    assert 'algorithm="brute"' in runtime
    assert "cosine_similarity" in runtime


def test_persistent_core_processes_keep_scientific_history_runtime_out_of_idle():
    worker = (ROOT / "src/core/worker.py").read_text(encoding="utf-8")
    ui = (ROOT / "src/core/prompt_ui.py").read_text(encoding="utf-8")
    broker = (ROOT / "src/core/history_broker.py").read_text(encoding="utf-8")
    engine = (ROOT / "src/core/history_engine.py").read_text(encoding="utf-8")
    assert "from history_runtime" not in worker
    assert "from history_runtime" not in ui
    assert "HistoryBroker" in worker
    assert "subprocess.Popen" in broker
    assert "from history_runtime import HistoryIndex" in engine
    assert "routing_docs.clear()" in worker
    assert "fresh = current_document(doc_id)" in worker
    assert "Document content changed after History batch routing" in worker


def test_history_cache_is_versioned_and_integrity_checked():
    common = (ROOT / "src/core/history_common.py").read_text(encoding="utf-8")
    engine = (ROOT / "src/core/history_engine.py").read_text(encoding="utf-8")
    assert "HISTORY_CACHE_FORMAT_VERSION" in common
    assert "HISTORY_ALGORITHM_VERSION" in common
    assert "HISTORY_APP_VERSION" in common
    assert 'importlib.metadata.version("scikit-learn")' in common
    assert "cache_sha256" in engine
    assert "history_algorithm_signature" in common
    assert '"status": persisted_status' in engine
    assert "pickle.dumps(payload, protocol=5)" in engine
    assert "os.replace" in engine
    cached_state = common.split("def cached_history_state", 1)[1].split("def _recv_json_line", 1)[0]
    assert ".read_bytes()" not in cached_state


def test_hybrid_fast_path_omits_tag_prompt_and_schema_field():
    runtime = (ROOT / "src/core/prompt_runtime.py").read_text(encoding="utf-8")
    assert '"tagging_prompt"' in runtime
    assert 'if tags_enabled:' in runtime
    assert 'properties["tags"]' in runtime
    assert 'render_template(config["tagging_prompt"], values)' in runtime
    assert '"tags must be omitted when the LLM is not responsible for tag selection"' in runtime
    assert "return tags as an empty array" not in runtime


def test_correspondent_is_resolved_without_second_llm_stage():
    worker = (ROOT / "src/core/worker.py").read_text(encoding="utf-8")
    runtime = (ROOT / "src/core/prompt_runtime.py").read_text(encoding="utf-8")
    resolver = (ROOT / "src/core/correspondent_resolver.py").read_text(encoding="utf-8")
    assert "resolve_correspondent" in worker
    assert "correspondent_runtime" not in worker
    assert "correspondent_fallback" not in worker
    assert '"correspondent": {"type": "string"}' in runtime
    assert "FUZZY_MATCH_THRESHOLD = 0.93" in resolver
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


def test_ocr_heavy_worker_does_not_use_python_multiprocessing():
    service = (ROOT / "src/ocr/service.py").read_text(encoding="utf-8")
    engine = (ROOT / "src/ocr/paddle_engine.py").read_text(encoding="utf-8")
    assert "multiprocessing" not in service
    assert "subprocess.Popen" in service
    assert "socket.socketpair()" in service
    assert "page_out_self_file_mappings" in engine
    assert "page_out_self_resident_file_cache" not in engine
    assert "os._exit" in engine
    assert "recycle_event.set()" in service
    assert "server.handle_request()" in service
    assert "RESTART_POLICY_ARM_SECONDS = 11.0" in service
    assert "uptime >= RESTART_POLICY_ARM_SECONDS" in service


def test_ocr_service_has_restart_policy_for_idle_container_recycle():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    truenas = (ROOT / "deploy/truenas/compose.example.yaml").read_text(encoding="utf-8")
    for text in (compose, truenas):
        ocr_section = text.split("\n  ocr-service:", 1)[1].split("\n  core-service:", 1)[0]
        assert "restart: unless-stopped" in ocr_section


def test_core_and_ocr_compose_healthchecks_use_dedicated_binary():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    truenas = (ROOT / "deploy/truenas/compose.example.yaml").read_text(encoding="utf-8")
    core_dockerfile = (ROOT / "docker/core.Dockerfile").read_text(encoding="utf-8")
    ocr_dockerfile = (ROOT / "docker/ocr.Dockerfile").read_text(encoding="utf-8")
    for text in (compose, truenas):
        assert 'test: ["CMD", "/usr/local/bin/plai-healthcheck"]' in text
        assert 'test: ["CMD", "/usr/local/bin/plai-healthcheck", "--ocr"]' in text
        assert "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8082/health'" not in text
    assert "/src/target/release/plai-healthcheck /usr/local/bin/plai-healthcheck" in core_dockerfile
    assert "x86_64-unknown-linux-musl" in ocr_dockerfile
    assert "/plai-healthcheck /usr/local/bin/plai-healthcheck" in ocr_dockerfile


def test_core_recycles_after_complete_heavy_work_boundaries():
    state = (ROOT / "rust/core/src/state.rs").read_text(encoding="utf-8")
    main = (ROOT / "rust/core/src/main.rs").read_text(encoding="utf-8")
    worker = (ROOT / "rust/core/src/worker.rs").read_text(encoding="utf-8")
    control = (ROOT / "rust/core/src/control.rs").read_text(encoding="utf-8")
    assert "pub struct RecycleSignal" in state
    assert "CoreEvent::Recycle" in main
    assert "RESTART_POLICY_ARM_SECONDS: u64 = 11" in main
    assert "had_jobs && state.recycle.request()" in worker
    assert "history::refresh_history(&state.history, config.max_tags, true)" in control
    assert "History refresh completed; requesting clean core restart" in control


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


def test_public_docs_describe_current_tagging_product():
    docs = [
        ROOT / "README.md",
        ROOT / "docs/architecture.md",
        ROOT / "docs/configuration.md",
        ROOT / "docs/tagging.md",
        ROOT / "docs/compatibility.md",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in docs)
    assert "Hybrid tagging" in combined
    assert "LLM direct" in combined
    assert "History depth by tag" in combined
    assert "Paperless native classifier vs Hybrid tagging" in combined
    assert "History-assisted" not in combined
    assert "LLM-only tagging remains" not in combined
    assert "pre-0.3" not in combined
    assert "correspondent fallback" not in combined.lower()
