"""Deny feedback API and MCP summary shaping."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from agent_jail.core.command_analyzer import RiskLevel
from agent_jail.core.proxy import JobResult, JobStatus, store
from agent_jail.mcp_server import _summarize_job


class DenyFeedbackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        store._jobs.clear()

    async def test_deny_stores_operator_feedback(self) -> None:
        job = await store.create(
            "npm install evil",
            10,
            status=JobStatus.PENDING,
            risk_level=RiskLevel.RISKY.name,
            risk_reason="npm",
        )
        reason = "Don't use npm, use yarn instead."
        job.status = JobStatus.DENIED
        job.result = JobResult(
            error=f"Denied by operator: {reason}",
            operator_feedback=reason,
        )
        await store.update(job)
        refreshed = await store.get(job.id)
        assert refreshed is not None
        assert refreshed.result is not None
        self.assertEqual(refreshed.result.operator_feedback, reason)
        self.assertIn("yarn", refreshed.result.error or "")

    def test_mcp_summary_includes_guidance_on_deny(self) -> None:
        payload = {
            "id": "abc",
            "status": "denied",
            "risk_level": "RISKY",
            "risk_reason": "npm",
            "command": "npm install",
            "checkpoint_ref": None,
            "result": {
                "error": "Denied by operator: Don't use npm, use yarn instead.",
                "operator_feedback": "Don't use npm, use yarn instead.",
                "fs_diff": {},
            },
        }
        summary = json.loads(_summarize_job(payload))
        self.assertEqual(
            summary["operator_feedback"],
            "Don't use npm, use yarn instead.",
        )
        self.assertIn("Follow the operator_feedback", summary["guidance"])


class DenyHttpTests(unittest.TestCase):
    def test_deny_endpoint_requires_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("agent_jail.core.isolation.docker.from_env") as from_env:
                client_mock = mock.MagicMock()
                client_mock.ping.return_value = True
                from_env.return_value = client_mock

                async def fake_start(self):  # noqa: ANN001
                    return asyncio.create_task(asyncio.sleep(3600))

                with mock.patch(
                    "agent_jail.core.egress_proxy.WhitelistProxy.start_background",
                    fake_start,
                ):
                    from agent_jail.dashboard.server import create_app

                    app = create_app(
                        workdir=tmp,
                        base_image="agentjail-sandbox:local",
                        native_notify=False,
                    )
                    with TestClient(app) as client:
                        store._jobs.clear()
                        job_id = asyncio.run(
                            store.create(
                                "npm install",
                                10,
                                status=JobStatus.PENDING,
                                risk_level="RISKY",
                            )
                        ).id
                        bad = client.post(f"/v1/commands/{job_id}/deny", json={})
                        self.assertEqual(bad.status_code, 422)
                        ok = client.post(
                            f"/v1/commands/{job_id}/deny",
                            json={"reason": "Stop editing .env"},
                        )
                        self.assertEqual(ok.status_code, 200)
                        body = ok.json()
                        self.assertEqual(body["status"], "denied")
                        self.assertEqual(
                            body["result"]["operator_feedback"],
                            "Stop editing .env",
                        )


if __name__ == "__main__":
    unittest.main()
