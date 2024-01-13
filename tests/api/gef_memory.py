"""
`gef.session` test module.
"""

import pathlib
import random
import pytest

from tests.base import RemoteGefUnitTestGeneric

from tests.utils import (
    debug_target,
    gdbserver_session,
    qemuuser_session,
    GDBSERVER_DEFAULT_HOST,
)


class GefMemoryApi(RemoteGefUnitTestGeneric):
    """`gef.memory` test module."""

    def setUp(self) -> None:
        self._target = debug_target("default")
        return super().setUp()

    def test_api_gef_memory_only_running(self):
        gdb, gef = self._gdb, self._gef

        with pytest.raises(RuntimeError):
            assert gef.memory.maps is None

        gdb.execute("start")
        assert gef.memory.maps is not None

    def test_api_gef_memory_parse_info_proc_maps_expected_format(self):
        gdb, root = self._gdb, self._conn.root
        gdb.execute("start")

        #
        # The function assumes the following output format (as of GDB 8.3+) for `info proc mappings`
        # """"
        # process 61789
        # Mapped address spaces:
        #
        #           Start Addr           End Addr       Size     Offset  Perms  objfile
        #       0x555555554000     0x555555558000     0x4000        0x0  r--p   /usr/bin/ls
        #       0x555555558000     0x55555556c000    0x14000     0x4000  r-xp   /usr/bin/ls
        # [...]
        # """
        #

        # Check output format
        lines = (gdb.execute("info proc mappings", to_string=True) or "").splitlines()
        assert len(lines) >= 5
        assert all(map(lambda x: isinstance(x, str), lines))
        for line in lines[4:]:
            parts = [x.strip() for x in line.split()]
            start_addr = int(parts[0], 16)
            end_addr = int(parts[1], 16)
            size = int(parts[2], 16)
            int(parts[3], 16)
            assert end_addr == start_addr + size
            assert len(parts[4]) == 4
            Permission = root.eval("Permission")
            Permission.from_process_maps(parts[4])

            # optional objfile
            if len(parts) == 5:
                continue

            objfile = " ".join(parts[5:]).strip()
            if objfile.startswith("/"):
                assert pathlib.Path(objfile).exists()

    def test_api_gef_memory_parse_info_proc_maps(self):
        gdb, gef, root = self._gdb, self._gef, self._conn.root
        gdb.execute("start")

        Section = root.eval("Section")

        for section in gef.memory.parse_gdb_info_proc_maps():
            assert isinstance(section, Section)

    def test_func_parse_permissions(self):
        root = self._conn.root
        expected_values = [
            (
                "Permission.from_info_sections('ALLOC LOAD READONLY CODE HAS_CONTENTS')",
                "r-x",
            ),
            ("Permission.from_process_maps('r--')", "r--"),
            ("Permission.from_monitor_info_mem('-r-')", "r--"),
            ("Permission.from_info_mem('rw')", "rw-"),
        ]
        for cmd, expected in expected_values:
            assert str(root.eval(cmd)) == expected

    def test_func_parse_maps_local_procfs(self):
        root, gdb, gef = self._conn.root, self._gdb, self._gef

        with pytest.raises(FileNotFoundError):
            root.eval("list(GefMemoryManager.parse_procfs_maps())")

        gdb.execute("start")

        sections = root.eval("list(GefMemoryManager.parse_procfs_maps())")
        for section in sections:
            assert section.page_start & ~0xFFF
            assert section.page_end & ~0xFFF

            #
            # The parse maps function should automatically get called when we start
            # up, and we should be able to view the maps via the `gef.memory.maps`
            # property. So check the alias `gef.memory.maps`
            # However, since `gef.memory.maps` has more info, use it as source of
            # trust
            #
            assert section in gef.memory.maps

    @pytest.mark.slow
    def test_func_parse_maps_remote_gdbserver(self):
        gef, gdb = self._gef, self._gdb
        # When in a gef-remote session `parse_gdb_info_proc_maps` should work to
        # query the memory maps
        while True:
            port = random.randint(1025, 65535)
            if port != self._port:
                break

        with pytest.raises(Exception):
            gdb.execute(f"gef-remote {GDBSERVER_DEFAULT_HOST} {port}")

        with gdbserver_session(port=port) as _:
            gdb.execute(f"gef-remote {GDBSERVER_DEFAULT_HOST} {port}")
            sections = gef.memory.maps
            assert len(sections) > 0

    def test_func_parse_maps_remote_qemu(self):
        gdb, gef = self._gdb, self._gef
        # When in a gef-remote qemu-user session `parse_gdb_info_proc_maps`
        # should work to query the memory maps
        while True:
            port = random.randint(1025, 65535)
            if port != self._port:
                break

        with qemuuser_session(port=port) as _:
            cmd = f"gef-remote --qemu-user --qemu-binary {self._target} {GDBSERVER_DEFAULT_HOST} {port}"
            gdb.execute(cmd)
            sections = gef.memory.maps
            assert len(sections) > 0
