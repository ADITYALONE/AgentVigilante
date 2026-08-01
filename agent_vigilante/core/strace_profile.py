"""Parse ``strace -c`` summaries and detailed ``strace -f`` event logs."""

from __future__ import annotations

import re
from collections import Counter
from typing import Literal, TypedDict


class SyscallStat(TypedDict):
    syscall: str
    calls: int
    errors: int
    time_pct: float


class KernelEvent(TypedDict):
    ts: str
    pid: str
    syscall: str
    args: str
    path: str | None
    endpoint: str | None
    ret: str | None
    category: Literal["file", "net", "process", "other"]


# Typical strace -c line
_ROW = re.compile(
    r"^\s*"
    r"(?P<time_pct>\d+(?:\.\d+)?)\s+"
    r"(?P<seconds>\d+(?:\.\d+)?)\s+"
    r"(?P<usecs_per_call>\d+(?:\.\d+)?)\s+"
    r"(?P<calls>\d+)\s+"
    r"(?:(?P<errors>\d+)\s+)?"
    r"(?P<syscall>[a-zA-Z0-9_]+)\s*$"
)

_ROW_ALT = re.compile(
    r"^\s*"
    r"(?P<time_pct>\d+(?:\.\d+)?)\s+"
    r"(?P<seconds>\d+(?:\.\d+)?)\s+"
    r"(?P<calls>\d+)\s+"
    r"(?:(?P<errors>\d+)\s+)?"
    r"(?P<syscall>[a-zA-Z0-9_]+)\s*$"
)

# 12:34:56.789012 openat(AT_FDCWD, "foo", O_RDONLY) = 3
# 12345 12:34:56.789012 connect(4, {sa_family=AF_INET, sin_port=htons(443), sin_addr=inet_addr("1.2.3.4")}, 16) = 0
_EVENT = re.compile(
    r"^(?:(?P<pid>\d+)\s+)?"
    r"(?P<ts>\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+"
    r"(?P<syscall>[a-zA-Z0-9_]+)\((?P<args>.*)\)\s*=\s*(?P<ret>.+?)\s*$"
)

_PATH_IN_ARGS = re.compile(r'"(?P<path>(?:\\.|[^"\\])*)"')
_INET = re.compile(
    r'sin_port=htons\((?P<port>\d+)\).*?inet_addr\("(?P<ip>[^"]+)"\)',
    re.DOTALL,
)
_INET6_OR_HOST = re.compile(r'inet_pton\(AF_INET6,\s*"(?P<ip6>[^"]+)"')

_FILE_CALLS = {
    "open",
    "openat",
    "unlink",
    "unlinkat",
    "rename",
    "renameat",
    "renameat2",
    "write",
    "creat",
}
_NET_CALLS = {"connect", "socket", "bind", "accept", "sendto", "recvfrom"}
_PROC_CALLS = {"clone", "clone3", "fork", "vfork", "execve", "execveat"}


def parse_strace_c(text: str, *, limit: int = 20) -> list[SyscallStat]:
    """Parse ``strace -c`` output into stats sorted by call count (desc)."""
    stats: list[SyscallStat] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("%") or line.startswith("------"):
            continue
        if line.lower().startswith("total"):
            continue
        match = _ROW.match(line) or _ROW_ALT.match(line)
        if not match:
            continue
        syscall = match.group("syscall")
        if syscall.lower() == "total":
            continue
        errors_raw = match.groupdict().get("errors")
        stats.append(
            SyscallStat(
                syscall=syscall,
                calls=int(match.group("calls")),
                errors=int(errors_raw) if errors_raw else 0,
                time_pct=float(match.group("time_pct")),
            )
        )
    stats.sort(key=lambda s: s["calls"], reverse=True)
    return stats[:limit]


def _category(syscall: str) -> Literal["file", "net", "process", "other"]:
    if syscall in _FILE_CALLS:
        return "file"
    if syscall in _NET_CALLS:
        return "net"
    if syscall in _PROC_CALLS:
        return "process"
    return "other"


def _extract_path(syscall: str, args: str) -> str | None:
    if syscall not in _FILE_CALLS and syscall not in {"execve", "execveat"}:
        # Still try for execve
        if syscall not in {"execve", "execveat"}:
            return None
    matches = list(_PATH_IN_ARGS.finditer(args))
    if not matches:
        return None
    # openat: first string is often the path (after AT_FDCWD)
    # execve: first string is pathname
    raw = matches[0].group("path")
    return raw.encode("utf-8").decode("unicode_escape", errors="replace")


def _extract_endpoint(syscall: str, args: str) -> str | None:
    if syscall not in _NET_CALLS:
        return None
    m = _INET.search(args)
    if m:
        return f"{m.group('ip')}:{m.group('port')}"
    m6 = _INET6_OR_HOST.search(args)
    if m6:
        return m6.group("ip6")
    return None


def parse_strace_events(text: str, *, limit: int = 500) -> list[KernelEvent]:
    """Parse detailed ``strace -f -tt`` lines into structured kernel events."""
    events: list[KernelEvent] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or "+++ exited" in line or "--- SIG" in line:
            continue
        # unfinished / resumed lines
        if "<unfinished" in line or "resumed>" in line:
            continue
        match = _EVENT.match(line)
        if not match:
            continue
        syscall = match.group("syscall")
        args = match.group("args")
        events.append(
            KernelEvent(
                ts=match.group("ts") or "",
                pid=match.group("pid") or "",
                syscall=syscall,
                args=args[:240],
                path=_extract_path(syscall, args),
                endpoint=_extract_endpoint(syscall, args),
                ret=match.group("ret").strip(),
                category=_category(syscall),
            )
        )
    if len(events) > limit:
        events = events[-limit:]
    return events


def counts_from_events(events: list[KernelEvent], *, limit: int = 20) -> list[SyscallStat]:
    """Derive a crude syscall_profile from event counts (no timing)."""
    counter: Counter[str] = Counter(e["syscall"] for e in events)
    err_counter: Counter[str] = Counter(
        e["syscall"]
        for e in events
        if (e.get("ret") or "").startswith("-")
    )
    total = sum(counter.values()) or 1
    stats: list[SyscallStat] = []
    for syscall, calls in counter.most_common(limit):
        stats.append(
            SyscallStat(
                syscall=syscall,
                calls=calls,
                errors=err_counter.get(syscall, 0),
                time_pct=round(100.0 * calls / total, 2),
            )
        )
    return stats
