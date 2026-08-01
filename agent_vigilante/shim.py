"""PATH shim install — ``~/.agentvigilante/shims`` + real binary map."""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SHIM_NAMES: tuple[str, ...] = (
    "bash",
    "sh",
    "zsh",
    "python",
    "python3",
    "node",
    "npm",
    "npx",
    "pip",
    "pip3",
    "yarn",
    "pnpm",
    "git",
)

DEFAULT_AGENTVIGILANTE_HOME = Path.home() / ".agentvigilante"


def agentvigilante_home(root: Path | None = None) -> Path:
    return Path(root) if root is not None else DEFAULT_AGENTVIGILANTE_HOME


def shim_dir(root: Path | None = None) -> Path:
    return agentvigilante_home(root) / "shims"


def real_bins_path(root: Path | None = None) -> Path:
    return agentvigilante_home(root) / "real_bins.json"


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def agentvigilante_argv() -> list[str]:
    """Absolute interpreter + ``-m agent_vigilante`` so shimmed python cannot recurse."""
    return [str(Path(sys.executable).resolve()), "-m", "agent_vigilante"]


def resolve_real_bin(name: str, *, skip_dir: Path | None = None) -> Path | None:
    """Find ``name`` on PATH, skipping the shim directory."""
    skip: Path | None = None
    if skip_dir is not None:
        try:
            skip = skip_dir.resolve()
        except OSError:
            skip = skip_dir

    search_paths: list[str] = []
    env_path = os.environ.get("PATH", "")
    if env_path:
        search_paths.extend(env_path.split(os.pathsep))
    for common in ("/bin", "/usr/bin", "/usr/local/bin", "/opt/homebrew/bin"):
        if common not in search_paths:
            search_paths.append(common)

    seen: set[str] = set()
    for part in search_paths:
        if not part or part in seen:
            continue
        seen.add(part)
        try:
            part_path = Path(part)
            if skip is not None:
                try:
                    if part_path.resolve() == skip:
                        continue
                except OSError:
                    if part_path == skip:
                        continue
            candidate = part_path / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate.resolve()
        except OSError:
            continue

    which = shutil.which(name)
    if which:
        path = Path(which)
        try:
            resolved = path.resolve()
            if skip is not None and resolved.parent == skip:
                return None
            if path.is_file() and os.access(path, os.X_OK):
                return resolved
        except OSError:
            pass
    return None


def _shim_script(*, name: str, real_bin: str, agentvigilante_py: str) -> str:
    real_q = _shell_quote(real_bin)
    py_q = _shell_quote(agentvigilante_py)
    name_q = _shell_quote(name)
    return f"""#!/bin/sh
# AgentVigilante PATH shim for {name}
# Generated — do not edit; re-run: agentvigilante shim-install
if [ -n "${{AGENTVIGILANTE_BYPASS}}" ]; then
  exec {real_q} "$@"
fi
exec {py_q} -m agent_vigilante exec-shim --bin {name_q} -- "$@"
"""


def install_shims(root: Path | None = None) -> dict[str, Any]:
    """Create shim scripts and ``real_bins.json``. Returns a summary dict."""
    home = agentvigilante_home(root)
    shims = shim_dir(root)
    home.mkdir(parents=True, exist_ok=True)
    shims.mkdir(parents=True, exist_ok=True)

    py = str(Path(sys.executable).resolve())
    real_map: dict[str, str] = {}
    written: list[str] = []
    skipped: list[str] = []

    for name in SHIM_NAMES:
        real = resolve_real_bin(name, skip_dir=shims)
        if real is None:
            skipped.append(name)
            # Remove stale shim so PATH falls through
            stale = shims / name
            if stale.exists():
                try:
                    stale.unlink()
                except OSError as exc:
                    logger.debug("Could not remove stale shim %s: %s", stale, exc)
            continue

        real_s = str(real)
        real_map[name] = real_s
        script_path = shims / name
        script_path.write_text(
            _shim_script(name=name, real_bin=real_s, agentvigilante_py=py),
            encoding="utf-8",
        )
        script_path.chmod(0o755)
        written.append(name)

    meta = {
        "agentvigilante_python": py,
        "agentvigilante_argv": agentvigilante_argv(),
        "bins": real_map,
        "written": written,
        "skipped": skipped,
    }
    real_bins_path(root).write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def load_real_bins(root: Path | None = None) -> dict[str, str]:
    path = real_bins_path(root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    bins = data.get("bins")
    if isinstance(bins, dict):
        return {str(k): str(v) for k, v in bins.items()}
    return {}


def real_bin_for(name: str, root: Path | None = None) -> Path | None:
    mapped = load_real_bins(root).get(name)
    if mapped and Path(mapped).is_file():
        return Path(mapped)
    return resolve_real_bin(name, skip_dir=shim_dir(root))
