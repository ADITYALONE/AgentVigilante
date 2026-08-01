"""Native Approve / Deny dialogs for RISKY pending jobs."""

from __future__ import annotations

import asyncio
import logging
import platform
import shutil
import subprocess
import webbrowser
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from agent_jail.core.proxy import Job

logger = logging.getLogger(__name__)

# Set by create_app / configure_notify
notify_base_url: str = "http://127.0.0.1:8420"
_notify_enabled: bool = True


def configure_notify(*, base_url: str, enabled: bool = True) -> None:
    global notify_base_url, _notify_enabled
    notify_base_url = base_url.rstrip("/")
    _notify_enabled = enabled


def schedule_risky_notification(job: Any) -> None:
    """Fire-and-forget native dialog for a pending RISKY job."""
    if not _notify_enabled:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("No running loop; skip native notify for %s", getattr(job, "id", "?"))
        return
    loop.create_task(_notify_and_act(job), name=f"notify-{getattr(job, 'id', 'job')}")


def _truncate(text: str, limit: int = 180) -> str:
    text = text.replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def prompt_risky_choice(
    *,
    command: str,
    risk_reason: str | None,
    job_id: str,
    console_url: str,
) -> str:
    """Blocking UI. Returns ``approve``, ``deny``, ``console``, or ``dismiss``."""
    system = platform.system()
    if system == "Darwin":
        return _macos_dialog(command, risk_reason, job_id)
    if system == "Linux":
        return _linux_dialog(command, risk_reason, job_id)
    if system == "Windows":
        _windows_toast(command, risk_reason)
        return "dismiss"
    return "dismiss"


def _applescript_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _macos_dialog(command: str, risk_reason: str | None, job_id: str) -> str:
    body = _applescript_escape(
        "AgentJail Security Guard\n\n"
        "RISKY command pending approval:\n"
        f"{_truncate(command)}\n\n"
        f"Reason: {_truncate(risk_reason or 'review required', 120)}\n"
        f"Job: {job_id[:8]}"
    )
    script = (
        f'display dialog "{body}" with title "AgentJail" '
        f'buttons {{"Deny", "Open Console", "Approve"}} '
        f'default button "Approve" cancel button "Deny" '
        f'with icon caution'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("osascript dialog failed: %s", exc)
        return "dismiss"

    if result.returncode != 0:
        # Cancel / Deny button → non-zero often
        err = (result.stderr or "").lower()
        if "user canceled" in err or result.returncode == 1:
            return "deny"
        return "dismiss"

    out = (result.stdout or "").strip()
    if "Approve" in out:
        return "approve"
    if "Open Console" in out:
        return "console"
    if "Deny" in out:
        return "deny"
    return "dismiss"


def _linux_dialog(command: str, risk_reason: str | None, job_id: str) -> str:
    text = (
        f"RISKY command:\n{_truncate(command)}\n\n"
        f"{_truncate(risk_reason or '', 120)}\nJob: {job_id[:8]}"
    )
    if shutil.which("zenity"):
        result = subprocess.run(
            [
                "zenity",
                "--question",
                "--title=AgentJail",
                f"--text={text}",
                "--ok-label=Approve",
                "--cancel-label=Deny",
                "--extra-button=Open Console",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
        # zenity: 0 = OK, 1 = cancel, 5 = extra sometimes varies
        if result.returncode == 0:
            return "approve"
        extra = (result.stdout or "").strip().lower()
        if "console" in extra:
            return "console"
        if result.returncode == 1:
            return "deny"
        return "dismiss"

    if shutil.which("kdialog"):
        result = subprocess.run(
            [
                "kdialog",
                "--yesnocancel",
                text,
                "--yes-label",
                "Approve",
                "--no-label",
                "Deny",
                "--title",
                "AgentJail",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
        # 0 yes, 1 no, 2 cancel
        if result.returncode == 0:
            return "approve"
        if result.returncode == 1:
            return "deny"
        return "dismiss"

    # Fallback: notify-send only
    if shutil.which("notify-send"):
        subprocess.run(
            [
                "notify-send",
                "AgentJail",
                f"RISKY pending: {_truncate(command, 80)} — open console to approve",
            ],
            check=False,
        )
    return "dismiss"


def _windows_toast(command: str, risk_reason: str | None) -> None:
    msg = _truncate(f"RISKY: {command} ({risk_reason or 'review'})", 200).replace(
        "'", "''"
    )
    ps = (
        "[Windows.UI.Notifications.ToastNotificationManager, "
        "Windows.UI.Notifications, ContentType = WindowsRuntime] > $null; "
        f"$msg = '{msg}'; "
        "Write-Output $msg"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            check=False,
            timeout=15,
            capture_output=True,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


async def _notify_and_act(job: Job) -> None:
    job_id = job.id
    command = job.command
    risk_reason = job.risk_reason
    console = f"{notify_base_url}/console"

    # Re-check still pending before bothering the user
    await asyncio.sleep(0.15)

    choice = await asyncio.to_thread(
        prompt_risky_choice,
        command=command,
        risk_reason=risk_reason,
        job_id=job_id,
        console_url=console,
    )
    if choice == "dismiss":
        return
    if choice == "console":
        try:
            webbrowser.open(console)
        except Exception as exc:
            logger.debug("Could not open console: %s", exc)
        return

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Skip if already resolved
            status_resp = await client.get(f"{notify_base_url}/v1/commands/{job_id}")
            if status_resp.status_code == 200:
                st = status_resp.json().get("status")
                if st != "pending":
                    return
            if choice == "approve":
                resp = await client.post(
                    f"{notify_base_url}/v1/commands/{job_id}/approve"
                )
                logger.info("Native approve job=%s status=%s", job_id, resp.status_code)
            elif choice == "deny":
                resp = await client.post(
                    f"{notify_base_url}/v1/commands/{job_id}/deny",
                    json={
                        "reason": "Denied via native AgentJail dialog",
                        "revert": False,
                    },
                )
                logger.info("Native deny job=%s status=%s", job_id, resp.status_code)
    except Exception:
        logger.exception("Native notify action failed for job=%s", job_id)
