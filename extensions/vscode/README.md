# AgentVigilante IDE extension

Status bar + Approve/Block prompts for Cursor / VS Code when using **Invisible mode**.

## Install (dev)

1. Open this folder in Cursor/VS Code, or:

```bash
# From repo root — package as VSIX (optional; needs @vscode/vsce)
cd extensions/vscode
npx --yes @vscode/vsce package --allow-missing-repository
cursor --install-extension agentvigilante-0.1.0.vsix
# or: code --install-extension agentvigilante-0.1.0.vsix
```

2. Or **Extensions → … → Install from Location…** and pick `extensions/vscode`.

3. Ensure the daemon is running (`agentvigilante invisible enable` or `agentvigilante start`).

## Settings

| Setting | Default |
|---------|---------|
| `agentvigilante.url` | `http://127.0.0.1:8420` |
| `agentvigilante.pollIntervalMs` | `2000` |
