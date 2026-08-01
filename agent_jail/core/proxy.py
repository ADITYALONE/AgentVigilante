"""FastAPI routes for the human-in-the-loop command proxy."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from agent_jail.core.checkpoint import (
    CheckpointError,
    create_checkpoint,
    restore_checkpoint,
)
from agent_jail.core.command_analyzer import CommandAnalyzer, RiskLevel
from agent_jail.core.diff_engine import DiffEngine, DiffResult
from agent_jail.core.egress_proxy import EgressEvent, WhitelistProxy
from agent_jail.core.hologram import create_shadow, destroy_shadow, promote_shadow
from agent_jail.core.isolation import AgentSandbox
from agent_jail.core.path_guard import find_symlink_paths
from agent_jail.core.strace_profile import (
    KernelEvent,
    SyscallStat,
    counts_from_events,
    parse_strace_c,
    parse_strace_events,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")
analyzer = CommandAnalyzer()


def _demux_docker_chunk(data: bytes) -> list[tuple[str, bytes]]:
    """Parse Docker multiplexed log frames into (stream, payload) pairs."""
    if not data:
        return []
    if len(data) < 8 or data[0] not in (1, 2) or data[1:4] != b"\x00\x00\x00":
        return [("stdout", data)]

    out: list[tuple[str, bytes]] = []
    offset = 0
    while offset + 8 <= len(data):
        stream_type = data[offset]
        size = int.from_bytes(data[offset + 4 : offset + 8], "big")
        offset += 8
        payload = data[offset : offset + size]
        offset += size
        name = "stderr" if stream_type == 2 else "stdout"
        out.append((name, payload))
    return out or [("stdout", data)]


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    DENIED = "denied"
    FAILED = "failed"
    BLOCKED = "blocked"
    KILLED = "killed"


class CommandCreate(BaseModel):
    command: str = Field(..., min_length=1)
    timeout: int = Field(default=10, ge=1, le=300)


class DenyBody(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)
    revert: bool = False


class JobResult(BaseModel):
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    fs_diff: DiffResult | None = None
    error: str | None = None
    operator_feedback: str | None = None
    syscall_profile: list[SyscallStat] | None = None
    kernel_events: list[KernelEvent] | None = None


class Job(BaseModel):
    id: str
    command: str
    timeout: int
    status: JobStatus
    risk_level: str | None = None
    risk_reason: str | None = None
    container_id: str | None = None
    checkpoint_ref: str | None = None
    shadow_path: str | None = None
    created_at: str
    updated_at: str
    result: JobResult | None = None


class RevertResult(BaseModel):
    ok: bool
    checkpoint_ref: str


class PromoteResult(BaseModel):
    ok: bool
    promoted: list[str]


class ContextOverrideOut(BaseModel):
    override: str | None = None


class MemoryRevertBody(BaseModel):
    reason: str = Field(default="", max_length=2000)


class EgressEventOut(BaseModel):
    action: str
    host: str
    port: int
    timestamp: str
    detail: str = ""


class JobStore:
    """In-memory pending/completed job registry."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        command: str,
        timeout: int,
        *,
        status: JobStatus = JobStatus.PENDING,
        risk_level: str | None = None,
        risk_reason: str | None = None,
        result: JobResult | None = None,
    ) -> Job:
        now = _utcnow()
        job = Job(
            id=str(uuid.uuid4()),
            command=command,
            timeout=timeout,
            status=status,
            risk_level=risk_level,
            risk_reason=risk_reason,
            created_at=now,
            updated_at=now,
            result=result,
        )
        async with self._lock:
            self._jobs[job.id] = job
        return job

    async def get(self, job_id: str) -> Job | None:
        async with self._lock:
            return self._jobs.get(job_id)

    async def list_pending(self) -> list[Job]:
        async with self._lock:
            return [j for j in self._jobs.values() if j.status == JobStatus.PENDING]

    async def list_running(self) -> list[Job]:
        async with self._lock:
            return [j for j in self._jobs.values() if j.status == JobStatus.RUNNING]

    async def list_recent(self, limit: int = 20) -> list[Job]:
        async with self._lock:
            jobs = sorted(
                self._jobs.values(),
                key=lambda j: j.updated_at,
                reverse=True,
            )
            return jobs[:limit]

    async def update(self, job: Job) -> Job:
        job.updated_at = _utcnow()
        async with self._lock:
            self._jobs[job.id] = job
        return job


