"""Autopilot allowlist — silent auto-run for standard RISKY commands."""

from __future__ import annotations

import re
import shlex
from typing import Iterable

from agent_jail.core.command_analyzer import RiskLevel

# Sensitive fragments that always stay HITL even under autopilot
SENSITIVE_FRAGMENTS = (
    ".env",
    ".aws",
    ".ssh",
    "id_rsa",
    "id_ed25519",
    "/etc/passwd",
    "/etc/shadow",
)

# Base commands that autopilot may auto-approve when RISKY (no sensitive hit)
AUTOPILOT_BASES = frozenset(
    {
        "pip",
        "pip3",
        "npm",
        "npx",
        "yarn",
        "pnpm",
        "python",
        "python3",
        "node",
        "pytest",
        "git",
        "echo",
        "touch",
        "mkdir",
        "cp",
        "mv",
        "tee",
        "sed",
        "install",
        "cargo",
    }
)

# npm/yarn/pnpm global install still requires HITL
_GLOBAL_FLAGS = frozenset({"-g", "--global"})


def touches_sensitive(command: str) -> bool:
    lower = command.lower()
    return any(frag in lower for frag in SENSITIVE_FRAGMENTS)


def _tokens(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _base_cmd(tokens: Iterable[str]) -> str | None:
    for t in tokens:
        if t.startswith("-"):
            continue
        return t.split("/")[-1]
    return None


def is_global_package_install(tokens: list[str]) -> bool:
    if not tokens:
        return False
    base = tokens[0].split("/")[-1]
    if base not in {"npm", "npx", "yarn", "pnpm", "pip", "pip3"}:
        return False
    return any(t in _GLOBAL_FLAGS for t in tokens) or (
        base in {"pip", "pip3"} and "--user" in tokens and any(
            re.match(r"^/|~", t) for t in tokens
        )
    )


def autopilot_allows(command: str, risk: RiskLevel, reason: str) -> bool:
    """Return True if a RISKY command should auto-run under autopilot.

    SAFE is already auto; CRITICAL never. Sensitive paths and global installs
    stay pending.
    """
    if risk != RiskLevel.RISKY:
        return False
    if touches_sensitive(command):
        return False
    # Symlink / parse-failure reasons stay HITL
    reason_l = reason.lower()
    if "symlink" in reason_l or "failed to parse" in reason_l:
        return False

    tokens = _tokens(command)
    base = _base_cmd(tokens)
    if base is None or base not in AUTOPILOT_BASES:
        return False
    if is_global_package_install(tokens):
        return False
    # git write subcommands that are especially sensitive stay HITL
    if base == "git" and len(tokens) > 1:
        sub = tokens[1]
        if sub in {"push", "reset", "clean", "rebase", "filter-branch"}:
            return False
    return True
