"""Holographic COW workspace isolation tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_jail.core.hologram import (
    create_shadow,
    destroy_shadow,
    promote_shadow,
)


class HologramTests(unittest.TestCase):
    def test_shadow_write_does_not_mutate_origin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origin = Path(tmp)
            target = origin / "config.json"
            target.write_text('{"ok": true}\n', encoding="utf-8")

            shadow = create_shadow(origin, "job-h1")
            shadowed = shadow / "config.json"
            self.assertTrue(shadowed.is_file())
            shadowed.write_text('{"ok": false}\n', encoding="utf-8")

            self.assertEqual(target.read_text(encoding="utf-8"), '{"ok": true}\n')
            self.assertEqual(shadowed.read_text(encoding="utf-8"), '{"ok": false}\n')
            destroy_shadow(shadow)

    def test_promote_copies_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origin = Path(tmp)
            (origin / "a.txt").write_text("a\n", encoding="utf-8")
            shadow = create_shadow(origin, "job-h2")
            (shadow / "a.txt").write_text("A\n", encoding="utf-8")
            (shadow / "b.txt").write_text("b\n", encoding="utf-8")

            promoted = promote_shadow(
                origin,
                shadow,
                added=["b.txt"],
                modified=["a.txt"],
                deleted=[],
            )
            self.assertIn("a.txt", promoted)
            self.assertIn("b.txt", promoted)
            self.assertEqual((origin / "a.txt").read_text(encoding="utf-8"), "A\n")
            self.assertEqual((origin / "b.txt").read_text(encoding="utf-8"), "b\n")
            destroy_shadow(shadow)
            self.assertFalse(shadow.exists())


if __name__ == "__main__":
    unittest.main()
