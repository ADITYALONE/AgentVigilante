"""Tests for PATH shim installation."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_vigilante.shim import install_shims, resolve_real_bin, shim_dir


class ShimInstallTests(unittest.TestCase):
    def test_install_writes_executable_shims_and_skips_shim_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "home"
            fake_bin = Path(tmp) / "hostbin"
            fake_bin.mkdir()
            bash = fake_bin / "bash"
            bash.write_text("#!/bin/sh\necho real\n", encoding="utf-8")
            bash.chmod(0o755)

            # Pre-create a decoy "bash" inside what will be the shim dir path
            shims = root / "shims"
            shims.mkdir(parents=True)
            decoy = shims / "bash"
            decoy.write_text("#!/bin/sh\necho decoy\n", encoding="utf-8")
            decoy.chmod(0o755)

            env = {"PATH": f"{shims}{os.pathsep}{fake_bin}"}
            with mock.patch.dict(os.environ, env, clear=False):
                meta = install_shims(root)

            self.assertIn("bash", meta["written"])
            self.assertEqual(Path(meta["bins"]["bash"]).resolve(), bash.resolve())

            script = (shim_dir(root) / "bash").read_text(encoding="utf-8")
            self.assertIn("exec-shim", script)
            self.assertIn("AGENTVIGILANTE_BYPASS", script)
            mode = (shim_dir(root) / "bash").stat().st_mode
            self.assertTrue(mode & stat.S_IXUSR)

            data = json.loads((root / "real_bins.json").read_text(encoding="utf-8"))
            self.assertEqual(data["bins"]["bash"], str(bash.resolve()))

    def test_resolve_real_bin_skips_shim_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shim = Path(tmp) / "shims"
            real = Path(tmp) / "bin"
            shim.mkdir()
            real.mkdir()
            (shim / "zsh").write_text("shim", encoding="utf-8")
            (shim / "zsh").chmod(0o755)
            zsh = real / "zsh"
            zsh.write_text("real", encoding="utf-8")
            zsh.chmod(0o755)
            with mock.patch.dict(
                os.environ, {"PATH": f"{shim}{os.pathsep}{real}"}, clear=False
            ):
                found = resolve_real_bin("zsh", skip_dir=shim)
            self.assertEqual(found, zsh.resolve())


if __name__ == "__main__":
    unittest.main()
