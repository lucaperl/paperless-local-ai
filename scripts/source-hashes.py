#!/usr/bin/env python3
from hashlib import sha256
from pathlib import Path

root = Path(__file__).resolve().parents[1]
for path in sorted((root / "src").rglob("*.py")):
    print(sha256(path.read_bytes()).hexdigest(), path.relative_to(root))
