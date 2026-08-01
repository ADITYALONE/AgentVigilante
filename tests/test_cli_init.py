"""Tests for agentjail init MCP config patching."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_jail.cli import cmd_init, patch_json_config


class PatchJsonConfigTests(unittest.TestCase):
    def test_merges_without_clobbering_neighbors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mcp.json"
            path.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "other": {
                                "command": "npx",
                                "args": ["-y", "other-mcp"],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            ok, msg = patch_json_config(path)
            self.assertTrue(ok, msg)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("other", data["mcpServers"])
            self.assertIn("agentjail", data["mcpServers"])
            self.assertEqual(
                data["mcpServers"]["agentjail"]["args"],
                ["-m", "agent_jail.mcp_server"],
            )
            backups = list(Path(tmp).glob("mcp.json.bak.*"))
            self.assertEqual(len(backups), 1)

    def test_corrupt_json_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mcp.json"
            original = "{not-json"
            path.write_text(original, encoding="utf-8")
            ok, msg = patch_json_config(path)
            self.assertFalse(ok)
            self.assertIn("corrupt JSON", msg)
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_creates_new_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "mcp.json"
            ok, msg = patch_json_config(path)
            self.assertTrue(ok, msg)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("agentjail", data["mcpServers"])


class CmdInitTests(unittest.TestCase):
    def test_force_project_writes_cwd_cursor_mcp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            with mock.patch("agent_jail.cli.discover_config_paths", return_value={}):
                with mock.patch("agent_jail.cli.Path.cwd", return_value=cwd):
                    ns = mock.Mock(
                        url="http://127.0.0.1:8420",
                        project=False,
                        force_project=True,
                        force=False,
                    )
                    code = cmd_init(ns)
            self.assertEqual(code, 0)
            project_mcp = cwd / ".cursor" / "mcp.json"
            self.assertTrue(project_mcp.is_file())
            data = json.loads(project_mcp.read_text(encoding="utf-8"))
            self.assertIn("agentjail", data["mcpServers"])


if __name__ == "__main__":
    unittest.main()
