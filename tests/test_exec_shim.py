"""Tests for exec-shim argv reconstruction and interactive detection."""

from __future__ import annotations

import unittest
from unittest import mock

from agent_jail.exec_shim import (
    extract_shell_c_command,
    is_interactive_shell,
    reconstruct_command,
    run_via_daemon,
)


class ReconstructTests(unittest.TestCase):
    def test_bash_c_extracts_inner_command(self) -> None:
        self.assertEqual(
            reconstruct_command("bash", ["-c", "echo hi > f.txt"]),
            "echo hi > f.txt",
        )

    def test_bash_lc_extracts_inner_command(self) -> None:
        self.assertEqual(
            extract_shell_c_command(["-lc", "ls -la"]),
            "ls -la",
        )
        self.assertEqual(
            reconstruct_command("zsh", ["-lc", "pwd"]),
            "pwd",
        )

    def test_npm_joins_full_argv(self) -> None:
        cmd = reconstruct_command("npm", ["install", "lodash"])
        self.assertIn("npm", cmd)
        self.assertIn("install", cmd)
        self.assertIn("lodash", cmd)

    def test_shell_script_invocation(self) -> None:
        cmd = reconstruct_command("bash", ["script.sh", "a", "b"])
        self.assertTrue(cmd.startswith("bash"))
        self.assertIn("script.sh", cmd)

    def test_interactive_shell_detection(self) -> None:
        self.assertTrue(is_interactive_shell("bash", []))
        self.assertTrue(is_interactive_shell("zsh", ["-i"]))
        self.assertFalse(is_interactive_shell("bash", ["-c", "ls"]))
        self.assertFalse(is_interactive_shell("bash", ["run.sh"]))
        self.assertFalse(is_interactive_shell("npm", []))


class RunViaDaemonTests(unittest.TestCase):
    def test_connect_error_returns_tempfail(self) -> None:
        with mock.patch("agent_jail.exec_shim.httpx.Client") as client_cls:
            client = client_cls.return_value.__enter__.return_value
            import httpx

            client.post.side_effect = httpx.ConnectError("down")
            code = run_via_daemon("ls", url="http://127.0.0.1:1")
        self.assertEqual(code, 75)


if __name__ == "__main__":
    unittest.main()
