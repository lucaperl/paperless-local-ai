from __future__ import annotations

import json
import os
import socket
import sys
from typing import Any

from memory_reclaim import (
    page_out_self_file_mappings,
    page_out_self_resident_file_cache,
)
from service import _JsonSocketConnection, _engine_process


def _write_stderr(message: str) -> None:
    try:
        os.write(2, (message.rstrip() + "\n").encode("utf-8", errors="replace"))
    except OSError:
        pass


def main() -> int:
    if len(sys.argv) != 3:
        raise RuntimeError("paddle_engine.py requires IPC fd and OCR config JSON")
    fd = int(sys.argv[1])
    config: Any = json.loads(sys.argv[2])
    if not isinstance(config, dict):
        raise ValueError("OCR engine config must be a JSON object")

    sock = socket.socket(fileno=fd)
    conn = _JsonSocketConnection(sock)
    try:
        _engine_process(conn, config)
    finally:
        conn.close()
    return 0


def _final_exit(code: int) -> None:
    try:
        stats = page_out_self_file_mappings()
        _write_stderr(
            "[PADDLE-ENGINE] final file-mapping reclaim: "
            f"accepted={stats['accepted_bytes'] / 1048576:.1f} MiB "
            f"attempted={stats['attempted_bytes'] / 1048576:.1f} MiB "
            f"failed_mappings={stats['failed_mappings']}"
        )
    except BaseException as exc:
        _write_stderr(
            "[PADDLE-ENGINE] final file-mapping reclaim skipped: "
            f"{type(exc).__name__}: {exc}"
        )

    try:
        cache_stats = page_out_self_resident_file_cache()
        _write_stderr(
            "[PADDLE-ENGINE] final resident file-cache reclaim: "
            f"accepted={cache_stats['accepted_bytes'] / 1048576:.1f} MiB "
            f"resident={cache_stats['resident_bytes'] / 1048576:.1f} MiB "
            f"files_scanned={cache_stats['files_scanned']} "
            f"failed_files={cache_stats['failed_files']}"
        )
    except BaseException as exc:
        _write_stderr(
            "[PADDLE-ENGINE] final resident file-cache reclaim skipped: "
            f"{type(exc).__name__}: {exc}"
        )

    # Logging and the cache sweep itself can fault a few runtime code pages
    # back in. One last mapping-only pass immediately before direct exit keeps
    # that tail small without changing worker semantics if reclaim is absent.
    try:
        page_out_self_file_mappings()
    except BaseException:
        pass

    os._exit(code)


if __name__ == "__main__":
    exit_code = 0
    try:
        exit_code = main()
    except BaseException as exc:
        _write_stderr(f"[PADDLE-ENGINE] fatal: {type(exc).__name__}: {exc}")
        exit_code = 1
    _final_exit(exit_code)
