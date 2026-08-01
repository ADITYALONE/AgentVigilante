# Contributing to AgentVigilante

Thanks for helping build a saner perimeter for AI coding agents.

AgentVigilante is a security tool. A change that makes the product friendlier but
quietly widens the blast radius is a regression, so most of this guide is about
proving that containment still holds.

## Ground rules

1. **Never weaken a guardrail silently.** If a change moves a command from
   CRITICAL to RISKY (or RISKY to autopilot), say so in the PR description and
   add a test that pins the new behavior.
2. **Interactive mode stays the default.** Invisible mode, autopilot, and shell
   integration are opt-in. Do not enable them implicitly.
3. **No new bypasses.** Anything that sets `AGENTVIGILANTE_BYPASS`, skips the
   analyzer, or executes outside the hologram needs an explicit justification.
4. **Document residual risk.** If your feature can be circumvented (for example
   absolute `/bin/zsh` defeating PATH shims), write it down rather than implying
   it is airtight.

## Local setup

```bash
git clone https://github.com/ADITYALONE/AgentVigilante.git
cd AgentVigilante

python3 -m venv .venv
source .venv/bin/activate
pip install -e .

agentvigilante setup                 # builds agentvigilante-sandbox:local (needs Docker)

cd web && npm install && npm run build && cd ..
agentvigilante start                 # http://127.0.0.1:8420
```

`web/dist` is gitignored, so build the UI at least once or the server falls back
to the legacy Jinja dashboard.

## Tests

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
```

The suite is offline and does not require Docker: sandbox execution is mocked or
avoided. Tests that spin up the FastAPI app must pass a unique `proxy_port` so
parallel apps do not collide on the egress port.

Add tests alongside the area you touch:

| Area | Test file |
|------|-----------|
| Risk classification | `tests/test_ciber_hardening.py` |
| Autopilot allowlist | `tests/test_autopilot.py` |
| PATH shims / wrap | `tests/test_shim_install.py`, `tests/test_wrap_env.py` |
| Shim client behavior | `tests/test_exec_shim.py` |
| Config / service / shell rc | `tests/test_config.py`, `tests/test_service_plist.py`, `tests/test_shell_integration.py` |
| HTTP surface | `tests/test_status_api.py`, `tests/test_deny_feedback.py` |

## Project layout

| Path | What lives there |
|------|------------------|
| `agent_vigilante/core/` | Analyzer, hologram, sandbox, egress proxy, HTTP routes |
| `agent_vigilante/cli.py` | `init`, `setup`, `start`, `wrap`, `invisible`, `service` |
| `agent_vigilante/shim.py`, `exec_shim.py`, `wrap.py` | PATH interception |
| `agent_vigilante/notify.py` | Native Approve/Deny dialogs |
| `web/` | Vite + React console and landing page |
| `extensions/vscode/` | Cursor / VS Code status bar extension |

## Style

- Python: type hints on public functions, `from __future__ import annotations`,
  imports at the top of the module.
- Match the surrounding code. Comments explain constraints, not narration.
- TypeScript: exhaustive `switch` over unions with a `never` default.

## Pull requests

1. Branch from `main`.
2. Keep the diff focused; split unrelated refactors.
3. Run the test suite and mention the result in the PR.
4. Describe the security impact explicitly, even when it is "none".

## Reporting a vulnerability

Do not open a public issue for an escape or bypass. Email
**adityapunjani9@gmail.com** with reproduction steps and the version you tested.
