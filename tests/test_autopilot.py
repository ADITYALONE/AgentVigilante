"""Tests for autopilot allowlist."""

from __future__ import annotations

import unittest

from agent_jail.core.autopilot import autopilot_allows, touches_sensitive
from agent_jail.core.command_analyzer import RiskLevel


class AutopilotTests(unittest.TestCase):
    def test_npm_install_allowed(self) -> None:
        self.assertTrue(
            autopilot_allows(
                "npm install lodash",
                RiskLevel.RISKY,
                "Matched risky base command: 'npm'",
            )
        )

    def test_npm_global_denied(self) -> None:
        self.assertFalse(
            autopilot_allows(
                "npm install -g evil",
                RiskLevel.RISKY,
                "Matched risky base command: 'npm'",
            )
        )

    def test_env_write_denied(self) -> None:
        self.assertTrue(touches_sensitive("echo x > .env"))
        self.assertFalse(
            autopilot_allows(
                "echo secret > .env",
                RiskLevel.RISKY,
                "I/O redirection detected",
            )
        )

    def test_safe_not_applicable(self) -> None:
        self.assertFalse(autopilot_allows("ls", RiskLevel.SAFE, "ok"))

    def test_git_push_denied(self) -> None:
        self.assertFalse(
            autopilot_allows(
                "git push origin main",
                RiskLevel.RISKY,
                "git write",
            )
        )


if __name__ == "__main__":
    unittest.main()
