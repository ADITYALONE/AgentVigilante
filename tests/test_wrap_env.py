"""Tests for agentvigilante wrap env composition."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_vigilante.shim import install_shims
from agent_vigilante.wrap import build_wrap_env, prepare_wrap, resolve_wrap_target


class WrapEnvTests(unittest.TestCase):
    def test_path_and_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = Path(tmp) / "bin"
            fake.mkdir()
            for name in ("bash", "zsh"):
                p = fake / name
                p.write_text("#!/bin/sh\n", encoding="utf-8")
                p.chmod(0o755)
            with mock.patch.dict(os.environ, {"PATH": str(fake)}, clear=False):
                install_shims(root)
                env = build_wrap_env(
                    url="http://127.0.0.1:8420",
                    base_env={"PATH": "/usr/bin", "AGENTVIGILANTE_BYPASS": "1", "HOME": tmp},
                    root=root,
                )
            self.assertTrue(env["PATH"].startswith(str(root / "shims")))
            self.assertEqual(env["AGENTVIGILANTE_ACTIVE"], "1")
            self.assertEqual(env["AGENTVIGILANTE_URL"], "http://127.0.0.1:8420")
            self.assertNotIn("AGENTVIGILANTE_BYPASS", env)
            self.assertTrue(env["SHELL"].endswith("/zsh") or env["SHELL"].endswith("/bash"))

    def test_prepare_wrap_installs_and_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "aj"
            host = Path(tmp) / "host"
            host.mkdir()
            tool = host / "mytool"
            tool.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
            tool.chmod(0o755)
            with mock.patch.dict(os.environ, {"PATH": str(host)}, clear=False):
                target, env = prepare_wrap(
                    ["mytool", "--flag"],
                    url="http://example:8420",
                    root=root,
                    install=True,
                )
            self.assertEqual(target[0], str(tool))
            self.assertEqual(target[1], "--flag")
            self.assertIn(str(root / "shims"), env["PATH"])

    def test_resolve_cursor_uses_macos_binary_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_cursor = Path(tmp) / "Cursor"
            fake_cursor.write_text("x", encoding="utf-8")
            fake_cursor.chmod(0o755)
            with mock.patch("agent_vigilante.wrap.platform.system", return_value="Darwin"):
                with mock.patch.dict(
                    "agent_vigilante.wrap._MAC_APP_BINARIES",
                    {"cursor": (str(fake_cursor),)},
                    clear=False,
                ):
                    resolved = resolve_wrap_target(["cursor", "."])
            self.assertEqual(resolved[0], str(fake_cursor))
            self.assertEqual(resolved[1], ".")


if __name__ == "__main__":
    unittest.main()
