#!/usr/bin/env python3
"""Backward-compatible entrypoint — prefer ``agentjail start``."""

from __future__ import annotations

import sys

from agent_jail.cli import start_main

if __name__ == "__main__":
    sys.exit(start_main())
