"""AgentJail user config — ``~/.agentjail/config.json``."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Literal

from agent_jail.shim import agentjail_home

Mode = Literal["interactive", "invisible"]

DEFAULT_URL = "http://127.0.0.1:8420"


@dataclass
class AgentJailConfig:
    mode: Mode = "interactive"
    autopilot: bool = False
    shell_integration: bool = False
    service: bool = False
    url: str = DEFAULT_URL
    python_executable: str = ""
    workdir: str = ""

    def is_invisible(self) -> bool:
        return self.mode == "invisible"


def config_path(root: Path | None = None) -> Path:
    return agentjail_home(root) / "config.json"


def default_config() -> AgentJailConfig:
    return AgentJailConfig(python_executable=str(Path(sys.executable).resolve()))


def load_config(root: Path | None = None) -> AgentJailConfig:
    path = config_path(root)
    cfg = default_config()
    if not path.is_file():
        return cfg
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return cfg
    if not isinstance(raw, dict):
        return cfg
    known = {f.name for f in fields(AgentJailConfig)}
    data: dict[str, Any] = {}
    for key, value in raw.items():
        if key in known:
            data[key] = value
    merged = {**asdict(cfg), **data}
    mode = merged.get("mode", "interactive")
    if mode not in ("interactive", "invisible"):
        mode = "interactive"
    merged["mode"] = mode
    if not merged.get("python_executable"):
        merged["python_executable"] = str(Path(sys.executable).resolve())
    return AgentJailConfig(**merged)


def save_config(cfg: AgentJailConfig, root: Path | None = None) -> Path:
    home = agentjail_home(root)
    home.mkdir(parents=True, exist_ok=True)
    path = config_path(root)
    payload = asdict(cfg)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def apply_invisible_defaults(cfg: AgentJailConfig) -> AgentJailConfig:
    cfg.mode = "invisible"
    cfg.autopilot = True
    cfg.shell_integration = True
    cfg.service = True
    if not cfg.python_executable:
        cfg.python_executable = str(Path(sys.executable).resolve())
    return cfg


def apply_interactive_defaults(cfg: AgentJailConfig) -> AgentJailConfig:
    cfg.mode = "interactive"
    cfg.autopilot = False
    cfg.shell_integration = False
    cfg.service = False
    return cfg
