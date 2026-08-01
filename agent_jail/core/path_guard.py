"""Host-side path guards against workspace symlink races."""

from __future__ import annotations

import logging
import shlex
from pathlib import Path

logger = logging.getLogger(__name__)

_SHELL_OPS = {
    "|",
    "||",
    "&&",
    ";",
    ">",
    ">>",
    "<",
    "2>",
    "2>>",
    "&>",
    "&",
    "(",
    ")",
}


def referenced_workdir_paths(command: str, workdir: Path) -> list[Path]:
    """Return existing or symlink paths under ``workdir`` referenced by ``command``."""
    root = workdir.resolve()
    try:
        tokens = shlex.split(command)
    except ValueError:
        return []

    found: list[Path] = []
    seen: set[str] = set()
    for tok in tokens:
        if not tok or tok in _SHELL_OPS or tok.startswith("-"):
            continue

        candidate = Path(tok)
        if candidate.is_absolute():
            path = candidate
            try:
                path.relative_to(root)
            except ValueError:
                # Absolute path outside workdir — ignore for this guard
                continue
        else:
            path = root / tok

        if not (path.is_symlink() or path.exists()):
            continue

        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        found.append(path)
    return found


def find_symlink_paths(command: str, workdir: Path) -> list[str]:
    """Return relative symlink paths under ``workdir`` referenced by ``command``."""
    root = workdir.resolve()
    hits: list[str] = []
    for path in referenced_workdir_paths(command, root):
        if not path.is_symlink():
            continue
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            rel = path.name
        hits.append(rel)
        logger.info(
            "Symlink path referenced in command: %s -> %s",
            rel,
            path.readlink(),
        )
    return hits
