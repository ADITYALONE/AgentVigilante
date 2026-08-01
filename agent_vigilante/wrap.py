"""``agentvigilante wrap`` — launch a process with PATH shims prepended."""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path
from typing import Mapping, Sequence

import httpx

from agent_vigilante.shim import install_shims, shim_dir

DEFAULT_AGENTVIGILANTE_URL = "http://127.0.0.1:8420"

_MAC_APP_BINARIES: dict[str, tuple[str, ...]] = {
    "cursor": (
        "/Applications/Cursor.app/Contents/MacOS/Cursor",
        str(Path.home() / "Applications/Cursor.app/Contents/MacOS/Cursor"),
    ),
    "code": (
        "/Applications/Visual Studio Code.app/Contents/MacOS/Electron",
        str(
            Path.home()
            / "Applications/Visual Studio Code.app/Contents/MacOS/Electron"
        ),
    ),
}


def daemon_healthy(url: str = DEFAULT_AGENTVIGILANTE_URL) -> bool:
    base = url.rstrip("/")
    try:
        resp = httpx.get(f"{base}/health", timeout=2.0)
        return resp.status_code == 200
    except Exception:
        return False


def build_wrap_env(
    *,
    url: str = DEFAULT_AGENTVIGILANTE_URL,
    base_env: Mapping[str, str] | None = None,
    root: Path | None = None,
) -> dict[str, str]:
    """Compose env with shims on PATH and AgentVigilante markers set."""
    env: dict[str, str] = dict(base_env if base_env is not None else os.environ)
    shims = str(shim_dir(root))
    old_path = env.get("PATH", "")
    env["PATH"] = f"{shims}{os.pathsep}{old_path}" if old_path else shims
    env["AGENTVIGILANTE_ACTIVE"] = "1"
    env["AGENTVIGILANTE_URL"] = url.rstrip("/")
    env.pop("AGENTVIGILANTE_BYPASS", None)

    preferred_shell = None
    for name in ("zsh", "bash", "sh"):
        candidate = Path(shims) / name
        if candidate.is_file():
            preferred_shell = str(candidate)
            break
    if preferred_shell:
        env["SHELL"] = preferred_shell
        env["AGENTVIGILANTE_SHELL"] = preferred_shell
    return env


def resolve_wrap_target(argv: Sequence[str]) -> list[str]:
    """Resolve the command to launch (macOS GUI apps → Mach-O binary)."""
    if not argv:
        raise ValueError("wrap requires a command")
    head = argv[0]
    rest = list(argv[1:])

    head_path = Path(head)
    if head_path.is_file() and os.access(head_path, os.X_OK):
        return [str(head_path.resolve()), *rest]

    key = head.lower()
    if platform.system() == "Darwin" and key in _MAC_APP_BINARIES:
        for candidate in _MAC_APP_BINARIES[key]:
            p = Path(candidate)
            if p.is_file() and os.access(p, os.X_OK):
                return [str(p), *rest]

    which = shutil.which(head)
    if which:
        return [which, *rest]
    return [head, *rest]


def prepare_wrap(
    argv: Sequence[str],
    *,
    url: str = DEFAULT_AGENTVIGILANTE_URL,
    root: Path | None = None,
    base_env: Mapping[str, str] | None = None,
    install: bool = True,
) -> tuple[list[str], dict[str, str]]:
    """Install shims (optional), build env, resolve target argv."""
    if install:
        install_shims(root)
    env = build_wrap_env(url=url, base_env=base_env, root=root)
    target = resolve_wrap_target(argv)
    return target, env
