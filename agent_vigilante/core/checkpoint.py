"""Host-side git micro-checkpoints for workspace Time Machine."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class CheckpointError(RuntimeError):
    """Raised when a checkpoint or restore operation fails."""


def _git(workdir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(workdir), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def git_available() -> bool:
    return shutil.which("git") is not None


def ensure_repo(workdir: Path) -> None:
    """Initialize a local git repo in ``workdir`` if missing."""
    workdir = workdir.resolve()
    if not (workdir / ".git").exists():
        # Empty template avoids writing hook samples (fails in some sandboxes).
        init = _git(workdir, "-c", "init.defaultBranch=main", "init", "--template=")
        if init.returncode != 0:
            raise CheckpointError(init.stderr.strip() or "git init failed")
    for key, value in (
        ("user.email", "agentvigilante@local"),
        ("user.name", "AgentVigilante"),
    ):
        cfg = _git(workdir, "config", key, value)
        if cfg.returncode != 0:
            raise CheckpointError(cfg.stderr.strip() or f"git config {key} failed")


def create_checkpoint(workdir: Path, job_id: str) -> str | None:
    """Snapshot the workdir; return commit SHA or None if git is unavailable."""
    if not git_available():
        logger.warning("git not found — skipping checkpoint for job %s", job_id)
        return None

    workdir = workdir.resolve()
    try:
        ensure_repo(workdir)
        add = _git(workdir, "add", "-A")
        if add.returncode != 0:
            raise CheckpointError(add.stderr.strip() or "git add failed")

        tree = _git(workdir, "write-tree")
        if tree.returncode != 0:
            raise CheckpointError(tree.stderr.strip() or "git write-tree failed")
        tree_sha = tree.stdout.strip()

        commit = _git(
            workdir,
            "commit-tree",
            tree_sha,
            "-m",
            f"agentvigilante checkpoint {job_id}",
        )
        if commit.returncode != 0:
            raise CheckpointError(commit.stderr.strip() or "git commit-tree failed")
        sha = commit.stdout.strip()
        if not sha:
            raise CheckpointError("empty commit sha from commit-tree")

        safe_ref = "".join(c if c.isalnum() or c in "-_" else "-" for c in job_id)
        ref = _git(workdir, "update-ref", f"refs/agentvigilante/{safe_ref}", sha)
        if ref.returncode != 0:
            logger.warning("Failed to update checkpoint ref: %s", ref.stderr.strip())

        logger.info("Checkpoint created job=%s sha=%s", job_id, sha[:12])
        return sha
    except CheckpointError:
        raise
    except Exception as exc:
        logger.warning("Checkpoint failed for job %s: %s", job_id, exc)
        return None


def restore_checkpoint(workdir: Path, commit_sha: str) -> None:
    """Restore workdir files to the given checkpoint commit."""
    if not git_available():
        raise CheckpointError("git is not installed on the host")

    workdir = workdir.resolve()
    ensure_repo(workdir)
    if not commit_sha or len(commit_sha) < 7:
        raise CheckpointError("invalid checkpoint sha")

    restore = _git(
        workdir,
        "restore",
        f"--source={commit_sha}",
        "--worktree",
        "--staged",
        ".",
    )
    if restore.returncode == 0:
        logger.info("Restored workdir from checkpoint %s", commit_sha[:12])
        return

    # Fallback for older git
    read = _git(workdir, "read-tree", commit_sha)
    if read.returncode != 0:
        raise CheckpointError(
            restore.stderr.strip()
            or read.stderr.strip()
            or "git restore/read-tree failed"
        )
    checkout = _git(workdir, "checkout-index", "-f", "-a")
    if checkout.returncode != 0:
        raise CheckpointError(checkout.stderr.strip() or "git checkout-index failed")
    logger.info("Restored workdir via read-tree from %s", commit_sha[:12])
