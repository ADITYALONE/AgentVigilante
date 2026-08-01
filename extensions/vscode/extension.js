/**
 * AgentVigilante VS Code / Cursor extension — status bar + Approve/Block prompts.
 * Plain JS (no build step). Compatible with Cursor and VS Code.
 */
const vscode = require("vscode");

/** @type {vscode.StatusBarItem} */
let statusBar;
/** @type {NodeJS.Timeout | undefined} */
let pollTimer;
/** @type {Set<string>} */
const promptedJobs = new Set();
/** @type {Set<string>} */
const toastedBlocks = new Set();

function baseUrl() {
  return (
    vscode.workspace.getConfiguration("agentvigilante").get("url") ||
    "http://127.0.0.1:8420"
  ).replace(/\/$/, "");
}

async function fetchJson(path) {
  const url = `${baseUrl()}${path}`;
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`);
  }
  return resp.json();
}

async function postJson(path, body) {
  const url = `${baseUrl()}${path}`;
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`);
  }
  return resp.json();
}

function truncate(s, n) {
  const t = String(s || "").replace(/\s+/g, " ").trim();
  return t.length <= n ? t : t.slice(0, n - 1) + "…";
}

async function promptPending(job) {
  if (!job || !job.id || promptedJobs.has(job.id)) {
    return;
  }
  promptedJobs.add(job.id);
  const msg = `AgentVigilante anomaly: ${truncate(job.command, 100)} (${job.risk_reason || "review"})`;
  const pick = await vscode.window.showWarningMessage(
    msg,
    "Approve",
    "Block",
    "Open Console"
  );
  try {
    if (pick === "Approve") {
      await postJson(`/v1/commands/${job.id}/approve`);
      vscode.window.setStatusBarMessage("AgentVigilante: approved", 3000);
    } else if (pick === "Block") {
      await postJson(`/v1/commands/${job.id}/deny`, {
        reason: "Denied via IDE extension",
        revert: false,
      });
      vscode.window.setStatusBarMessage("AgentVigilante: blocked", 3000);
    } else if (pick === "Open Console") {
      vscode.env.openExternal(vscode.Uri.parse(`${baseUrl()}/console`));
    }
  } catch (err) {
    vscode.window.showErrorMessage(`AgentVigilante action failed: ${err.message || err}`);
  }
}

async function toastBlocked(ev) {
  const key = ev.job_id || `${ev.at}:${ev.command}`;
  if (toastedBlocks.has(key)) {
    return;
  }
  toastedBlocks.add(key);
  await vscode.window.showErrorMessage(
    `AgentVigilante blocked: ${truncate(ev.command, 100)} — ${truncate(ev.risk_reason, 80)}`,
    "Open Console"
  ).then((pick) => {
    if (pick === "Open Console") {
      vscode.env.openExternal(vscode.Uri.parse(`${baseUrl()}/console`));
    }
  });
}

async function refresh() {
  try {
    const status = await fetchJson("/v1/status");
    const pending = await fetchJson("/v1/pending");
    const n = status.pending_count ?? (pending && pending.length) || 0;
    const mode = status.mode || "interactive";
    statusBar.text = `$(shield) AgentVigilante: Active (${n} pending)`;
    statusBar.tooltip = `mode=${mode} autopilot=${status.autopilot} — click to open console`;
    statusBar.backgroundColor =
      n > 0
        ? new vscode.ThemeColor("statusBarItem.warningBackground")
        : undefined;

    for (const job of pending || []) {
      await promptPending(job);
    }

    try {
      const events = await fetchJson("/v1/events/recent?limit=10");
      for (const ev of events || []) {
        if (ev.type === "blocked") {
          await toastBlocked(ev);
        }
      }
    } catch {
      /* older daemon without events endpoint */
    }
  } catch {
    statusBar.text = "$(shield) AgentVigilante: Unreachable";
    statusBar.tooltip = `Cannot reach ${baseUrl()} — run agentvigilante start or invisible enable`;
    statusBar.backgroundColor = new vscode.ThemeColor(
      "statusBarItem.errorBackground"
    );
  }
}

/**
 * @param {vscode.ExtensionContext} context
 */
function activate(context) {
  statusBar = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Left,
    100
  );
  statusBar.command = "agentvigilante.openConsole";
  statusBar.text = "$(shield) AgentVigilante: …";
  statusBar.show();
  context.subscriptions.push(statusBar);

  context.subscriptions.push(
    vscode.commands.registerCommand("agentvigilante.openConsole", () => {
      vscode.env.openExternal(vscode.Uri.parse(`${baseUrl()}/console`));
    })
  );
  context.subscriptions.push(
    vscode.commands.registerCommand("agentvigilante.refresh", () => refresh())
  );

  const ms =
    vscode.workspace.getConfiguration("agentvigilante").get("pollIntervalMs") || 2000;
  pollTimer = setInterval(() => {
    refresh().catch(() => {});
  }, ms);
  context.subscriptions.push({
    dispose: () => {
      if (pollTimer) {
        clearInterval(pollTimer);
      }
    },
  });
  refresh().catch(() => {});
}

function deactivate() {
  if (pollTimer) {
    clearInterval(pollTimer);
  }
}

module.exports = { activate, deactivate };