class StreamHub:
    """Fan-out live container output to WebSocket subscribers."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(
            list
        )
        self._buffers: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def subscribe(self, job_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        async with self._lock:
            for event in self._buffers[job_id]:
                await queue.put(event)
            self._subscribers[job_id].append(queue)
        return queue

    async def unsubscribe(self, job_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            subs = self._subscribers.get(job_id, [])
            if queue in subs:
                subs.remove(queue)

    async def publish(self, job_id: str, event: dict[str, Any]) -> None:
        async with self._lock:
            self._buffers[job_id].append(event)
            if len(self._buffers[job_id]) > 500:
                self._buffers[job_id] = self._buffers[job_id][-500:]
            subscribers = list(self._subscribers.get(job_id, []))
        for queue in subscribers:
            await queue.put(event)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# Populated by create_app / run.py
store = JobStore()
streams = StreamHub()
sandbox: AgentSandbox | None = None
diff_engine: DiffEngine | None = None
egress_proxy: WhitelistProxy | None = None
_running_tasks: dict[str, asyncio.Task[None]] = {}
_job_containers: dict[str, str] = {}
pending_context_override: str | None = None
autopilot_enabled: bool = False
runtime_mode: str = "interactive"
_recent_events: list[dict[str, Any]] = []
_RECENT_EVENTS_MAX = 50


def configure(
    sb: AgentSandbox,
    de: DiffEngine,
    proxy: WhitelistProxy | None = None,
    *,
    autopilot: bool = False,
    mode: str = "interactive",
) -> None:
    global sandbox, diff_engine, egress_proxy, autopilot_enabled, runtime_mode
    sandbox = sb
    diff_engine = de
    egress_proxy = proxy
    autopilot_enabled = autopilot
    runtime_mode = mode


def _push_event(kind: str, payload: dict[str, Any]) -> None:
    event = {"type": kind, "at": _utcnow(), **payload}
    _recent_events.append(event)
    if len(_recent_events) > _RECENT_EVENTS_MAX:
        del _recent_events[: len(_recent_events) - _RECENT_EVENTS_MAX]


async def _broadcast_chunk(job_id: str, data: str) -> None:
    await streams.publish(job_id, {"type": "out", "data": data})


def _set_context_override(message: str) -> None:
    global pending_context_override
    pending_context_override = message
    logger.info("Context override armed (%s chars)", len(message))


def consume_context_override() -> str | None:
    """Return and clear the pending LLM memory override (one-shot)."""
    global pending_context_override
    msg = pending_context_override
    pending_context_override = None
    return msg


def peek_context_override() -> str | None:
    return pending_context_override


def _build_memory_override(reason: str) -> str:
    detail = reason.strip() or "No additional operator reason provided."
    return (
        "SYSTEM OVERRIDE: Your previous execution was rejected and the "
        "holographic workspace was wiped. No changes were promoted to the "
        f"developer workspace. Operator said: \"{detail}\". "
        "Do NOT repeat that approach."
    )


def _load_kernel_telemetry(
    job_id: str,
    shadow: Path | None,
) -> tuple[list[SyscallStat] | None, list[KernelEvent] | None]:
    if sandbox is None:
        return None, None
    token = AgentSandbox._safe_job_token(job_id)
    roots = []
    if shadow is not None:
        roots.append(Path(shadow))
    roots.append(sandbox.workdir)

    events: list[KernelEvent] | None = None
    profile: list[SyscallStat] | None = None

    for root in roots:
        trace = root / ".agentjail" / "strace" / f"{token}.trace"
        summary = root / ".agentjail" / "strace" / f"{token}.txt"
        if trace.is_file() and events is None:
            try:
                text = trace.read_text(encoding="utf-8", errors="replace")
                events = parse_strace_events(text)
                if events:
                    profile = counts_from_events(events)
            except OSError as exc:
                logger.warning("Failed to read strace trace for %s: %s", job_id, exc)
            finally:
                try:
                    trace.unlink(missing_ok=True)
                except OSError:
                    pass
        if summary.is_file() and profile is None:
            try:
                text = summary.read_text(encoding="utf-8", errors="replace")
                profile = parse_strace_c(text) or None
            except OSError as exc:
                logger.warning("Failed to read strace summary for %s: %s", job_id, exc)
            finally:
                try:
                    summary.unlink(missing_ok=True)
                except OSError:
                    pass
    return profile, events or None


async def _run_job_execution(job_id: str) -> None:
    """Create hologram, start container, stream logs, finalize with fs diff."""
    assert sandbox is not None and diff_engine is not None

    job = await store.get(job_id)
    if job is None:
        return

    container = None
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    exit_code = -1
    killed = False
    shadow = None
    job_diff: DiffEngine | None = None

    try:
        # Holographic workspace: COW clone, never mount the origin
        shadow = await asyncio.to_thread(create_shadow, sandbox.workdir, job_id)
        job.shadow_path = str(shadow)
        await store.update(job)
        job_diff = DiffEngine(root=shadow)

        # Time Machine checkpoint inside the hologram
        try:
            checkpoint_ref = await asyncio.to_thread(
                create_checkpoint,
                shadow,
                job_id,
            )
        except CheckpointError as exc:
            logger.warning("Checkpoint error job=%s: %s", job_id, exc)
            checkpoint_ref = None
        if checkpoint_ref:
            job.checkpoint_ref = checkpoint_ref
            await store.update(job)

        before = await asyncio.to_thread(job_diff.snapshot)
        container = await asyncio.to_thread(
            lambda: sandbox.start_command(
                job.command,
                job_id=job_id,
                shadow_dir=shadow,
            )
        )
        job.container_id = container.id
        job.status = JobStatus.RUNNING
        await store.update(job)
        _job_containers[job_id] = container.id

        await streams.publish(
            job_id,
            {
                "type": "meta",
                "data": (
                    f"[hologram {shadow.name} · container {container.short_id}]\r\n"
                ),
            },
        )

        def _iter_logs():
            return container.logs(
                stream=True,
                follow=True,
                stdout=True,
                stderr=True,
            )

        log_iter = await asyncio.to_thread(lambda: iter(_iter_logs()))

        async def _consume_logs() -> None:
            while True:
                try:
                    chunk = await asyncio.to_thread(next, log_iter, None)
                except Exception:
                    break
                if chunk is None:
                    break
                if isinstance(chunk, tuple):
                    frames = []
                    out_b, err_b = chunk
                    if out_b:
                        frames.append(("stdout", out_b))
                    if err_b:
                        frames.append(("stderr", err_b))
                elif isinstance(chunk, (bytes, bytearray)):
                    frames = _demux_docker_chunk(bytes(chunk))
                else:
                    frames = [("stdout", str(chunk).encode("utf-8", errors="replace"))]

                for stream_name, part in frames:
                    if not part:
                        continue
                    text = part.decode("utf-8", errors="replace")
                    if stream_name == "stderr":
                        stderr_parts.append(text)
                    else:
                        stdout_parts.append(text)
                    await _broadcast_chunk(job_id, text)

        consume_task = asyncio.create_task(_consume_logs())
        try:
            wait_result = await asyncio.wait_for(
                asyncio.to_thread(container.wait),
                timeout=job.timeout,
            )
            exit_code = int(wait_result.get("StatusCode", 1))
        except asyncio.TimeoutError:
            killed = True
            await _broadcast_chunk(
                job_id,
                f"\r\n[timeout after {job.timeout}s — killing container]\r\n",
            )
            await asyncio.to_thread(sandbox.kill_container, container.id)
            exit_code = -1
        finally:
            consume_task.cancel()
            try:
                await consume_task
            except asyncio.CancelledError:
                pass

        try:
            final_out = container.logs(stdout=True, stderr=False).decode(
                "utf-8", errors="replace"
            )
            final_err = container.logs(stdout=False, stderr=True).decode(
                "utf-8", errors="replace"
            )
            if final_out:
                stdout_parts = [final_out]
            if final_err:
                stderr_parts = [final_err]
        except Exception:
            pass

        await asyncio.to_thread(sandbox._safe_remove, container)
        container = None
        _job_containers.pop(job_id, None)

        fs_diff: DiffResult = await asyncio.to_thread(job_diff.diff, before)
        syscall_profile, kernel_events = await asyncio.to_thread(
            _load_kernel_telemetry,
            job_id,
            shadow,
        )
        job = await store.get(job_id) or job
        if killed:
            job.status = JobStatus.FAILED
            job.result = JobResult(
                stdout="".join(stdout_parts),
                stderr="".join(stderr_parts),
                exit_code=exit_code,
                fs_diff=fs_diff,
                error=f"Command exceeded timeout of {job.timeout}s and was killed",
                syscall_profile=syscall_profile,
                kernel_events=kernel_events,
            )
        elif job.status == JobStatus.KILLED:
            job.result = JobResult(
                stdout="".join(stdout_parts),
                stderr="".join(stderr_parts),
                exit_code=-1,
                fs_diff=fs_diff,
                error="Killed by operator (E-Stop)",
                syscall_profile=syscall_profile,
                kernel_events=kernel_events,
            )
        else:
            job.status = JobStatus.COMPLETED
            job.result = JobResult(
                stdout="".join(stdout_parts),
                stderr="".join(stderr_parts),
                exit_code=exit_code,
                fs_diff=fs_diff,
                syscall_profile=syscall_profile,
                kernel_events=kernel_events,
            )
        job.container_id = None
        await store.update(job)
        await streams.publish(
            job_id,
            {"type": "done", "exit_code": exit_code, "status": job.status.value},
        )
    except Exception as exc:
        logger.exception("Job execution failed id=%s", job_id)
        if container is not None:
            try:
                await asyncio.to_thread(sandbox.kill_container, container.id)
            except Exception:
                pass
        _job_containers.pop(job_id, None)
        job = await store.get(job_id) or job
        job.status = JobStatus.FAILED
        job.container_id = None
        profile, events = await asyncio.to_thread(
            _load_kernel_telemetry, job_id, shadow
        )
        job.result = JobResult(
            stdout="".join(stdout_parts),
            stderr="".join(stderr_parts),
            exit_code=-1,
            error=str(exc),
            syscall_profile=profile,
            kernel_events=events,
        )
        await store.update(job)
        await streams.publish(
            job_id,
            {"type": "done", "exit_code": -1, "status": job.status.value, "error": str(exc)},
        )
    finally:
        _running_tasks.pop(job_id, None)


def _schedule_execution(job_id: str) -> None:
    task = asyncio.create_task(_run_job_execution(job_id), name=f"job-{job_id}")
    _running_tasks[job_id] = task


def _symlink_guard(command: str) -> tuple[RiskLevel, str] | None:
    """Escalate or block when workspace paths are symlinks (TOCTOU guard)."""
    if sandbox is None:
        return None
    hits = find_symlink_paths(command, sandbox.workdir)
    if not hits:
        return None
    joined = ", ".join(hits)
    return (
        RiskLevel.RISKY,
        f"Workspace symlink path detected (human review required): {joined}",
    )


@router.post("/commands", response_model=Job)
async def create_command(body: CommandCreate) -> Job:
    from agent_jail.core.autopilot import autopilot_allows

    risk, reason = analyzer.analyze(body.command)
    logger.info(
        "Pre-flight risk=%s cmd=%r reason=%s autopilot=%s",
        risk.name,
        body.command,
        reason,
        autopilot_enabled,
    )

    if risk == RiskLevel.CRITICAL:
        job = await store.create(
            body.command,
            body.timeout,
            status=JobStatus.BLOCKED,
            risk_level=risk.name,
            risk_reason=reason,
            result=JobResult(error=f"SYSTEM GUARDRAIL: Command blocked. {reason}"),
        )
        _push_event(
            "blocked",
            {
                "job_id": job.id,
                "command": body.command,
                "risk_level": risk.name,
                "risk_reason": reason,
            },
        )
        return job

    # SAFE commands that touch workspace symlinks escalate to HITL
    if risk == RiskLevel.SAFE:
        guard = _symlink_guard(body.command)
        if guard is not None:
            risk, reason = guard

    # Autopilot: allowlisted RISKY runs silently like SAFE
    if (
        risk == RiskLevel.RISKY
        and autopilot_enabled
        and autopilot_allows(body.command, risk, reason)
    ):
        risk = RiskLevel.SAFE
        reason = f"Autopilot auto-run: {reason}"

    if risk == RiskLevel.SAFE:
        if sandbox is None or diff_engine is None:
            raise HTTPException(status_code=503, detail="sandbox not configured")
        job = await store.create(
            body.command,
            body.timeout,
            status=JobStatus.RUNNING,
            risk_level=risk.name,
            risk_reason=reason,
        )
        _schedule_execution(job.id)
        return job

    # RISKY anomaly → human approval
    job = await store.create(
        body.command,
        body.timeout,
        status=JobStatus.PENDING,
        risk_level=risk.name,
        risk_reason=reason,
    )
    _push_event(
        "pending",
        {
            "job_id": job.id,
            "command": body.command,
            "risk_level": risk.name,
            "risk_reason": reason,
        },
    )
    try:
        from agent_jail.notify import schedule_risky_notification

        schedule_risky_notification(job)
    except Exception:
        logger.exception("Failed to schedule native notify for job=%s", job.id)
    return job


class StatusOut(BaseModel):
    healthy: bool = True
    mode: str
    autopilot: bool
    pending_count: int
    blocked_recent: int


class RecentEventOut(BaseModel):
    type: str
    at: str
    job_id: str | None = None
    command: str | None = None
    risk_level: str | None = None
    risk_reason: str | None = None


@router.get("/status", response_model=StatusOut)
async def runtime_status() -> StatusOut:
    pending = await store.list_pending()
    blocked_recent = sum(1 for e in _recent_events if e.get("type") == "blocked")
    return StatusOut(
        healthy=True,
        mode=runtime_mode,
        autopilot=autopilot_enabled,
        pending_count=len(pending),
        blocked_recent=blocked_recent,
    )


@router.get("/events/recent", response_model=list[RecentEventOut])
async def list_recent_events(limit: int = 40) -> list[RecentEventOut]:
    items = _recent_events[-max(1, min(limit, 100)) :]
    out: list[RecentEventOut] = []
    for e in reversed(items):
        out.append(
            RecentEventOut(
                type=str(e.get("type", "")),
                at=str(e.get("at", "")),
                job_id=e.get("job_id"),
                command=e.get("command"),
                risk_level=e.get("risk_level"),
                risk_reason=e.get("risk_reason"),
            )
        )
    return out


@router.get("/commands/{job_id}", response_model=Job)
async def get_command(job_id: str) -> Job:
    job = await store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="command not found")
    return job


@router.get("/pending", response_model=list[Job])
async def list_pending() -> list[Job]:
    return await store.list_pending()


@router.get("/jobs", response_model=list[Job])
async def list_jobs(limit: int = 20) -> list[Job]:
    return await store.list_recent(limit=limit)


@router.get("/egress/events", response_model=list[EgressEventOut])
async def list_egress_events(limit: int = 50) -> list[EgressEventOut]:
    if egress_proxy is None:
        return []
    events: list[EgressEvent] = await egress_proxy.recent_events(limit=limit)
    return [
        EgressEventOut(
            action=e.action,
            host=e.host,
            port=e.port,
            timestamp=e.timestamp,
            detail=e.detail,
        )
        for e in events
    ]


@router.post("/commands/{job_id}/approve", response_model=Job)
async def approve_command(job_id: str) -> Job:
    if sandbox is None or diff_engine is None:
        raise HTTPException(status_code=503, detail="sandbox not configured")

    job = await store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="command not found")
    if job.status != JobStatus.PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"command is {job.status}, expected pending",
        )

    # Re-check workspace symlinks at approval time (TOCTOU)
    hits = find_symlink_paths(job.command, sandbox.workdir)
    if hits:
        joined = ", ".join(hits)
        reason = f"Blocked at approve: workspace symlink path detected: {joined}"
        job.status = JobStatus.BLOCKED
        job.risk_level = RiskLevel.CRITICAL.name
        job.risk_reason = reason
        job.result = JobResult(error=f"SYSTEM GUARDRAIL: {reason}")
        await store.update(job)
        return job

    job.status = JobStatus.RUNNING
    await store.update(job)
    _schedule_execution(job.id)
    return job


@router.post("/commands/{job_id}/deny", response_model=Job)
async def deny_command(job_id: str, body: DenyBody) -> Job:
    job = await store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="command not found")
    if job.status != JobStatus.PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"command is {job.status}, expected pending",
        )

    reason = body.reason.strip()
    job.status = JobStatus.DENIED
    job.result = JobResult(
        error=f"Denied by operator: {reason}",
        operator_feedback=reason,
    )
    if body.revert:
        if job.shadow_path:
            await asyncio.to_thread(destroy_shadow, Path(job.shadow_path))
            job.shadow_path = None
        _set_context_override(_build_memory_override(reason))
    await store.update(job)
    logger.info(
        "Denied command id=%s reason=%r revert=%s",
        job.id,
        reason,
        body.revert,
    )
    return job


@router.post("/commands/{job_id}/revert", response_model=RevertResult)
async def revert_command(job_id: str) -> RevertResult:
    if sandbox is None:
        raise HTTPException(status_code=503, detail="sandbox not configured")

    job = await store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="command not found")
    if not job.checkpoint_ref:
        raise HTTPException(status_code=409, detail="no checkpoint available for job")
    if job.status in (JobStatus.PENDING, JobStatus.RUNNING):
        raise HTTPException(
            status_code=409,
            detail=f"cannot revert while job is {job.status.value}",
        )

    target = Path(job.shadow_path) if job.shadow_path else sandbox.workdir
    try:
        await asyncio.to_thread(
            restore_checkpoint,
            target,
            job.checkpoint_ref,
        )
    except CheckpointError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return RevertResult(ok=True, checkpoint_ref=job.checkpoint_ref)


@router.post("/commands/{job_id}/promote", response_model=PromoteResult)
async def promote_command(job_id: str) -> PromoteResult:
    if sandbox is None:
        raise HTTPException(status_code=503, detail="sandbox not configured")

    job = await store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="command not found")
    if not job.shadow_path:
        raise HTTPException(status_code=409, detail="no holographic workspace for job")
    if job.status in (JobStatus.PENDING, JobStatus.RUNNING):
        raise HTTPException(
            status_code=409,
            detail=f"cannot promote while job is {job.status.value}",
        )

    fs = job.result.fs_diff if job.result else None
    fs_data: dict[str, Any] = {}
    if fs is not None:
        fs_data = fs.model_dump() if hasattr(fs, "model_dump") else dict(fs)  # type: ignore[arg-type]

    def _paths(items: list[Any]) -> list[str]:
        out: list[str] = []
        for item in items:
            if isinstance(item, dict):
                p = item.get("path")
            else:
                p = getattr(item, "path", None)
            if p:
                out.append(str(p))
        return out

    added = _paths(fs_data.get("added", []))
    modified = _paths(fs_data.get("modified", []))
    deleted = _paths(fs_data.get("deleted", []))

    promoted = await asyncio.to_thread(
        promote_shadow,
        sandbox.workdir,
        Path(job.shadow_path),
        added=added,
        modified=modified,
        deleted=deleted,
    )
    await asyncio.to_thread(destroy_shadow, Path(job.shadow_path))
    job.shadow_path = None
    await store.update(job)
    return PromoteResult(ok=True, promoted=promoted)


@router.post("/commands/{job_id}/memory-revert")
async def memory_revert_command(
    job_id: str,
    body: MemoryRevertBody | None = None,
) -> dict[str, Any]:
    """Wipe hologram + arm SYSTEM OVERRIDE for MCP tool results."""
    job = await store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="command not found")

    reason = (body.reason if body else "") or (
        (job.result.operator_feedback if job.result else None) or "Rejected by operator"
    )
    if job.shadow_path:
        await asyncio.to_thread(destroy_shadow, Path(job.shadow_path))
        job.shadow_path = None
    if job.status == JobStatus.PENDING:
        job.status = JobStatus.DENIED
        job.result = JobResult(
            error=f"Denied by operator: {reason}",
            operator_feedback=reason,
        )
    override = _build_memory_override(reason)
    _set_context_override(override)
    await store.update(job)
    return {"ok": True, "override": override, "job_id": job_id}


@router.get("/context/override", response_model=ContextOverrideOut)
async def get_context_override() -> ContextOverrideOut:
    return ContextOverrideOut(override=peek_context_override())


@router.post("/context/override/ack", response_model=ContextOverrideOut)
async def ack_context_override() -> ContextOverrideOut:
    msg = consume_context_override()
    return ContextOverrideOut(override=msg)


@router.post("/commands/{job_id}/kill", response_model=Job)
async def kill_command(job_id: str) -> Job:
    if sandbox is None:
        raise HTTPException(status_code=503, detail="sandbox not configured")

    job = await store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="command not found")
    if job.status != JobStatus.RUNNING:
        raise HTTPException(
            status_code=409,
            detail=f"command is {job.status}, expected running",
        )

    container_id = _job_containers.get(job_id) or job.container_id
    job.status = JobStatus.KILLED
    await store.update(job)
    if container_id:
        await asyncio.to_thread(sandbox.kill_container, container_id)
    await streams.publish(
        job_id,
        {"type": "out", "data": "\r\n[E-Stop] container killed by operator\r\n"},
    )
    logger.warning("Killed job id=%s container=%s", job_id, container_id)
    return job


@router.post("/estop")
async def emergency_stop() -> dict[str, Any]:
    if sandbox is None:
        raise HTTPException(status_code=503, detail="sandbox not configured")

    running = await store.list_running()
    killed_ids: list[str] = []
    for job in running:
        container_id = _job_containers.get(job.id) or job.container_id
        job.status = JobStatus.KILLED
        await store.update(job)
        if container_id:
            await asyncio.to_thread(sandbox.kill_container, container_id)
        await streams.publish(
            job.id,
            {"type": "out", "data": "\r\n[E-Stop] global panic — container killed\r\n"},
        )
        killed_ids.append(job.id)
    logger.error("Global E-Stop triggered; killed=%s", killed_ids)
    return {"killed": killed_ids, "count": len(killed_ids)}


@router.websocket("/commands/{job_id}/stream")
async def stream_command(websocket: WebSocket, job_id: str) -> None:
    job = await store.get(job_id)
    if job is None:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    queue = await streams.subscribe(job_id)
    try:
        # If job already finished, send a done event from result.
        if job.status not in (JobStatus.RUNNING, JobStatus.PENDING) and job.result:
            if job.result.stdout:
                await websocket.send_text(
                    json.dumps({"type": "out", "data": job.result.stdout})
                )
            if job.result.stderr:
                await websocket.send_text(
                    json.dumps({"type": "out", "data": job.result.stderr})
                )
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "done",
                        "exit_code": job.result.exit_code,
                        "status": job.status.value,
                    }
                )
            )
            return

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                # Keepalive ping as JSON comment-like event.
                await websocket.send_text(json.dumps({"type": "ping"}))
                refreshed = await store.get(job_id)
                if refreshed and refreshed.status not in (
                    JobStatus.RUNNING,
                    JobStatus.PENDING,
                ):
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "done",
                                "exit_code": (
                                    refreshed.result.exit_code if refreshed.result else None
                                ),
                                "status": refreshed.status.value,
                            }
                        )
                    )
                    break
                continue

            await websocket.send_text(json.dumps(event))
            if event.get("type") == "done":
                break
    except WebSocketDisconnect:
        pass
    finally:
        await streams.unsubscribe(job_id, queue)
