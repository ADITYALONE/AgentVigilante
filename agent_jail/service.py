"""Background service install — macOS launchd / Linux systemd user unit."""

from __future__ import annotations

import platform
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

LABEL = "com.agentjail.daemon"
SYSTEMD_UNIT = "agentjail.service"


def python_for_service(python_executable: str | None = None) -> str:
    if python_executable:
        return str(Path(python_executable).resolve())
    return str(Path(sys.executable).resolve())


def launchd_plist_path(home: Path | None = None) -> Path:
    h = home or Path.home()
    return h / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def systemd_unit_path(home: Path | None = None) -> Path:
    h = home or Path.home()
    return h / ".config" / "systemd" / "user" / SYSTEMD_UNIT


def render_launchd_plist(
    *,
    python: str,
    url_host: str = "127.0.0.1",
    port: int = 8420,
    workdir: str | None = None,
    log_dir: Path | None = None,
) -> str:
    logs = log_dir or (Path.home() / ".agentjail" / "logs")
    wd = workdir or str(Path.home() / ".agentjail" / "workspace")
    # XML-escape paths
    def esc(s: str) -> str:
        return (
            s.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    args = [
        python,
        "-m",
        "agent_jail",
        "start",
        "--host",
        url_host,
        "--port",
        str(port),
        "--workdir",
        wd,
        "--no-browser",
        "--no-native-notify",
    ]
    arg_xml = "\n".join(f"        <string>{esc(a)}</string>" for a in args)
    return textwrap.dedent(
        f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>Label</key>
            <string>{LABEL}</string>
            <key>ProgramArguments</key>
            <array>
        {arg_xml}
            </array>
            <key>RunAtLoad</key>
            <true/>
            <key>KeepAlive</key>
            <true/>
            <key>StandardOutPath</key>
            <string>{esc(str(logs / "daemon.out.log"))}</string>
            <key>StandardErrorPath</key>
            <string>{esc(str(logs / "daemon.err.log"))}</string>
            <key>EnvironmentVariables</key>
            <dict>
                <key>AGENTJAIL_URL</key>
                <string>http://{url_host}:{port}</string>
            </dict>
        </dict>
        </plist>
        """
    )


def render_systemd_unit(
    *,
    python: str,
    url_host: str = "127.0.0.1",
    port: int = 8420,
    workdir: str | None = None,
) -> str:
    wd = workdir or str(Path.home() / ".agentjail" / "workspace")
    exec_start = (
        f"{python} -m agent_jail start --host {url_host} --port {port} "
        f"--workdir {wd} --no-browser --no-native-notify"
    )
    return textwrap.dedent(
        f"""\
        [Unit]
        Description=AgentJail Invisible Security daemon
        After=default.target

        [Service]
        Type=simple
        ExecStart={exec_start}
        Restart=on-failure
        RestartSec=3
        Environment=AGENTJAIL_URL=http://{url_host}:{port}

        [Install]
        WantedBy=default.target
        """
    )


def install_service(
    *,
    python: str | None = None,
    workdir: str | None = None,
    home: Path | None = None,
    load: bool = True,
) -> dict[str, Any]:
    """Write and optionally load the OS service. Returns summary."""
    py = python_for_service(python)
    system = platform.system()
    h = home or Path.home()
    log_dir = h / ".agentjail" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (h / ".agentjail" / "workspace").mkdir(parents=True, exist_ok=True)

    if system == "Darwin":
        path = launchd_plist_path(h)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            render_launchd_plist(python=py, workdir=workdir, log_dir=log_dir),
            encoding="utf-8",
        )
        if load:
            subprocess.run(
                ["launchctl", "unload", str(path)],
                check=False,
                capture_output=True,
            )
            result = subprocess.run(
                ["launchctl", "load", str(path)],
                check=False,
                capture_output=True,
                text=True,
            )
            return {
                "os": "Darwin",
                "path": str(path),
                "loaded": result.returncode == 0,
                "detail": (result.stderr or result.stdout or "").strip(),
            }
        return {"os": "Darwin", "path": str(path), "loaded": False}

    if system == "Linux":
        path = systemd_unit_path(h)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            render_systemd_unit(python=py, workdir=workdir),
            encoding="utf-8",
        )
        if load:
            subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                check=False,
                capture_output=True,
            )
            enable = subprocess.run(
                ["systemctl", "--user", "enable", "--now", SYSTEMD_UNIT],
                check=False,
                capture_output=True,
                text=True,
            )
            return {
                "os": "Linux",
                "path": str(path),
                "loaded": enable.returncode == 0,
                "detail": (enable.stderr or enable.stdout or "").strip(),
            }
        return {"os": "Linux", "path": str(path), "loaded": False}

    return {
        "os": system,
        "path": None,
        "loaded": False,
        "detail": "service install not supported on this OS",
    }


def uninstall_service(*, home: Path | None = None, unload: bool = True) -> dict[str, Any]:
    system = platform.system()
    h = home or Path.home()
    if system == "Darwin":
        path = launchd_plist_path(h)
        if unload and path.is_file():
            subprocess.run(
                ["launchctl", "unload", str(path)],
                check=False,
                capture_output=True,
            )
        if path.is_file():
            path.unlink()
        return {"os": "Darwin", "removed": True, "path": str(path)}
    if system == "Linux":
        path = systemd_unit_path(h)
        if unload:
            subprocess.run(
                ["systemctl", "--user", "disable", "--now", SYSTEMD_UNIT],
                check=False,
                capture_output=True,
            )
        if path.is_file():
            path.unlink()
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            check=False,
            capture_output=True,
        )
        return {"os": "Linux", "removed": True, "path": str(path)}
    return {"os": system, "removed": False, "detail": "unsupported"}


def service_status(*, home: Path | None = None) -> dict[str, Any]:
    system = platform.system()
    h = home or Path.home()
    if system == "Darwin":
        path = launchd_plist_path(h)
        installed = path.is_file()
        running = False
        if installed:
            probe = subprocess.run(
                ["launchctl", "list", LABEL],
                check=False,
                capture_output=True,
                text=True,
            )
            running = probe.returncode == 0
        return {
            "os": "Darwin",
            "installed": installed,
            "running": running,
            "path": str(path),
        }
    if system == "Linux":
        path = systemd_unit_path(h)
        installed = path.is_file()
        running = False
        if installed:
            probe = subprocess.run(
                ["systemctl", "--user", "is-active", SYSTEMD_UNIT],
                check=False,
                capture_output=True,
                text=True,
            )
            running = (probe.stdout or "").strip() == "active"
        return {
            "os": "Linux",
            "installed": installed,
            "running": running,
            "path": str(path),
        }
    return {"os": system, "installed": False, "running": False}
