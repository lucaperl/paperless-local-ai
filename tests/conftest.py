import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "src" / "common"
CORE = ROOT / "src" / "core"
for path in (COMMON, CORE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ.setdefault("PAPERLESS_TOKEN", "test-token")
os.environ.setdefault("APP_CONFIG_FILE", "/tmp/paperless-local-ai-tests-app-config.json")
os.environ.setdefault("APP_CONFIG_HISTORY_DIR", "/tmp/paperless-local-ai-tests-app-history")
os.environ.setdefault("APP_CONFIG_LOCK_FILE", "/tmp/paperless-local-ai-tests-app-config.lock")
