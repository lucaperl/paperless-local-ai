from __future__ import annotations

import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


CONFIG_FILE = Path(os.getenv("APP_CONFIG_FILE", "/config/app-config.json"))
HISTORY_DIR = Path(os.getenv("APP_CONFIG_HISTORY_DIR", "/config/app-history"))
LOCK_FILE = Path(os.getenv("APP_CONFIG_LOCK_FILE", "/config/app-config.lock"))

OCR_MODEL_PROFILES = ("medium", "small", "tiny")
OCR_MAX_SIDE_PIXELS_DEFAULT = 3000
OCR_MAX_SIDE_PIXELS_MIN = 2000
OCR_MAX_SIDE_PIXELS_MAX = 4000
OCR_RETRY_DELAYS_DEFAULT = (15, 60, 300, 600)
OCR_RETRY_DELAYS_MAX_COUNT = 10
OCR_RETRY_DELAY_MAX_SECONDS = 86400


DEFAULT_CONFIG = {
    "version": 1,
    "updated_at": None,
    "connections": {
        "paperless_url": "http://paperless:8000",
        "ollama_url": "http://ollama:11434",
    },
    "workflow": {
        "llm_queue_tag": "LLM",
        "llm_error_tag": "LLM Error",
        "review_tag": "Inbox",
        "extra_excluded_tags": ["TODO"],
    },
    "ocr": {
        "language": "en",
        "version": "PP-OCRv6",
        "model_profile": "medium",
        "max_side_pixels": OCR_MAX_SIDE_PIXELS_DEFAULT,
        "retry_delays_seconds": list(OCR_RETRY_DELAYS_DEFAULT),
        "device": "cpu",
    },
    "runtime": {
        "poll_interval_seconds": 10,
        "review_prune_interval_seconds": 3600,
        "dry_run": False,
    },
    "paperless_ui": {
        "enabled": False,
        "control_center_url": "",
    },
}


class ConfigError(ValueError):
    pass


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _deepcopy_default():
    return json.loads(json.dumps(DEFAULT_CONFIG, ensure_ascii=False))


