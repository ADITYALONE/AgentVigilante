"""Blocking client used by PATH shims — submit argv to the AgentVigilante daemon."""

from __future__ import annotations

import os
import shlex
import sys
import time
from typing import Any, Sequence

import httpx

from agent_vigilante.shim import real_bin_for

DEFAULT_BASE_URL = "http://127.0.0.1:8420"
TERMINAL_STATUSES = frozenset(
    {"completed", "failed", "denied", "blocked", "killed"}
)
SHELL_BINS = frozenset({"bash", "sh", "zsh"})
EX_TEMPFAIL = 75


def base_url() -> str:
    return os.environ.get("AGENTVIGILANTE_URL", DEFAULT_BASE_URL).rstrip("/")


def _flag_has_c(flag: str) -> bool:
    """True for ``-c`` or combined short flags containing ``c`` (e.g. ``-lc``)."""
    if flag == "-c":
        return True
    if flag.startswith("--"):
        return flag in ("--command",)
    if flag.startswith("-") and len(flag) > 1 and not flag.startswith("--"):
        return "c" in flag[1:]
    return False


def extract_shell_c_command(args: Sequence[str]) -> str | None:
    """Return the ``-c`` command payload if present."""
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            break
        if a == "-c" or (a.startswith("-") and not a.startswith("--") and _flag_has_c(a)):
            if i + 1 < len(args):
                return args[i + 1]
            return ""
        if a.startswith("-") and a not in ("-", "--"):
            i += 1
            continue
        break
    return None


def shell_script_args(args: Sequence[str]) -> list[str] | None:
    """Return positional script + args if the shell invocation runs a script file."""
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            rest = list(args[i + 1 :])
            return rest or None
        if a == "-c" or (a.startswith("-") and not a.startswith("--") and _flag_has_c(a)):
            return None
        if a.startswith("-") and a not in ("-", "--"):
            i += 1
            continue
        return list(args[i:])
    return None


def is_interactive_shell(bin_name: str, args: Sequence[str]) -> bool:
    if bin_name not in SHELL_BINS:
        return False
    if extract_shell_c_command(args) is not None:
        return False
    if shell_script_args(args) is not None:
        return False
    return True


def reconstruct_command(bin_name: str, args: Sequence[str]) -> str:
    """Build the command string submitted to ``/v1/commands``."""
    if bin_name in SHELL_BINS:
        c_cmd = extract_shell_c_command(args)
        if c_cmd is not None:
            return c_cmd
        script = shell_script_args(args)
        if script is not None:
            return shlex.join([bin_name, *script])
    return shlex.join([bin_name, *args])


def passthrough_real(bin_name: str, args: Sequence[str], *, root=None) -> int:
    """Exec the real host binary with ``AGENTVIGILANTE_BYPASS`` set (never returns on success)."""
    real = real_bin_for(bin_name, root)
    if real is None:
        print(
            f"agentvigilante exec-shim: real binary for {bin_name!r} not found",
            file=sys.stderr,
        )
        return 127
    env = os.environ.copy()
    env["AGENTVIGILANTE_BYPASS"] = "1"
    os.execve(str(real), [str(real), *args], env)
    return 127  # pragma: no cover


def _print_result(job: dict[str, Any]) -> int:
    result = job.get("result") or {}
    stdout = result.get("stdout") or ""
    stderr = result.get("stderr") or ""
    error = result.get("error")
    feedback = result.get("operator_feedback")
    if stdout:
        sys.stdout.write(stdout)
        if not stdout.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()
    if stderr:
        sys.stderr.write(stderr)
        if not stderr.endswith("\n"):
            sys.stderr.write("\n")
        sys.stderr.flush()
    status = job.get("status")
    if status == "denied":
        msg = feedback or error or "Denied by operator"
        print(f"agentvigilante: {msg}", file=sys.stderr)
        return 1
    if status == "blocked":
        print(f"agentvigilante: {error or 'blocked'}", file=sys.stderr)
        return 1
    if status == "killed":
        print("agentvigilante: job killed", file=sys.stderr)
        return 137
    if status == "failed":
        code = result.get("exit_code")
        if error and not stderr:
            print(f"agentvigilante: {error}", file=sys.stderr)
        return int(code) if code is not None else 1
    code = result.get("exit_code")
    if code is None:
        return 0 if status == "completed" else 1
    return int(code)


def run_via_daemon(
    command: str,
    *,
    timeout: int = 30,
    url: str | None = None,
) -> int:
    """POST command, poll until terminal, mirror I/O, return exit code."""
    base = (url or base_url()).rstrip("/")
    try:
        with httpx.Client(timeout=timeout + 60.0) as client:
            try:
                create = client.post(
                    f"{base}/v1/commands",
                    json={"command": command, "timeout": timeout},
                )
            except httpx.ConnectError:
                print(
                    f"agentvigilante: cannot connect to daemon at {base}. "
                    "Start it with: agentvigilante start",
                    file=sys.stderr,
                )
                return EX_TEMPFAIL
            if create.status_code >= 400:
                print(
                    f"agentvigilante: create failed ({create.status_code}): {create.text}",
                    file=sys.stderr,
                )
                return 1
            job = create.json()
            status = job.get("status")
            if status in TERMINAL_STATUSES:
                return _print_result(job)

            job_id = job["id"]
            wait_budget = float(timeout + 300 if status == "pending" else timeout + 30)
            deadline = time.monotonic() + wait_budget
            while True:
                resp = client.get(f"{base}/v1/commands/{job_id}")
                resp.raise_for_status()
                job = resp.json()
                if job.get("status") in TERMINAL_STATUSES:
                    return _print_result(job)
                if time.monotonic() > deadline:
                    print(
                        f"agentvigilante: timed out waiting for job {job_id}",
                        file=sys.stderr,
                    )
                    return EX_TEMPFAIL
                time.sleep(0.4)
    except httpx.HTTPError as exc:
        print(f"agentvigilante: HTTP error: {exc}", file=sys.stderr)
        return 1


def exec_shim_main(
    bin_name: str,
    args: Sequence[str],
    *,
    timeout: int = 30,
    url: str | None = None,
    root=None,
) -> int:
    if os.environ.get("AGENTVIGILANTE_BYPASS"):
        return passthrough_real(bin_name, args, root=root)

    if is_interactive_shell(bin_name, args):
        return passthrough_real(bin_name, args, root=root)

    command = reconstruct_command(bin_name, list(args))
    if not command.strip():
        print("agentvigilante exec-shim: empty command", file=sys.stderr)
        return 2
    return run_via_daemon(command, timeout=timeout, url=url)
