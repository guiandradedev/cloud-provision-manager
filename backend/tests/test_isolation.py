import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services import runtime


class IsolationRuntimeTests(unittest.TestCase):
    def test_network_namespace_must_differ_from_host(self) -> None:
        with patch.object(
            runtime.os,
            "stat",
            side_effect=[SimpleNamespace(st_ino=10), SimpleNamespace(st_ino=20)],
        ):
            self.assertTrue(runtime.has_isolated_network_namespace(1234))

    def test_io_limit_is_applied_to_read_and_write(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary_directory:
            cgroup_path = Path(temporary_directory)
            with (
                patch.object(
                    runtime.os,
                    "stat",
                    return_value=SimpleNamespace(st_dev=123),
                ),
                patch.object(runtime.os, "major", return_value=8, create=True),
                patch.object(runtime.os, "minor", return_value=1, create=True),
            ):
                runtime.configure_environment_cgroup(
                    cgroup_path,
                    cpu_quota=50,
                    cpu_weight=100,
                    mem_limit=512,
                    io_limit_bps=10_000_000,
                )

            self.assertEqual(
                (cgroup_path / "io.max").read_text(),
                "8:1 rbps=10000000 wbps=10000000\n",
            )

    def test_zero_io_limit_keeps_kernel_default(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary_directory:
            cgroup_path = Path(temporary_directory)
            runtime.configure_environment_cgroup(
                cgroup_path,
                cpu_quota=50,
                cpu_weight=100,
                mem_limit=512,
            )

            self.assertFalse((cgroup_path / "io.max").exists())


if __name__ == "__main__":
    unittest.main()
