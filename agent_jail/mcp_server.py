"""AgentJail MCP stdio server — route agent tool calls through the jail API."""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer

DEFAULT_BASE_URL = "http://127.0.0.1:8420"
TERMINAL_STATUSES = {"completed", "failed", "denied", "blocked", "killed"}

mcp = MCPServer(
    name="agentjail",
    version="0.3.0",
    description="Holographic sandbox + kernel telemetry via AgentJail",
)


def _base_url() -> str:
    return os.environ.get("AGENTJAIL_URL", DEFAULT_BASE_URL).rstrip("/")


async def _consume_override(client: httpx.AsyncClient) -> str | None:
    try:
        resp = await client.post(f"{_base_url()}/v1/context/override/ack")
        if resp.status_code >= 400:
            return None
        return (resp.json() or {}).get("override")
    except Exception:
        return None


def _summarize_job(job: dict[str, Any], *, override: str | None = None) -> str:
    result = job.get("result") or {}
    fs = result.get("fs_diff") or {}
    summary: dict[str, Any] = {
        "id": job.get("id"),
        "status": job.get("status"),
        "risk_level": job.get("risk_level"),
        "risk_reason": job.get("risk_reason"),
        "command": job.get("command"),
        "checkpoint_ref": job.get("checkpoint_ref"),
        "shadow_path": job.get("shadow_path"),
        "exit_code": result.get("exit_code"),
        "stdout": result.get("stdout"),
        "stderr": result.get("stderr"),
        "error": result.get("error"),
        "operator_feedback": result.get("operator_feedback"),
        "fs_diff": {
            "added": [c.get("path") for c in fs.get("added", [])],
            "modified": [c.get("path") for c in fs.get("modified", [])],
            "deleted": [c.get("path") for c in fs.get("deleted", [])],
        },
    }
    if job.get("status") == "denied":
        summary["guidance"] = (
            "Follow the operator_feedback exactly on your next attempt."
        )
    profile = result.get("syscall_profile")
    if profile:
        summary["syscall_profile_top"] = [
            {"syscall": s.get("syscall"), "calls": s.get("calls")}
            for s in profile[:8]
        ]
    events = result.get("kernel_events") or []
    if events:
        summary["kernel_events_sample"] = events[:12]
    payload = json.dumps(summary, indent=2)
    if override:
        return f"{override}\n\n{payload}"
    return payload


async def _poll_job(
    client: httpx.AsyncClient,
    job_id: str,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout + 5
    while True:
        resp = await client.get(f"{_base_url()}/v1/commands/{job_id}")
        resp.raise_for_status()
        job = resp.json()
        if job.get("status") in TERMINAL_STATUSES:
            return job
        if time.monotonic() > deadline:
            job["poll_timeout"] = True
            return job
        await asyncio.sleep(0.4)


@mcp.tool()
async def agentjail_exec(command: str, timeout: int = 10) -> str:
    """Execute a shell command through AgentJail's holographic sandbox pipeline.

    SAFE commands auto-run in a COW shadow workspace. RISKY commands wait for
    dashboard approval. CRITICAL commands are blocked. Requires `python run.py`.
    """
    async with httpx.AsyncClient(timeout=timeout + 60.0) as client:
        override = await _consume_override(client)
        try:
            create = await client.post(
                f"{_base_url()}/v1/commands",
                json={"command": command, "timeout": timeout},
            )
            create.raise_for_status()
        except httpx.ConnectError:
            return (
                "ERROR: Cannot connect to AgentJail at "
                f"{_base_url()}. Start it with `python run.py` first."
            )
        job = create.json()
        status = job.get("status")
        if status in TERMINAL_STATUSES:
            return _summarize_job(job, override=override)
        wait_budget = float(timeout + 300 if status == "pending" else timeout + 30)
        job = await _poll_job(client, job["id"], wait_budget)
        return _summarize_job(job, override=override)


@mcp.tool()
async def agentjail_job_status(job_id: str) -> str:
    """Look up an AgentJail job by id."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        override = await _consume_override(client)
        try:
            resp = await client.get(f"{_base_url()}/v1/commands/{job_id}")
        except httpx.ConnectError:
            return (
                "ERROR: Cannot connect to AgentJail at "
                f"{_base_url()}. Start it with `python run.py` first."
            )
        if resp.status_code == 404:
            body = json.dumps({"error": "job not found", "id": job_id})
            return f"{override}\n\n{body}" if override else body
        resp.raise_for_status()
        return _summarize_job(resp.json(), override=override)


@mcp.tool()
async def agentjail_revert(job_id: str, reason: str = "") -> str:
    """Wipe the job hologram and inject a SYSTEM OVERRIDE into subsequent tool results.

    Use after a bad agent turn so filesystem state and LLM memory stay aligned.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(
                f"{_base_url()}/v1/commands/{job_id}/memory-revert",
                json={"reason": reason},
            )
        except httpx.ConnectError:
            return (
                "ERROR: Cannot connect to AgentJail at "
                f"{_base_url()}. Start it with `python run.py` first."
            )
        if resp.status_code == 404:
            return json.dumps({"error": "job not found", "id": job_id})
        resp.raise_for_status()
        data = resp.json()
        override = data.get("override") or ""
        return json.dumps(
            {
                "ok": True,
                "job_id": job_id,
                "override": override,
                "guidance": "Treat the SYSTEM OVERRIDE as authoritative.",
            },
            indent=2,
        )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
