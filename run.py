#!/usr/bin/env python3
"""Backward-compatible entrypoint — prefer ``agentvigilante start``."""

from __future__ import annotations

import sys

from agent_vigilante.cli import start_main

if __name__ == "__main__":
    sys.exit(start_main())
