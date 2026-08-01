#!/usr/bin/env node
"use strict";

const { spawnSync } = require("child_process");

const args = process.argv.slice(2);
const candidates = process.platform === "win32"
  ? ["py", "python", "python3"]
  : ["python3", "python"];

let lastError = null;
for (const bin of candidates) {
  const result = spawnSync(bin, ["-m", "agent_vigilante.cli", ...args], {
    stdio: "inherit",
    env: process.env,
  });
  if (result.error && result.error.code === "ENOENT") {
    lastError = result.error;
    continue;
  }
  if (result.status === 1 && result.stderr) {
    // module missing often exits non-zero with ImportError
  }
  if (result.status === 0) {
    process.exit(0);
  }
  // Non-ENOENT: Python ran; forward exit code (e.g. bad args or missing package)
  if (result.status !== null && result.status !== undefined) {
    if (result.status !== 0) {
      const probe = spawnSync(bin, ["-c", "import agent_vigilante.cli"], {
        encoding: "utf8",
      });
      if (probe.status !== 0) {
        console.error(
          "AgentVigilante Python package not found.\n" +
            "Install it first:\n" +
            "  pip install agentvigilante\n" +
            "  # or from a checkout: pip install -e .\n",
        );
      }
    }
    process.exit(result.status);
  }
  lastError = result.error;
}

console.error(
  "Could not find a Python interpreter (tried: " +
    candidates.join(", ") +
    ").\nInstall Python 3.11+ and: pip install agentvigilante",
);
if (lastError) {
  console.error(String(lastError));
}
process.exit(1);
