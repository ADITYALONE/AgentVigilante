"""AgentJail CLI — ``agentjail init`` / ``start`` / ``setup``."""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

DEFAULT_AGENTJAIL_URL = "http://127.0.0.1:8420"


def agentjail_mcp_block(url: str = DEFAULT_AGENTJAIL_URL) -> dict[str, Any]:
    return {
        "command": sys.executable,
        "args": ["-m", "agent_jail.mcp_server"],
        "env": {"AGENTJAIL_URL": url},
    }


def discover_config_paths() -> dict[str, Path]:
    """Return IDE label → MCP config path for the current OS."""
    home = Path.home()
    paths: dict[str, Path] = {
        "Claude Code": home / ".claude" / "claude_desktop_config.json",
        "Cursor (Global)": home / ".cursor" / "mcp.json",
        "Windsurf": home / ".codeium" / "windsurf" / "mcp_config.json",
    }
    system = platform.system()
    if system == "Darwin":
        paths["Claude Desktop (Mac)"] = (
            home
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json"
        )
    elif system == "Windows":
        appdata = os.getenv("APPDATA", "")
        if appdata:
            paths["Claude Desktop (Windows)"] = (
                Path(appdata) / "Claude" / "claude_desktop_config.json"
            )
    else:
        paths["Claude Desktop (Linux)"] = (
            home / ".config" / "Claude" / "claude_desktop_config.json"
        )
    return paths