def _canonical_json(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def config_hash(config):
    return hashlib.sha256(_canonical_json(config).encode("utf-8")).hexdigest()


def _require_nonempty_string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{name} must be a non-empty string")
    return value.strip()


def _validate_url(value, name):
    value = _require_nonempty_string(value, name).rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError(f"{name} must be a complete http(s) URL")
    return value


def _positive_int(value, name, minimum=1, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{name} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        hi = f" and <= {maximum}" if maximum is not None else ""
        raise ConfigError(f"{name} must be >= {minimum}{hi}")
    return value


def _retry_delays(value):
    if not isinstance(value, list):
        raise ConfigError("ocr.retry_delays_seconds must be a list of integer seconds")
    if len(value) > OCR_RETRY_DELAYS_MAX_COUNT:
        raise ConfigError(
            f"ocr.retry_delays_seconds may contain at most {OCR_RETRY_DELAYS_MAX_COUNT} values"
        )
    return [
        _positive_int(
            delay,
            f"ocr.retry_delays_seconds[{index}]",
            1,
            OCR_RETRY_DELAY_MAX_SECONDS,
        )
        for index, delay in enumerate(value)
    ]


def validate_config(raw):
    if not isinstance(raw, dict):
        raise ConfigError("App configuration must be a JSON object")

    cfg = _deepcopy_default()

    # Only copy fields that belong to the current schema. This intentionally
    # drops removed pre-0.2 OCR queue/error keys instead of carrying dead
    # configuration forward.
    for section in ("connections", "workflow", "ocr", "runtime", "paperless_ui"):
        incoming = raw.get(section, {})
        if not isinstance(incoming, dict):
            raise ConfigError(f"{section} must be an object")
        for key in cfg[section]:
            if key in incoming:
                cfg[section][key] = incoming[key]

    cfg["version"] = raw.get("version", 1)
    cfg["updated_at"] = raw.get("updated_at")

    cfg["version"] = _positive_int(cfg["version"], "version")
    if cfg["updated_at"] is not None and not isinstance(cfg["updated_at"], str):
        raise ConfigError("updated_at must be a string or null")

    conn = cfg["connections"]
    conn["paperless_url"] = _validate_url(
        conn["paperless_url"], "connections.paperless_url"
    )
    conn["ollama_url"] = _validate_url(
        conn["ollama_url"], "connections.ollama_url"
    )

    workflow = cfg["workflow"]
    for key in ("llm_queue_tag", "llm_error_tag", "review_tag"):
        workflow[key] = _require_nonempty_string(
            workflow[key], f"workflow.{key}"
        )

    technical = [
        workflow["llm_queue_tag"],
        workflow["llm_error_tag"],
        workflow["review_tag"],
    ]
    if len({x.casefold() for x in technical}) != len(technical):
        raise ConfigError("Technical workflow tags must have distinct names")

    extra = workflow.get("extra_excluded_tags", [])
    if not isinstance(extra, list) or any(
        not isinstance(x, str) or not x.strip() for x in extra
    ):
        raise ConfigError(
            "workflow.extra_excluded_tags must be a list of non-empty strings"
        )

    dedup = []
    seen = set()
    for item in extra:
        item = item.strip()
        key = item.casefold()
        if key not in seen:
            dedup.append(item)
            seen.add(key)
    workflow["extra_excluded_tags"] = dedup

    ocr = cfg["ocr"]
    for key in ("language", "version", "model_profile", "device"):
        ocr[key] = _require_nonempty_string(ocr[key], f"ocr.{key}")

    ocr["max_side_pixels"] = _positive_int(
        ocr["max_side_pixels"],
        "ocr.max_side_pixels",
        OCR_MAX_SIDE_PIXELS_MIN,
        OCR_MAX_SIDE_PIXELS_MAX,
    )
    ocr["retry_delays_seconds"] = _retry_delays(ocr["retry_delays_seconds"])

    ocr["model_profile"] = ocr["model_profile"].lower()
    if ocr["model_profile"] not in OCR_MODEL_PROFILES:
        raise ConfigError(
            "ocr.model_profile must be one of: " + ", ".join(OCR_MODEL_PROFILES)
        )

    if (
        ocr["version"] == "PP-OCRv6"
        and ocr["model_profile"] == "tiny"
        and ocr["language"].casefold() in {"japan", "ja", "japanese"}
    ):
        raise ConfigError("PP-OCRv6 Tiny does not support Japanese")

    runtime = cfg["runtime"]
    runtime["poll_interval_seconds"] = _positive_int(
        runtime["poll_interval_seconds"],
        "runtime.poll_interval_seconds",
        5,
        3600,
    )
    runtime["review_prune_interval_seconds"] = _positive_int(
        runtime["review_prune_interval_seconds"],
        "runtime.review_prune_interval_seconds",
        60,
        86400,
    )
    if not isinstance(runtime["dry_run"], bool):
        raise ConfigError("runtime.dry_run must be true or false")

    paperless_ui = cfg["paperless_ui"]
    if not isinstance(paperless_ui["enabled"], bool):
        raise ConfigError("paperless_ui.enabled must be true or false")
    url = paperless_ui.get("control_center_url", "")
    if not isinstance(url, str):
        raise ConfigError("paperless_ui.control_center_url must be a string")
    url = url.strip()
    if url:
        url = _validate_url(url, "paperless_ui.control_center_url")
    if paperless_ui["enabled"] and not url:
        raise ConfigError("paperless_ui.control_center_url is required when enabled")
    paperless_ui["control_center_url"] = url

    return cfg


def _atomic_write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


@contextmanager
def config_lock():
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def ensure_config():
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        return load_config()
    cfg = _deepcopy_default()
    cfg["updated_at"] = utc_now_iso()
    _atomic_write_json(CONFIG_FILE, cfg)
    return cfg


def load_config():
    if not CONFIG_FILE.exists():
        return validate_config(_deepcopy_default())
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ConfigError(f"app-config.json is not readable: {exc}") from exc
    return validate_config(raw)


def _history_filename(config):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return HISTORY_DIR / f"app-config-v{config['version']:04d}-{stamp}.json"


def save_config(raw, source="ui"):
    with config_lock():
        current = load_config()
        candidate = validate_config(raw)
        candidate["version"] = current["version"] + 1
        candidate["updated_at"] = utc_now_iso()
        candidate = validate_config(candidate)

        history = json.loads(json.dumps(current, ensure_ascii=False))
        history["history_saved_at"] = utc_now_iso()
        history["history_source"] = source
        _atomic_write_json(_history_filename(current), history)
        _atomic_write_json(CONFIG_FILE, candidate)
        return candidate


def list_history():
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for path in sorted(HISTORY_DIR.glob("app-config-v*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            runtime = data.get("runtime", {}) if isinstance(data.get("runtime"), dict) else {}
            ocr = data.get("ocr", {}) if isinstance(data.get("ocr"), dict) else {}
            profile = str(ocr.get("model_profile", "medium")).title()
            items.append(
                {
                    "file": path.name,
                    "version": data.get("version"),
                    "updated_at": data.get("updated_at"),
                    "history_saved_at": data.get("history_saved_at"),
                    "history_source": data.get("history_source"),
                    "config_sha256": config_hash(data),
                    "summary": (
                        ("Metadata dry run" if runtime.get("dry_run") else "Metadata writes enabled")
                        + f" · {ocr.get('version', 'PP-OCRv6')} {profile}"
                        + f" · {ocr.get('max_side_pixels', OCR_MAX_SIDE_PIXELS_DEFAULT)} px"
                    ),
                }
            )
        except Exception:
            items.append({"file": path.name, "error": "not readable"})
    return items


def restore_history(filename):
    if Path(filename).name != filename or not filename.startswith("app-config-v"):
        raise ConfigError("Invalid history filename")
    path = HISTORY_DIR / filename
    if not path.exists():
        raise ConfigError("History version not found")
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw = {
        k: v
        for k, v in raw.items()
        if k in DEFAULT_CONFIG or k in {"version", "updated_at"}
    }
    return save_config(raw, source=f"restore:{filename}")


def technical_tag_names(config=None):
    cfg = config or load_config()
    w = cfg["workflow"]
    return {
        w["llm_queue_tag"],
        w["llm_error_tag"],
        w["review_tag"],
        *w["extra_excluded_tags"],
    }
