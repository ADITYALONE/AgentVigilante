"""Filesystem snapshot and diff helpers for sandboxed agent runs."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)

SKIP_DIR_NAMES = {
    ".git",
    ".agentjail",
    ".agentjail_shadow",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
}

TEXT_SIZE_CAP = 256 * 1024  # 256 KiB


@dataclass(frozen=True)
class FileMeta:
    sha256: str
    size: int
    mtime_ns: int
    text_content: str | None = None


class Snapshot(dict[str, FileMeta]):
    """Map of relative path → file metadata."""


class FileChange(TypedDict, total=False):
    path: str
    size: int
    sha256: str
    unified_diff: str
    binary_or_large: bool


class DiffResult(TypedDict):
    added: list[FileChange]
    modified: list[FileChange]
    deleted: list[FileChange]


class DiffEngine:
    """Track filesystem changes under a mounted workspace root."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise FileNotFoundError(f"diff root does not exist: {self.root}")

    def snapshot(self) -> Snapshot:
        """Walk ``root`` and record hash/size/mtime for each regular file.

        Text-eligible files (UTF-8, no NUL, ≤256 KiB) also store content so
        later diffs can emit unified patches without a secondary backup tree.
        """
        snap = Snapshot()
        for path in self._iter_files():
            rel = path.relative_to(self.root).as_posix()
            try:
                stat = path.stat()
                digest = self._sha256(path)
                text = self._read_text_if_eligible(path, stat.st_size)
            except OSError as exc:
                logger.warning("Skipping unreadable file %s: %s", path, exc)
                continue
            snap[rel] = FileMeta(
                sha256=digest,
                size=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                text_content=text,
            )
        logger.debug("Snapshot captured files=%s root=%s", len(snap), self.root)
        return snap

    def diff(self, before: Snapshot) -> DiffResult:
        """Compare current tree against a prior ``snapshot()`` result."""
        after = self.snapshot()
        before_keys = set(before)
        after_keys = set(after)

        added: list[FileChange] = []
        modified: list[FileChange] = []
        deleted: list[FileChange] = []

        for path in sorted(after_keys - before_keys):
            meta = after[path]
            added.append(self._build_change(path, old_text=None, new_meta=meta))

        for path in sorted(before_keys - after_keys):
            meta = before[path]
            deleted.append(
                FileChange(path=path, size=meta.size, sha256=meta.sha256)
            )

        for path in sorted(before_keys & after_keys):
            old_meta = before[path]
            new_meta = after[path]
            if old_meta.sha256 == new_meta.sha256:
                continue
            modified.append(
                self._build_change(
                    path,
                    old_text=old_meta.text_content,
                    new_meta=new_meta,
                )
            )

        result = DiffResult(added=added, modified=modified, deleted=deleted)
        logger.info(
            "Diff complete added=%s modified=%s deleted=%s",
            len(added),
            len(modified),
            len(deleted),
        )
        return result

    @staticmethod
    def _build_change(
        rel_path: str,
        *,
        old_text: str | None,
        new_meta: FileMeta,
    ) -> FileChange:
        change = FileChange(
            path=rel_path,
            size=new_meta.size,
            sha256=new_meta.sha256,
        )
        new_text = new_meta.text_content
        if new_text is None:
            change["binary_or_large"] = True
            return change

        from_lines = [] if old_text is None else old_text.splitlines(keepends=True)
        to_lines = new_text.splitlines(keepends=True)
        change["unified_diff"] = "".join(
            unified_diff(
                from_lines,
                to_lines,
                fromfile=f"a/{rel_path}",
                tofile=f"b/{rel_path}",
            )
        )
        return change

    def _iter_files(self):
        for path in self.root.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            if any(part in SKIP_DIR_NAMES for part in path.relative_to(self.root).parts):
                continue
            yield path

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _read_text_if_eligible(path: Path, size: int) -> str | None:
        if size > TEXT_SIZE_CAP:
            return None
        try:
            data = path.read_bytes()
        except OSError:
            return None
        if b"\x00" in data:
            return None
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return None
