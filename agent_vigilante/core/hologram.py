"""Holographic COW shadow workspaces — isolate agent writes from origin."""

from __future__ import annotations

import logging
import os
import platform
import shutil
import stat
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

SHADOW_ROOT_NAME = ".agentvigilante_shadow"

SKIP_NAMES = {
    ".git",
    ".agentvigilante",
    SHADOW_ROOT_NAME,
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
}


def shadow_path_for(origin: Path, job_id: str) -> Path:
    token = "".join(c if c.isalnum() or c in "-_" else "-" for c in job_id)
    return origin.resolve() / SHADOW_ROOT_NAME / token


def clone_file(src: Path, dst: Path) -> None:
    """Copy-on-write clone ``src`` → ``dst`` with best-effort platform support."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()

    system = platform.system()
    if system == "Darwin":
        # APFS clonefile via cp -c (copy-on-write when supported)
        result = subprocess.run(
            ["cp", "-c", str(src), str(dst)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and dst.exists():
            return
    elif system == "Linux":
        result = subprocess.run(
            ["cp", "--reflink=auto", str(src), str(dst)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and dst.exists():
            return

    shutil.copy2(src, dst)


def create_shadow(origin: Path, job_id: str) -> Path:
    """Build a COW hologram of ``origin`` for ``job_id`` and return its path."""
    origin = origin.resolve()
    shadow = shadow_path_for(origin, job_id)
    if shadow.exists():
        shutil.rmtree(shadow, ignore_errors=True)
    shadow.mkdir(parents=True, exist_ok=True)

    file_count = 0
    for root, dirs, files in os.walk(origin):
        root_path = Path(root)
        # Prune skipped directories in-place
        dirs[:] = [d for d in dirs if d not in SKIP_NAMES]
        try:
            rel_root = root_path.relative_to(origin)
        except ValueError:
            continue
        # Never walk into shadow root
        if rel_root.parts and rel_root.parts[0] == SHADOW_ROOT_NAME:
            dirs.clear()
            continue

        dest_root = shadow / rel_root if str(rel_root) != "." else shadow
        dest_root.mkdir(parents=True, exist_ok=True)

        for name in files:
            src = root_path / name
            if src.is_symlink():
                # Materialize symlink target text only (no follow)
                dst = dest_root / name
                try:
                    if dst.exists() or dst.is_symlink():
                        dst.unlink()
                    dst.symlink_to(os.readlink(src))
                except OSError as exc:
                    logger.debug("Skip symlink %s: %s", src, exc)
                continue
            if not src.is_file():
                continue
            dst = dest_root / name
            try:
                clone_file(src, dst)
                file_count += 1
            except OSError as exc:
                logger.warning("Failed to clone %s: %s", src, exc)

    logger.info(
        "Hologram created job=%s files=%s shadow=%s",
        job_id,
        file_count,
        shadow,
    )
    return shadow


def destroy_shadow(shadow: Path | None) -> None:
    if shadow is None:
        return
    shadow = Path(shadow)
    if not shadow.exists():
        return
    shutil.rmtree(shadow, ignore_errors=True)
    logger.info("Hologram destroyed path=%s", shadow)
    # Clean empty parent .agentvigilante_shadow
    parent = shadow.parent
    if parent.name == SHADOW_ROOT_NAME and parent.is_dir():
        try:
            next(parent.iterdir())
        except StopIteration:
            parent.rmdir()
        except OSError:
            pass


def promote_shadow(
    origin: Path,
    shadow: Path,
    *,
    added: list[str] | None = None,
    modified: list[str] | None = None,
    deleted: list[str] | None = None,
) -> list[str]:
    """Copy hologram changes into ``origin``. Return list of promoted relative paths."""
    origin = origin.resolve()
    shadow = Path(shadow).resolve()
    promoted: list[str] = []

    for rel in list(added or []) + list(modified or []):
        src = shadow / rel
        dst = origin / rel
        if not src.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            if dst.exists() or dst.is_symlink():
                dst.unlink()
            dst.symlink_to(os.readlink(src))
        elif src.is_file():
            shutil.copy2(src, dst)
            # Ensure writable for developer after promote
            mode = dst.stat().st_mode
            dst.chmod(mode | stat.S_IWUSR)
        else:
            continue
        promoted.append(rel)

    for rel in deleted or []:
        dst = origin / rel
        if dst.is_symlink() or dst.is_file():
            dst.unlink()
            promoted.append(rel)
        elif dst.is_dir():
            shutil.rmtree(dst, ignore_errors=True)
            promoted.append(rel)

    logger.info("Promoted %s paths from hologram to origin", len(promoted))
    return promoted