def _backup_path(file_path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return file_path.with_name(f"{file_path.name}.bak.{stamp}")


def patch_json_config(
    file_path: Path,
    *,
    url: str = DEFAULT_AGENTJAIL_URL,
    create_parents: bool = True,
) -> tuple[bool, str]:
    """Safely inject AgentJail into an MCP JSON file.

    Returns ``(ok, message)``.
    """
    try:
        if create_parents:
            file_path.parent.mkdir(parents=True, exist_ok=True)

        data: dict[str, Any] = {}
        if file_path.exists() and file_path.stat().st_size > 0:
            try:
                with open(file_path, encoding="utf-8") as f:
                    loaded = json.load(f)
            except json.JSONDecodeError as exc:
                return False, f"corrupt JSON, refused to overwrite: {exc}"
            if not isinstance(loaded, dict):
                return False, "root JSON value is not an object"
            data = loaded
            backup = _backup_path(file_path)
            shutil.copy2(file_path, backup)

        if "mcpServers" not in data or not isinstance(data.get("mcpServers"), dict):
            data["mcpServers"] = {}

        data["mcpServers"]["agentjail"] = agentjail_mcp_block(url)

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")

        return True, f"configured {file_path}"
    except OSError as exc:
        return False, f"failed patching {file_path}: {exc}"


def cmd_init(args: argparse.Namespace) -> int:
    print("\nAgentJail Auto-Installer")
    print("-" * 30)

    url = args.url
    patched = 0
    attempted = 0

    targets = list(discover_config_paths().items())

    if args.project or args.force_project:
        project_mcp = Path.cwd() / ".cursor" / "mcp.json"
        if args.force_project or project_mcp.parent.exists() or project_mcp.exists():
            targets.append(("Cursor (Project)", project_mcp))

    for name, path in targets:
        # Skip missing IDE install dirs unless --force / project force
        allow_create = bool(args.force) or (
            name == "Cursor (Project)" and bool(args.force_project)
        )
        if not path.parent.exists() and not allow_create:
            continue
        attempted += 1
        print(f" Found {name}...")
        ok, message = patch_json_config(
            path,
            url=url,
            create_parents=True,
        )
        if ok:
            print(f"  OK {message}")
            patched += 1
        else:
            print(f"  FAIL {message}")

    if patched == 0:
        if args.force or attempted == 0:
            default = Path.home() / ".claude" / "claude_desktop_config.json"
            print(
                "\nNo IDE configs patched. "
                f"Creating default at {default}"
            )
            ok, message = patch_json_config(default, url=url, create_parents=True)
            if ok:
                print(f"  OK {message}")
                patched = 1
            else:
                print(f"  FAIL {message}")
                return 1
        else:
            print(
                "\nNo configs written. Install Cursor/Claude or re-run with --force."
            )
            return 1

    print(
        f"\nOK AgentJail connected in {patched} config(s). "
        "Restart Claude Code or Cursor, then run: agentjail start"
    )
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    """Build the AgentJail sandbox Docker image."""
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "setup.sh"
    image = args.image

    if script.is_file() and os.access(script, os.X_OK):
        env = os.environ.copy()
        env["IMAGE_TAG"] = image
        print(f"Running {script} (IMAGE_TAG={image})")
        result = subprocess.run([str(script)], cwd=str(root), env=env, check=False)
        return int(result.returncode)

    dockerfile = root / "docker" / "Dockerfile.sandbox"
    if not dockerfile.is_file():
        print(f"FAIL cannot find Dockerfile at {dockerfile}")
        return 1
    if shutil.which("docker") is None:
        print("FAIL docker CLI not found")
        return 1
    print(f"Building {image} from {dockerfile}")
    result = subprocess.run(
        ["docker", "build", "-t", image, "-f", str(dockerfile), str(root)],
        check=False,
    )
    return int(result.returncode)


def _add_start_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workdir",
        default="./workspace",
        help="Host workspace origin for holographic clones (default: ./workspace)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8420)
    parser.add_argument("--proxy-port", type=int, default=8888)
    parser.add_argument(
        "--base-image",
        default="agentjail-sandbox:local",
        help="Docker image for sandboxed execution",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error"],
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the dashboard in a browser",
    )
    parser.add_argument(
        "--no-native-notify",
        action="store_true",
        help="Disable macOS/Linux Approve/Deny dialogs for RISKY jobs",
    )


def cmd_start(args: argparse.Namespace) -> int:
    import uvicorn

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    from agent_jail.config import load_config

    cfg = load_config()
    workdir = Path(args.workdir).expanduser().resolve()
    if cfg.workdir and args.workdir == "./workspace":
        workdir = Path(cfg.workdir).expanduser().resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    from agent_jail.dashboard.server import create_app

    url = f"http://{args.host}:{args.port}/"
    notify_url = f"http://{args.host}:{args.port}"
    # Invisible mode: IDE extension handles prompts; skip osascript fatigue
    native_notify = (
        not getattr(args, "no_native_notify", False)
        and not cfg.is_invisible()
    )
    app = create_app(
        workdir=workdir,
        base_image=args.base_image,
        proxy_port=args.proxy_port,
        notify_url=notify_url,
        native_notify=native_notify,
        autopilot=bool(cfg.autopilot),
        mode=cfg.mode,
    )

    print(
        f"AgentJail listening on {url}\n"
        f"  mode:        {cfg.mode} (autopilot={cfg.autopilot})\n"
        f"  dashboard:   {url}\n"
        f"  console:     http://{args.host}:{args.port}/console\n"
        f"  workdir:     {workdir}\n"
        f"  image:       {args.base_image}\n"
        f"  egress proxy: 0.0.0.0:{args.proxy_port}",
        flush=True,
    )

    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception as exc:
            logger.debug("Could not open browser: %s", exc)

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
    )
    return 0


def cmd_shim_install(args: argparse.Namespace) -> int:
    from agent_jail.shim import install_shims, shim_dir

    root = Path(args.root).expanduser() if args.root else None
    meta = install_shims(root)
    print(f"Shims installed under {shim_dir(root)}")
    print(f"  written: {', '.join(meta.get('written') or []) or '(none)'}")
    skipped = meta.get("skipped") or []
    if skipped:
        print(f"  skipped (not on PATH): {', '.join(skipped)}")
    return 0


def cmd_exec_shim(args: argparse.Namespace) -> int:
    from agent_jail.exec_shim import exec_shim_main

    raw = list(args.args or [])
    if raw and raw[0] == "--":
        raw = raw[1:]
    return exec_shim_main(
        args.bin,
        raw,
        timeout=int(args.timeout),
        url=args.url,
    )


