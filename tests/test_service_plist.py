"""Tests for launchd/systemd unit rendering (no real launchctl)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_jail.service import (
    install_service,
    render_launchd_plist,
    render_systemd_unit,
)


class ServiceRenderTests(unittest.TestCase):
    def test_launchd_contains_headless_flags(self) -> None:
        xml = render_launchd_plist(python="/usr/bin/python3", workdir="/tmp/ws")
        self.assertIn("com.agentjail.daemon", xml)
        self.assertIn("--no-browser", xml)
        self.assertIn("--no-native-notify", xml)
        self.assertIn("/usr/bin/python3", xml)

    def test_systemd_unit(self) -> None:
        unit = render_systemd_unit(python="/usr/bin/python3")
        self.assertIn("ExecStart=", unit)
        self.assertIn("--no-native-notify", unit)

    def test_install_writes_plist_without_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with mock.patch("agent_jail.service.platform.system", return_value="Darwin"):
                summary = install_service(
                    python="/usr/bin/python3",
                    workdir=str(home / "ws"),
                    home=home,
                    load=False,
                )
            path = Path(summary["path"])
            self.assertTrue(path.is_file())
            body = path.read_text(encoding="utf-8")
            self.assertIn("agent_jail", body)


if __name__ == "__main__":
    unittest.main()
