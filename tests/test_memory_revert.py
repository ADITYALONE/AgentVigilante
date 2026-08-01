"""Memory revert / context override tests."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from agent_vigilante.core.hologram import create_shadow
from agent_vigilante.core.proxy import (
    JobResult,
    JobStatus,
    consume_context_override,
    peek_context_override,
    store,
)
from agent_vigilante.mcp_server import _summarize_job


class MemoryRevertTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        store._jobs.clear()
        consume_context_override()

    async def test_memory_revert_sets_override_and_wipes_shadow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origin = Path(tmp)
            (origin / "f.txt").write_text("x\n", encoding="utf-8")
            job = await store.create(
                "echo hi",
                10,
                status=JobStatus.COMPLETED,
                risk_level="SAFE",
            )
            shadow = create_shadow(origin, job.id)
            job.shadow_path = str(shadow)
            job.result = JobResult(exit_code=0)
            await store.update(job)
            self.assertTrue(shadow.exists())

            from agent_vigilante.core import proxy as proxy_mod

            with mock.patch.object(proxy_mod, "sandbox") as sb:
                sb.workdir = origin
                # Call handler via importing after patch is awkward; use logic directly
                from agent_vigilante.core.hologram import destroy_shadow
                from agent_vigilante.core.proxy import (
                    _build_memory_override,
                    _set_context_override,
                )

                destroy_shadow(Path(job.shadow_path))
                job.shadow_path = None
                msg = _build_memory_override("Stop that")
                _set_context_override(msg)
                await store.update(job)

            self.assertFalse(shadow.exists())
            self.assertIsNotNone(peek_context_override())
            self.assertIn("SYSTEM OVERRIDE", peek_context_override() or "")
            consumed = consume_context_override()
            self.assertIn("Stop that", consumed or "")
            self.assertIsNone(peek_context_override())

    def test_mcp_summary_prepends_override(self) -> None:
        text = _summarize_job(
            {
                "id": "1",
                "status": "completed",
                "command": "ls",
                "result": {"fs_diff": {}},
            },
            override="SYSTEM OVERRIDE: wiped",
        )
        self.assertTrue(text.startswith("SYSTEM OVERRIDE"))
        self.assertIn('"status": "completed"', text)


class MemoryRevertHttpTests(unittest.TestCase):
    def test_deny_with_revert_arms_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("agent_vigilante.core.isolation.docker.from_env") as from_env:
                client_mock = mock.MagicMock()
                client_mock.ping.return_value = True
                from_env.return_value = client_mock

                async def fake_start(self):  # noqa: ANN001
                    return asyncio.create_task(asyncio.sleep(3600))

                with mock.patch(
                    "agent_vigilante.core.egress_proxy.WhitelistProxy.start_background",
                    fake_start,
                ):
                    from agent_vigilante.dashboard.server import create_app
                    from agent_vigilante.core.proxy import consume_context_override, store

                    consume_context_override()
                    app = create_app(
                        workdir=tmp,
                        base_image="agentvigilante-sandbox:local",
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
                        ok = client.post(
                            f"/v1/commands/{job_id}/deny",
                            json={"reason": "use yarn", "revert": True},
                        )
                        self.assertEqual(ok.status_code, 200)
                        peek = client.get("/v1/context/override")
                        self.assertEqual(peek.status_code, 200)
                        self.assertIn("SYSTEM OVERRIDE", peek.json()["override"] or "")
                        ack = client.post("/v1/context/override/ack")
                        self.assertIn("SYSTEM OVERRIDE", ack.json()["override"] or "")
                        empty = client.get("/v1/context/override")
                        self.assertIsNone(empty.json()["override"])


if __name__ == "__main__":
    unittest.main()