def cmd_wrap(args: argparse.Namespace) -> int:
    from agent_jail.wrap import daemon_healthy, prepare_wrap

    target_argv = list(args.argv or [])
    if target_argv and target_argv[0] == "--":
        target_argv = target_argv[1:]
    if not target_argv:
        print("usage: agentjail wrap [--url URL] [--] <command> [args...]", file=sys.stderr)
        return 2

    url = args.url
    if not daemon_healthy(url):
        print(
            f"WARNING: AgentJail daemon not reachable at {url}. "
            "Start it with: agentjail start",
            file=sys.stderr,
        )

    root = Path(args.root).expanduser() if getattr(args, "root", None) else None
    target, env = prepare_wrap(target_argv, url=url, root=root, install=True)
    print(
        f"AgentJail active: intercepting PATH lookups for {target[0]}...",
        flush=True,
    )
    try:
        result = subprocess.run(target, env=env, check=False)
    except FileNotFoundError:
        print(f"FAIL: command not found: {target[0]}", file=sys.stderr)
        return 127
    return int(result.returncode)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentjail",
        description="AgentJail — holographic containment runtime for AI agents",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init", help="Auto-patch Claude / Cursor / Windsurf MCP configs")
    init_p.add_argument(
        "--url",
        default=DEFAULT_AGENTJAIL_URL,
        help=f"AgentJail base URL (default: {DEFAULT_AGENTJAIL_URL})",
    )
    init_p.add_argument(
        "--project",
        action="store_true",
        help="Also patch ./.cursor/mcp.json when the .cursor folder exists",
    )
    init_p.add_argument(
        "--force-project",
        action="store_true",
        help="Create and patch ./.cursor/mcp.json in the current directory",
    )
    init_p.add_argument(
        "--force",
        action="store_true",
        help="Create missing parent dirs / fallback Claude Code config",
    )
    init_p.set_defaults(func=cmd_init)

    setup_p = sub.add_parser("setup", help="Build the sandbox Docker image")
    setup_p.add_argument(
        "--image",
        default="agentjail-sandbox:local",
        help="Image tag to build",
    )
    setup_p.set_defaults(func=cmd_setup)

    start_p = sub.add_parser("start", help="Boot the AgentJail control panel")
    _add_start_flags(start_p)
    start_p.set_defaults(func=cmd_start)

    shim_p = sub.add_parser(
        "shim-install",
        help="Install PATH shims under ~/.agentjail/shims",
    )
    shim_p.add_argument(
        "--root",
        default=None,
        help="Override AgentJail home (default: ~/.agentjail)",
    )
    shim_p.set_defaults(func=cmd_shim_install)

    exec_p = sub.add_parser(
        "exec-shim",
        help="Internal: forward a shimmed binary invocation to the daemon",
    )
    exec_p.add_argument("--bin", required=True, help="Logical binary name (e.g. bash)")
    exec_p.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Sandbox timeout seconds (default: 30)",
    )
    exec_p.add_argument(
        "--url",
        default=DEFAULT_AGENTJAIL_URL,
        help=f"AgentJail base URL (default: {DEFAULT_AGENTJAIL_URL})",
    )
    exec_p.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help="Arguments after -- (passed to the logical binary)",
    )
    exec_p.set_defaults(func=cmd_exec_shim)

    wrap_p = sub.add_parser(
        "wrap",
        help="Launch a CLI/IDE with AgentJail PATH shims prepended",
    )
    wrap_p.add_argument(
        "--url",
        default=DEFAULT_AGENTJAIL_URL,
        help=f"AgentJail base URL (default: {DEFAULT_AGENTJAIL_URL})",
    )
    wrap_p.add_argument(
        "--root",
        default=None,
        help="Override AgentJail home (default: ~/.agentjail)",
    )
    wrap_p.add_argument(
        "argv",
        nargs=argparse.REMAINDER,
        help="Command to wrap, e.g. cursor .  or  claude",
    )
    wrap_p.set_defaults(func=cmd_wrap)

    inv_p = sub.add_parser(
        "invisible",
        help="Opt-in Invisible (background) mode: service + shell PATH + autopilot",
    )
    inv_sub = inv_p.add_subparsers(dest="invisible_action", required=True)
    inv_en = inv_sub.add_parser("enable", help="Enable invisible background mode")
    inv_en.add_argument("--url", default=DEFAULT_AGENTJAIL_URL)
    inv_en.add_argument(
        "--root",
        default=None,
        help="Override AgentJail home (default: ~/.agentjail)",
    )
    inv_en.add_argument(
        "--no-service",
        action="store_true",
        help="Skip launchd/systemd install (config + shell only)",
    )
    inv_en.set_defaults(func=cmd_invisible_enable)
    inv_dis = inv_sub.add_parser("disable", help="Return to interactive front mode")
    inv_dis.add_argument("--root", default=None)
    inv_dis.set_defaults(func=cmd_invisible_disable)
    inv_st = inv_sub.add_parser("status", help="Show invisible / service status")
    inv_st.add_argument("--root", default=None)
    inv_st.set_defaults(func=cmd_invisible_status)

    svc_p = sub.add_parser("service", help="Manage the background AgentJail daemon")
    svc_sub = svc_p.add_subparsers(dest="service_action", required=True)
    for name, help_text, func_name in (
        ("install", "Install and start launchd/systemd unit", "cmd_service_install"),
        ("uninstall", "Stop and remove the service unit", "cmd_service_uninstall"),
        ("status", "Show whether the service is installed/running", "cmd_service_status"),
        ("start", "Start the service", "cmd_service_start"),
        ("stop", "Stop the service", "cmd_service_stop"),
    ):
        sp = svc_sub.add_parser(name, help=help_text)
        sp.add_argument("--root", default=None)
        sp.set_defaults(func=globals()[func_name])

    return parser


