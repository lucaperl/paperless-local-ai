from memory_reclaim import (
    _file_backed_readonly_mappings,
    _file_backed_readonly_paths,
)


MAPS = """\
1000-2000 r-xp 00000000 00:01 1 /usr/lib/libexample.so
2000-3000 r--p 00001000 00:01 1 /usr/lib/libexample.so
3000-4000 rw-p 00002000 00:01 1 /usr/lib/libexample.so
4000-5000 r--p 00000000 00:00 0 [vvar]
5000-6000 rw-p 00000000 00:00 0
6000-7000 r--p 00000000 00:01 2 /usr/lib/lib with spaces.so
7000-8000 r--p 00000000 00:01 3 /usr/lib/removed.so (deleted)
"""


def test_mapping_parser_targets_only_readonly_file_backed_ranges():
    assert _file_backed_readonly_mappings(MAPS) == [
        (0x1000, 0x1000),
        (0x2000, 0x1000),
        (0x6000, 0x1000),
        (0x7000, 0x1000),
    ]


def test_mapping_parser_returns_unique_live_paths_for_cache_sweep():
    assert _file_backed_readonly_paths(MAPS) == [
        "/usr/lib/lib with spaces.so",
        "/usr/lib/libexample.so",
    ]
