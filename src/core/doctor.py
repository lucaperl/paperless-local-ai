#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path

import requests

from app_config import load_config as load_app_config

PAPERLESS_TOKEN = os.environ.get("PAPERLESS_TOKEN", "")
CONFIG_FILE = Path("/config/prompt-config.json")
CORR_CONFIG_FILE = Path("/config/correspondent-suggestion.json")


def ok(msg):
    print(f"PASS  {msg}")


def warn(msg):
    print(f"WARN  {msg}")


def fail(msg):
    print(f"FAIL  {msg}")
    return False


def configured_models():
    out = set()
    for path in (CONFIG_FILE, CORR_CONFIG_FILE):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except Exception as exc:
            warn(f"Config {path} nicht lesbar: {exc}")
            continue
        model = str(data.get("model", "")).strip()
        if model:
            out.add(model)
    if not out:
        out.add("qwen3.5:4b")
    return sorted(out)


def main():
    good = True
    print("paperless-local-ai doctor")
    print("=========================")

    try:
        app = load_app_config()
    except Exception as exc:
        fail(f"App-Konfiguration nicht lesbar: {exc}")
        return 1

    paperless_url = app["connections"]["paperless_url"]
    ollama_url = app["connections"]["ollama_url"]
    workflow = app["workflow"]

    if not PAPERLESS_TOKEN:
        fail("PAPERLESS_TOKEN fehlt in der Deployment-Umgebung")
        return 1

    def paperless_get(path):
        r = requests.get(
            paperless_url + path,
            headers={
                "Authorization": f"Token {PAPERLESS_TOKEN}",
                "Accept": "application/json",
            },
            timeout=20,
        )
        r.raise_for_status()
        return r.json()

    try:
        data = paperless_get("/api/tags/?page_size=1000")
        tags = data.get("results", data) if isinstance(data, dict) else data
        ok(f"Paperless erreichbar: {paperless_url}")
    except Exception as exc:
        fail(f"Paperless nicht erreichbar oder Token ungültig: {exc}")
        return 1

    tag_names = {str(x.get("name", "")) for x in tags}
    required = [
        workflow["ocr_queue_tag"],
        workflow["ocr_error_tag"],
        workflow["llm_queue_tag"],
        workflow["llm_error_tag"],
        workflow["review_tag"],
    ]
    missing = [x for x in required if x not in tag_names]
    if missing:
        good &= fail("Fehlende Paperless-Tags: " + ", ".join(missing))
    else:
        ok("Alle benötigten Queue-/Review-Tags vorhanden")

    try:
        r = requests.get(f"{ollama_url}/api/tags", timeout=20)
        r.raise_for_status()
        payload = r.json()
        installed = {
            str(item.get("name", ""))
            for item in payload.get("models", [])
            if isinstance(item, dict)
        }
        ok(f"Ollama erreichbar: {ollama_url}")
    except Exception as exc:
        fail(f"Ollama nicht erreichbar: {exc}")
        return 1

    wanted = configured_models()
    missing_models = [
        model for model in wanted
        if model not in installed
        and not any(name.startswith(model + ":") for name in installed)
    ]
    if missing_models:
        good &= fail("Fehlende Ollama-Modelle: " + ", ".join(missing_models))
    else:
        ok("Alle aktuell konfigurierten Ollama-Modelle vorhanden: " + ", ".join(wanted))

    if good:
        print("\nREADY: Grundvoraussetzungen sind erfüllt.")
        return 0

    print("\nNOT READY: Siehe FAIL-Zeilen oben.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
