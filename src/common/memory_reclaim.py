from __future__ import annotations

import ctypes
import os
import stat
import sys
from typing import Any


MADV_PAGEOUT = 21
PROT_READ = 0x1
MAP_PRIVATE = 0x02


def _file_backed_readonly_entries(maps_text: str) -> list[tuple[int, int, str]]:
    entries: list[tuple[int, int, str]] = []
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
            entries.append((start, end - start, path))
    return entries


def _file_backed_readonly_mappings(maps_text: str) -> list[tuple[int, int]]:
    return [
        (start, length)
        for start, length, _path in _file_backed_readonly_entries(maps_text)
    ]


def _file_backed_readonly_paths(maps_text: str) -> list[str]:
    return sorted(
        {
            path
            for _start, _length, path in _file_backed_readonly_entries(maps_text)
            if not path.endswith(" (deleted)")
        }
    )


def _linux_memory_api() -> tuple[Any, Any, Any, Any] | None:
    try:
        libc = ctypes.CDLL(None, use_errno=True)

        madvise = libc.madvise
        madvise.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
        madvise.restype = ctypes.c_int

        mmap_fn = libc.mmap
        mmap_fn.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_longlong,
        ]
        mmap_fn.restype = ctypes.c_void_p

        mincore = libc.mincore
        mincore.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_ubyte),
        ]
        mincore.restype = ctypes.c_int

        munmap = libc.munmap
        munmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        munmap.restype = ctypes.c_int
    except (AttributeError, OSError, TypeError, ValueError):
        return None

    return madvise, mmap_fn, mincore, munmap


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
        api = _linux_memory_api()
        if api is None:
            return stats
        madvise, _mmap_fn, _mincore, _munmap = api
    except (OSError, TypeError, ValueError):
        return stats

    stats["supported"] = True
    for start, length in mappings:
        stats["attempted_bytes"] += length
        try:
            result = madvise(
                ctypes.c_void_p(start),
                ctypes.c_size_t(length),
                MADV_PAGEOUT,
            )
        except (OSError, TypeError, ValueError):
            result = -1

        if result == 0:
            stats["accepted_bytes"] += length
        else:
            stats["failed_mappings"] += 1

    return stats


def page_out_self_resident_file_cache() -> dict[str, Any]:
    """Page out residual clean cache for files mapped by a disposable helper.

    Ordinary MADV_PAGEOUT can remove the helper's original PTEs while clean
    runtime-library pages remain charged to the helper's cgroup page cache.
    This second pass temporarily maps each unique regular file that appeared in
    a read-only mapping, checks residency with mincore(), touches only pages
    already reported resident to establish temporary PTEs, and applies
    MADV_PAGEOUT to that mapping.

    Non-resident pages are not intentionally faulted in. The helper is already
    on its final exit path, and every failure here is deliberately best-effort
    so cleanup cannot change OCR success/failure semantics.
    """
    stats: dict[str, Any] = {
        "supported": False,
        "files_scanned": 0,
        "resident_bytes": 0,
        "accepted_bytes": 0,
        "failed_files": 0,
    }
    if not sys.platform.startswith("linux"):
        return stats

    try:
        with open("/proc/self/maps", "r", encoding="utf-8") as handle:
            paths = _file_backed_readonly_paths(handle.read())

        api = _linux_memory_api()
        if api is None:
            return stats

        madvise, mmap_fn, mincore, munmap = api
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        map_failed = ctypes.c_void_p(-1).value
    except (OSError, TypeError, ValueError):
        return stats

    stats["supported"] = True
    open_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    seen_files: set[tuple[int, int]] = set()

    for path in paths:
        fd: int | None = None
        addr: int | None = None
        length = 0

        try:
            fd = os.open(path, open_flags)
            info = os.fstat(fd)

            if not stat.S_ISREG(info.st_mode) or info.st_size <= 0:
                continue

            file_identity = (int(info.st_dev), int(info.st_ino))
            if file_identity in seen_files:
                continue
            seen_files.add(file_identity)

            length = int(info.st_size)
            page_count = (length + page_size - 1) // page_size

            addr = mmap_fn(
                None,
                ctypes.c_size_t(length),
                PROT_READ,
                MAP_PRIVATE,
                fd,
                0,
            )
            if addr in (None, map_failed):
                raise OSError(ctypes.get_errno(), "mmap failed")

            vector = (ctypes.c_ubyte * page_count)()
            if mincore(
                ctypes.c_void_p(addr),
                ctypes.c_size_t(length),
                vector,
            ) != 0:
                raise OSError(ctypes.get_errno(), "mincore failed")

            resident_pages = [
                index
                for index, value in enumerate(vector)
                if value & 1
            ]
            stats["files_scanned"] += 1

            if not resident_pages:
                continue

            resident_bytes = sum(
                min(page_size, length - index * page_size)
                for index in resident_pages
            )
            stats["resident_bytes"] += resident_bytes

            # mincore() is only a residency snapshot. Touch pages that were
            # already reported resident so this temporary mapping has PTEs for
            # MADV_PAGEOUT without intentionally faulting cold pages in.
            for index in resident_pages:
                ctypes.c_ubyte.from_address(
                    int(addr) + index * page_size
                ).value

            result = madvise(
                ctypes.c_void_p(addr),
                ctypes.c_size_t(length),
                MADV_PAGEOUT,
            )
            if result == 0:
                stats["accepted_bytes"] += resident_bytes
            else:
                stats["failed_files"] += 1

        except (MemoryError, OSError, OverflowError, TypeError, ValueError):
            stats["failed_files"] += 1

        finally:
            if addr not in (None, map_failed) and length > 0:
                try:
                    munmap(
                        ctypes.c_void_p(addr),
                        ctypes.c_size_t(length),
                    )
                except (OSError, TypeError, ValueError):
                    pass

            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass

    return stats
