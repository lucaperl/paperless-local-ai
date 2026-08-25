#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

files = {}
source_paths = list((ROOT / "src").rglob("*.py"))
source_paths.extend((ROOT / "rust" / "core" / "src").rglob("*.rs"))
source_paths.append(ROOT / "rust" / "core" / "build.rs")
for path in sorted(source_paths):
    # Keep release manifests identical across Windows and Linux checkouts.
    with path.open("r", encoding="utf-8", newline=None) as handle:
        data = handle.read().encode("utf-8")
    files[path.relative_to(ROOT).as_posix()] = hashlib.sha256(data).hexdigest()

manifest = {
    "version": VERSION,
    "created": date.today().isoformat(),
    "source_files": files,
}

(ROOT / "SOURCE-MANIFEST.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(f"Wrote SOURCE-MANIFEST.json for {VERSION} ({len(files)} runtime files)")
