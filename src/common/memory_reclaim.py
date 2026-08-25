from __future__ import annotations

import ctypes
import sys
from typing import Any


MADV_PAGEOUT = 21


def _file_backed_readonly_mappings(maps_text: str) -> list[tuple[int, int]]:
    mappings: list[tuple[int, int]] = []
    for line in maps_text.splitlines():
        parts = line.split(maxsplit=5)
        if len(parts) < 6:
            continue
        address_range, permissions, _offset, _device, _inode, path = parts
        if not path.startswith("/"):
            continue
        if not permissions.startswith("r") or "w" in permissions:
            continue
        try:
            start_text, end_text = address_range.split("-", 1)
            start = int(start_text, 16)
            end = int(end_text, 16)
        except ValueError:
            continue
        if end > start:
            mappings.append((start, end - start))
    return mappings


def page_out_self_file_mappings() -> dict[str, Any]:
    """Best-effort Linux reclaim for disposable helper process file mappings.

    Only read-only file-backed mappings are targeted. Failure is deliberately
    non-fatal because process teardown must never change OCR/History semantics.
    """
    stats: dict[str, Any] = {
        "supported": False,
        "attempted_bytes": 0,
        "accepted_bytes": 0,
        "failed_mappings": 0,
    }
    if not sys.platform.startswith("linux"):
        return stats

    try:
        with open("/proc/self/maps", "r", encoding="utf-8") as handle:
            mappings = _file_backed_readonly_mappings(handle.read())
        libc = ctypes.CDLL(None, use_errno=True)
        madvise = libc.madvise
        madvise.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
        madvise.restype = ctypes.c_int
    except (OSError, AttributeError, TypeError, ValueError):
        return stats

    stats["supported"] = True
    for start, length in mappings:
        stats["attempted_bytes"] += length
        try:
            result = madvise(ctypes.c_void_p(start), ctypes.c_size_t(length), MADV_PAGEOUT)
        except (OSError, TypeError, ValueError):
            result = -1
        if result == 0:
            stats["accepted_bytes"] += length
        else:
            stats["failed_mappings"] += 1
    return stats
