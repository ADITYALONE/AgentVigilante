"""Tests for shell rc injection."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_vigilante.shell_integration import (
    BEGIN_MARK,
    disable_shell_integration,
    enable_shell_integration,
    inject_agentvigilante_block,
    strip_agentvigilante_block,
)


class ShellIntegrationTests(unittest.TestCase):
    def test_inject_idempotent(self) -> None:
        text = "export FOO=1\n"
        once = inject_agentvigilante_block(
            text, url="http://127.0.0.1:8420", shim_dir="/tmp/shims"
        )
        twice = inject_agentvigilante_block(
            once, url="http://127.0.0.1:8420", shim_dir="/tmp/shims"
        )
        self.assertEqual(once.count(BEGIN_MARK), 1)
        self.assertEqual(twice.count(BEGIN_MARK), 1)
        self.assertIn("AGENTVIGILANTE_ACTIVE=1", twice)

    def test_strip(self) -> None:
        text = inject_agentvigilante_block(
            "hi\n", url="http://x", shim_dir="/s"
        )
        cleaned = strip_agentvigilante_block(text)
        self.assertNotIn(BEGIN_MARK, cleaned)
        self.assertIn("hi", cleaned)

    def test_enable_disable_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            zsh = root / ".zshrc"
            zsh.write_text("# existing\n", encoding="utf-8")
            written = enable_shell_integration(
                url="http://127.0.0.1:8420",
                shim_dir=root / "shims",
                rc_paths=[zsh, root / ".bashrc"],
            )
            self.assertEqual(len(written), 2)
            self.assertIn("agentvigilante", zsh.read_text(encoding="utf-8"))
            modified = disable_shell_integration(rc_paths=[zsh, root / ".bashrc"])
            self.assertIn(zsh, modified)
            self.assertNotIn(BEGIN_MARK, zsh.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