def cmd_invisible_enable(args: argparse.Namespace) -> int:
    from agent_jail.config import (
        apply_invisible_defaults,
        load_config,
        save_config,
    )
    from agent_jail.service import install_service
    from agent_jail.shell_integration import enable_shell_integration
    from agent_jail.shim import install_shims, shim_dir

    root = Path(args.root).expanduser() if args.root else None
    cfg = apply_invisible_defaults(load_config(root))
    cfg.url = args.url.rstrip("/")
    cfg.python_executable = str(Path(sys.executable).resolve())
    if not cfg.workdir:
        base = root if root is not None else Path.home() / ".agentjail"
        cfg.workdir = str(base / "workspace")
    if args.no_service:
        cfg.service = False
    save_config(cfg, root)

    meta = install_shims(root)
    print(f"Shims: {', '.join(meta.get('written') or []) or '(none)'}")

    if root is not None:
        written = enable_shell_integration(
            url=cfg.url,
            shim_dir=shim_dir(root),
            rc_paths=[root / ".zshrc", root / ".bashrc"],
        )
    else:
        written = enable_shell_integration(
            url=cfg.url,
            shim_dir=shim_dir(None),
        )
    print(f"Shell integration: {', '.join(str(p) for p in written)}")

    if cfg.service and not args.no_service:
        summary = install_service(
            python=cfg.python_executable,
            workdir=cfg.workdir,
            home=root if root else None,
            load=root is None,
        )
        print(f"Service: {summary}")
    else:
        print("Service: skipped")

    print(
        "\nInvisible mode enabled.\n"
        "  - Autopilot: standard commands run silently in the hologram\n"
        "  - Anomalies: pending for IDE Approve/Block\n"
        "  - Install the status-bar extension from extensions/vscode\n"
        "  - Open a new terminal so PATH picks up shims\n"
        f"  - Console: {cfg.url}/console"
    )
    return 0


