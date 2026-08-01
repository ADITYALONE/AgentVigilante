"""Tests for native notify choice plumbing (no real UI)."""

from __future__ import annotations

import unittest
from unittest import mock

from agent_jail.notify import prompt_risky_choice


class NotifyPromptTests(unittest.TestCase):
    def test_macos_approve(self) -> None:
        with mock.patch("agent_jail.notify.platform.system", return_value="Darwin"):
            with mock.patch("agent_jail.notify.subprocess.run") as run:
                run.return_value = mock.Mock(
                    returncode=0, stdout="button returned:Approve\n", stderr=""
                )
                choice = prompt_risky_choice(
                    command="echo x > f",
                    risk_reason="I/O redirection",
                    job_id="abcd1234-ffff",
                    console_url="http://127.0.0.1:8420/console",
                )
        self.assertEqual(choice, "approve")
        self.assertEqual(run.call_args.args[0][0], "osascript")

    def test_linux_without_tools_dismisses(self) -> None:
        with mock.patch("agent_jail.notify.platform.system", return_value="Linux"):
            with mock.patch("agent_jail.notify.shutil.which", return_value=None):
                choice = prompt_risky_choice(
                    command="npm install x",
                    risk_reason=None,
                    job_id="id",
                    console_url="http://127.0.0.1:8420/console",
                )
        self.assertEqual(choice, "dismiss")


if __name__ == "__main__":
    unittest.main()
