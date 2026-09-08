from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_published_compose_uses_two_persistent_services():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert "\n  core-service:\n" in compose
    assert "\n  ocr-service:\n" in compose

    assert "\n  metadata-worker:\n" not in compose
    assert "\n  prompt-ui:\n" not in compose
    assert "\n  suggestion-bridge:\n" not in compose

    assert 'command: ["/usr/local/bin/plai-core"]' in compose
    assert ":8080" in compose
    assert ":8081" in compose
    assert ":8082" in compose


def test_core_image_builds_and_defaults_to_rust_supervisor():
    dockerfile = (ROOT / "docker/core.Dockerfile").read_text(encoding="utf-8")

    assert "FROM rust:1.98.0-bookworm AS rust-builder" in dockerfile
    assert "cargo build --locked --release -p plai-core" in dockerfile
    assert 'CMD ["/usr/local/bin/plai-core"]' in dockerfile
    assert "COPY src/common/ /app/" in dockerfile
    assert "COPY src/core/ /app/" in dockerfile


def test_legacy_core_service_command_execs_rust_binary():
    dockerfile = (ROOT / "docker/core.Dockerfile").read_text(encoding="utf-8")

    assert "> /app/core_service.py" in dockerfile
    assert 'os.execv("/usr/local/bin/plai-core"' in dockerfile


def test_core_reconciles_interrupted_rag_index_state_on_startup():
    main = (ROOT / "rust/core/src/main.rs").read_text(encoding="utf-8")
    rag = (ROOT / "rust/core/src/rag.rs").read_text(encoding="utf-8")

    assert "rag::reconcile_startup_state()" in main
    assert "pub fn reconcile_startup_state()" in rag
    assert 'const RAG_BUILD_DB_FILE: &str = "/data/rag/rag.db.build";' in rag
    assert 'atomic_write(Path::new(RAG_PAUSE_FILE), b"paused\\n")?' in rag
    assert "keeping it paused for explicit Resume" in rag
