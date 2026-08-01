"""Pre-flight bash AST risk classification for agent commands."""

from __future__ import annotations

import logging
from enum import IntEnum
from typing import Any

import bashlex

logger = logging.getLogger(__name__)

_INTERPRETERS = {"python", "python3", "node", "bash", "sh", "zsh", "ruby", "perl"}
_SCRIPT_SUFFIXES = (".py", ".sh", ".js", ".mjs", ".cjs", ".rb", ".pl")


class RiskLevel(IntEnum):
    SAFE = 1
    RISKY = 2
    CRITICAL = 3


class CommandAnalyzer:
    """Classify shell commands via bashlex AST inspection."""

    def __init__(self) -> None:
        self.safe_commands = {
            "ls",
            "pwd",
            "whoami",
            "cat",
            "echo",
            "grep",
            "find",
            "head",
            "tail",
            "pytest",
            "git",
            "wc",
            "true",
            "false",
            "test",
            "[",
        }
        self.risky_commands = {
            "pip",
            "pip3",
            "npm",
            "npx",
            "yarn",
            "pnpm",
            "cargo",
            "touch",
            "mkdir",
            "mv",
            "cp",
            "ln",
            "python",
            "python3",
            "node",
            "sed",
            "tee",
            "install",
        }
        self.critical_commands = {
            "rm",
            "chmod",
            "chown",
            "curl",
            "wget",
            "su",
            "sudo",
            "nc",
            "ncat",
            "netcat",
            "socat",
            "dig",
            "nslookup",
            "host",
            "drill",
            "nmap",
            "telnet",
            "ssh",
            "scp",
            "dd",
            "mkfs",
            "shutdown",
            "reboot",
            "kill",
            "killall",
        }
        self.sensitive_paths = {
            ".env",
            ".aws",
            ".ssh",
            "id_rsa",
            "id_ed25519",
            "/etc/passwd",
            "/etc/shadow",
        }
        self.git_write_subcommands = {
            "push",
            "commit",
            "reset",
            "clean",
            "rebase",
            "checkout",
            "merge",
            "add",
        }

    def _extract_words(self, node: Any) -> list[str]:
        words: list[str] = []
        if hasattr(node, "word") and isinstance(node.word, str):
            words.append(node.word)
        if hasattr(node, "parts"):
            for part in node.parts:
                words.extend(self._extract_words(part))
        if hasattr(node, "list"):
            for part in node.list:
                words.extend(self._extract_words(part))
        if hasattr(node, "commands"):
            for part in node.commands:
                words.extend(self._extract_words(part))
        return words

    def _has_redirections(self, node: Any) -> bool:
        # bashlex represents I/O redirects as child nodes with kind="redirect".
        if getattr(node, "kind", None) == "redirect":
            return True
        if getattr(node, "redirects", None):
            return True
        for attr in ("parts", "list", "commands"):
            children = getattr(node, attr, None)
            if not children:
                continue
            for child in children:
                if self._has_redirections(child):
                    return True
        return False

    def _critical_inline_patterns(self, command: str) -> str | None:
        stripped = "".join(command.split())
        if ":(){" in stripped and ":|:&" in stripped:
            return "Blocked fork-bomb pattern in command string."
        if "if=/dev/zero" in command or "of=/dev/zero" in command:
            return "Blocked destructive dd /dev/zero pattern."
        return None

    def analyze(self, command: str) -> tuple[RiskLevel, str]:
        """Return ``(risk_level, reason)`` for a shell command string."""
        inline = self._critical_inline_patterns(command)
        if inline:
            return RiskLevel.CRITICAL, inline

        try:
            ast_nodes = bashlex.parse(command)
        except Exception as exc:
            return RiskLevel.RISKY, f"Failed to parse shell syntax: {exc}"

        highest = RiskLevel.SAFE
        reasons: list[str] = []

        for node in ast_nodes:
            words = self._extract_words(node)
            if not words:
                continue

            base_cmd = words[0].split("/")[-1]

            if base_cmd in self.critical_commands:
                return (
                    RiskLevel.CRITICAL,
                    f"Blocked destructive base command: '{base_cmd}'",
                )

            for word in words:
                for path in self.sensitive_paths:
                    if path in word:
                        return (
                            RiskLevel.CRITICAL,
                            f"Blocked access to sensitive path: '{path}'",
                        )

            if base_cmd in self.risky_commands:
                highest = max(highest, RiskLevel.RISKY)
                reasons.append(f"State-modifying command detected: '{base_cmd}'")

            if base_cmd in _INTERPRETERS:
                for word in words[1:]:
                    lower = word.lower()
                    if any(lower.endswith(suf) for suf in _SCRIPT_SUFFIXES):
                        highest = max(highest, RiskLevel.RISKY)
                        reasons.append(
                            "Interpreter runs a script file; nested payloads "
                            "are not inspected by the shell AST."
                        )
                        break

            if base_cmd == "git" and len(words) > 1:
                sub = words[1]
                if sub in self.git_write_subcommands:
                    highest = max(highest, RiskLevel.RISKY)
                    reasons.append(f"Git write operation detected: 'git {sub}'")

            if self._has_redirections(node):
                highest = max(highest, RiskLevel.RISKY)
                reasons.append("I/O redirection detected (writing to file).")

            if highest == RiskLevel.SAFE and base_cmd not in self.safe_commands:
                highest = RiskLevel.RISKY
                reasons.append(
                    f"Unrecognized command '{base_cmd}', defaulting to human review."
                )

        reason = (
            " | ".join(reasons)
            if reasons
            else "Command is recognized as read-only and safe."
        )
        logger.info("Analyzed command risk=%s reason=%s", highest.name, reason)
        return highest, reason
