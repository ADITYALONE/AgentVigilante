"""Tests for ~/.agentjail/config.json helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_jail.config import (
    apply_invisible_defaults,
    apply_interactive_defaults,
    load_config,
    save_config,
)


class ConfigTests(unittest.TestCase):
    def test_roundtrip_invisible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = apply_invisible_defaults(load_config(root))
            cfg.url = "http://127.0.0.1:9999"
            save_config(cfg, root)
            loaded = load_config(root)
            self.assertEqual(loaded.mode, "invisible")
            self.assertTrue(loaded.autopilot)
            self.assertTrue(loaded.shell_integration)
            self.assertEqual(loaded.url, "http://127.0.0.1:9999")

    def test_interactive_defaults(self) -> None:
        cfg = apply_interactive_defaults(apply_invisible_defaults(load_config()))
        self.assertEqual(cfg.mode, "interactive")
        self.assertFalse(cfg.autopilot)


if __name__ == "__main__":
    unittest.main()
