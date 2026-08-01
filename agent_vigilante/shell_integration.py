"""Idempotent shell rc PATH injection for Invisible mode."""

from __future__ import annotations

from pathlib import Path

BEGIN_MARK = "# >>> agentvigilante >>>"
END_MARK = "# <<< agentvigilante <<<"


def _block(url: str, shim_dir: str) -> str:
    return (
        f"{BEGIN_MARK}\n"
        f'export PATH="{shim_dir}:$PATH"\n'
        "export AGENTVIGILANTE_ACTIVE=1\n"
        f'export AGENTVIGILANTE_URL="{url}"\n'
        f"{END_MARK}\n"
    )


def strip_agentvigilante_block(text: str) -> str:
    """Remove marked AgentVigilante block(s) from rc file contents."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped == BEGIN_MARK:
            skipping = True
            continue
        if stripped == END_MARK:
            skipping = False
            continue
        if not skipping:
            out.append(line)
    return "".join(out)


def inject_agentvigilante_block(text: str, *, url: str, shim_dir: str) -> str:
    cleaned = strip_agentvigilante_block(text)
    if cleaned and not cleaned.endswith("\n"):
        cleaned += "\n"
    if cleaned and not cleaned.endswith("\n\n"):
        cleaned += "\n"
    return cleaned + _block(url, shim_dir)


def default_rc_paths(home: Path | None = None) -> list[Path]:
    h = home or Path.home()
    return [h / ".zshrc", h / ".bashrc"]


def enable_shell_integration(
    *,
    url: str,
    shim_dir: Path,
    home: Path | None = None,
    rc_paths: list[Path] | None = None,
) -> list[Path]:
    """Inject PATH block into zshrc/bashrc. Returns paths written."""
    written: list[Path] = []
    targets = rc_paths if rc_paths is not None else default_rc_paths(home)
    block_shim = str(shim_dir)
    for path in targets:
        existing = ""
        if path.is_file():
            existing = path.read_text(encoding="utf-8")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
        updated = inject_agentvigilante_block(existing, url=url, shim_dir=block_shim)
        path.write_text(updated, encoding="utf-8")
        written.append(path)
    return written


def disable_shell_integration(
    *,
    home: Path | None = None,
    rc_paths: list[Path] | None = None,
) -> list[Path]:
    """Strip marked blocks. Returns paths modified."""
    modified: list[Path] = []
    targets = rc_paths if rc_paths is not None else default_rc_paths(home)
    for path in targets:
        if not path.is_file():
            continue
        existing = path.read_text(encoding="utf-8")
        cleaned = strip_agentvigilante_block(existing)
        if cleaned != existing:
            path.write_text(cleaned, encoding="utf-8")
            modified.append(path)
    return modified
