"""Integration-ish tests for status API and autopilot scheduling."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from agent_vigilante.dashboard.server import create_app
from agent_vigilante.core import proxy as proxy_module


class StatusApiTests(unittest.TestCase):
    def test_status_and_block_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(
                workdir=tmp,
                base_image="agentvigilante-sandbox:local",
                proxy_port=18901,
                native_notify=False,
                autopilot=True,
                mode="invisible",
            )
            with TestClient(app) as client:
                proxy_module._recent_events.clear()
                proxy_module.store._jobs.clear()
                st = client.get("/v1/status")
                self.assertEqual(st.status_code, 200)
                body = st.json()
                self.assertEqual(body["mode"], "invisible")
                self.assertTrue(body["autopilot"])

                blocked = client.post(
                    "/v1/commands",
                    json={"command": "rm -rf /tmp/x", "timeout": 5},
                )
                self.assertEqual(blocked.status_code, 200)
                self.assertEqual(blocked.json()["status"], "blocked")

                events = client.get("/v1/events/recent")
                self.assertEqual(events.status_code, 200)
                types = [e["type"] for e in events.json()]
                self.assertIn("blocked", types)

    def test_autopilot_auto_runs_npm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(
                workdir=tmp,
                base_image="agentvigilante-sandbox:local",
                proxy_port=18902,
                native_notify=False,
                autopilot=True,
                mode="invisible",
            )
            with TestClient(app) as client:
                proxy_module.store._jobs.clear()
                with mock.patch.object(proxy_module, "_schedule_execution"):
                    resp = client.post(
                        "/v1/commands",
                        json={"command": "npm install lodash", "timeout": 5},
                    )
                self.assertEqual(resp.status_code, 200)
                job = resp.json()
                # Autopilot demotes to SAFE auto-run → running (not pending)
                self.assertEqual(job["status"], "running")
                self.assertNotEqual(job["status"], "pending")

    def test_sensitive_stays_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(
                workdir=tmp,
                base_image="agentvigilante-sandbox:local",
                proxy_port=18903,
                native_notify=False,
                autopilot=True,
                mode="invisible",
            )
            with TestClient(app) as client:
                proxy_module.store._jobs.clear()
                resp = client.post(
                    "/v1/commands",
                    json={"command": "echo leak > .env", "timeout": 5},
                )
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json()["status"], "pending")


if __name__ == "__main__":
    unittest.main()
