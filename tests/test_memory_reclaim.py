from memory_reclaim import _file_backed_readonly_mappings


def test_mapping_parser_targets_only_readonly_file_backed_ranges():
    maps = """\
1000-2000 r-xp 00000000 00:01 1 /usr/lib/libexample.so
2000-3000 r--p 00001000 00:01 1 /usr/lib/libexample.so
3000-4000 rw-p 00002000 00:01 1 /usr/lib/libexample.so
4000-5000 r--p 00000000 00:00 0 [vvar]
5000-6000 rw-p 00000000 00:00 0
"""
    assert _file_backed_readonly_mappings(maps) == [
        (0x1000, 0x1000),
        (0x2000, 0x1000),
    ]
