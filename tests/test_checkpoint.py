"""Git Time Machine checkpoint create/restore."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_jail.core.checkpoint import (
    create_checkpoint,
    git_available,
    restore_checkpoint,
)


@unittest.skipUnless(git_available(), "git not installed")
class CheckpointTests(unittest.TestCase):
    def test_create_and_restore_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "config.json"
            target.write_text('{"ok": true}\n', encoding="utf-8")

            sha = create_checkpoint(root, "job-1")
            self.assertIsNotNone(sha)
            assert sha is not None

            target.write_text('{"ok": false, "wrecked": true}\n', encoding="utf-8")
            self.assertIn("wrecked", target.read_text(encoding="utf-8"))

            restore_checkpoint(root, sha)
            self.assertEqual(target.read_text(encoding="utf-8"), '{"ok": true}\n')

    def test_checkpoint_captures_new_file_deletion_on_restore(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "keep.txt").write_text("keep\n", encoding="utf-8")
            sha = create_checkpoint(root, "job-2")
            assert sha is not None

            (root / "keep.txt").write_text("changed\n", encoding="utf-8")
            (root / "extra.txt").write_text("extra\n", encoding="utf-8")
            restore_checkpoint(root, sha)
            self.assertEqual((root / "keep.txt").read_text(encoding="utf-8"), "keep\n")


if __name__ == "__main__":
    unittest.main()