def cmd_invisible_disable(args: argparse.Namespace) -> int:
    from agent_jail.config import (
        apply_interactive_defaults,
        load_config,
        save_config,
    )
    from agent_jail.service import uninstall_service
    from agent_jail.shell_integration import disable_shell_integration

    root = Path(args.root).expanduser() if args.root else None
    cfg = apply_interactive_defaults(load_config(root))
    save_config(cfg, root)

    if root is not None:
        modified = disable_shell_integration(
            rc_paths=[root / ".zshrc", root / ".bashrc"]
        )
    else:
        modified = disable_shell_integration()
    print(f"Shell integration removed from: {', '.join(str(p) for p in modified) or '(none)'}")

    summary = uninstall_service(home=root if root else None, unload=root is None)
    print(f"Service: {summary}")
    print("Interactive (front) mode restored.")
    return 0


def cmd_invisible_status(args: argparse.Namespace) -> int:
    from agent_jail.config import load_config
    from agent_jail.service import service_status

    root = Path(args.root).expanduser() if args.root else None
    cfg = load_config(root)
    svc = service_status(home=root if root else None)
    print(json.dumps({"config": cfg.__dict__, "service": svc}, indent=2))
    return 0


def cmd_service_install(args: argparse.Namespace) -> int:
    from agent_jail.config import load_config, save_config
    from agent_jail.service import install_service

    root = Path(args.root).expanduser() if args.root else None
    cfg = load_config(root)
    cfg.service = True
    if not cfg.python_executable:
        cfg.python_executable = str(Path(sys.executable).resolve())
    if not cfg.workdir:
        cfg.workdir = str((root or Path.home() / ".agentjail") / "workspace")
    save_config(cfg, root)
    summary = install_service(
        python=cfg.python_executable,
        workdir=cfg.workdir,
        home=root if root else None,
        load=root is None,
    )
    print(json.dumps(summary, indent=2))
    return 0 if summary.get("path") else 1


def cmd_service_uninstall(args: argparse.Namespace) -> int:
    from agent_jail.config import load_config, save_config
    from agent_jail.service import uninstall_service

    root = Path(args.root).expanduser() if args.root else None
    cfg = load_config(root)
    cfg.service = False
    save_config(cfg, root)
    print(json.dumps(uninstall_service(home=root if root else None, unload=root is None), indent=2))
    return 0


def cmd_service_status(args: argparse.Namespace) -> int:
    from agent_jail.service import service_status

    root = Path(args.root).expanduser() if args.root else None
    print(json.dumps(service_status(home=root if root else None), indent=2))
    return 0


def cmd_service_start(args: argparse.Namespace) -> int:
    from agent_jail.service import install_service, launchd_plist_path, service_status
    import platform as _platform

    root = Path(args.root).expanduser() if args.root else None
    st = service_status(home=root if root else None)
    if not st.get("installed"):
        return cmd_service_install(args)
    if _platform.system() == "Darwin":
        path = launchd_plist_path(root if root else None)
        subprocess.run(["launchctl", "load", str(path)], check=False)
    elif _platform.system() == "Linux":
        subprocess.run(
            ["systemctl", "--user", "start", "agentjail.service"],
            check=False,
        )
    print(json.dumps(service_status(home=root if root else None), indent=2))
    return 0


def cmd_service_stop(args: argparse.Namespace) -> int:
    from agent_jail.service import launchd_plist_path, service_status
    import platform as _platform

    root = Path(args.root).expanduser() if args.root else None
    if _platform.system() == "Darwin":
        path = launchd_plist_path(root if root else None)
        if path.is_file():
            subprocess.run(["launchctl", "unload", str(path)], check=False)
    elif _platform.system() == "Linux":
        subprocess.run(
            ["systemctl", "--user", "stop", "agentjail.service"],
            check=False,
        )
    print(json.dumps(service_status(home=root if root else None), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func: Callable[[argparse.Namespace], int] = args.func
    return func(args)


def start_main(argv: list[str] | None = None) -> int:
    """Backward-compatible entry used by ``run.py`` (start only)."""
    parser = argparse.ArgumentParser(description="Run the AgentJail local sandboxing proxy")
    _add_start_flags(parser)
    args = parser.parse_args(argv)
    return cmd_start(args)


if __name__ == "__main__":
    sys.exit(main())
