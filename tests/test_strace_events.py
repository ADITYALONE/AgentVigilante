"""Kernel event parser tests."""

from __future__ import annotations

import unittest

from agent_jail.core.strace_profile import counts_from_events, parse_strace_events

SAMPLE = """
1234 12:00:00.000001 openat(AT_FDCWD, "/workspace/foo.py", O_RDONLY) = 3
1234 12:00:00.000100 connect(4, {sa_family=AF_INET, sin_port=htons(443), sin_addr=inet_addr("1.2.3.4")}, 16) = 0
1235 12:00:00.000200 clone(child_stack=NULL, flags=CLONE_CHILD_CLEARTID) = 1236
1234 12:00:00.000300 execve("/bin/ls", ["ls"], 0x7ffe) = 0
1234 12:00:00.000400 unlink("/workspace/tmp.dat") = 0
"""


class StraceEventTests(unittest.TestCase):
    def test_parse_openat_connect_clone(self) -> None:
        events = parse_strace_events(SAMPLE)
        self.assertGreaterEqual(len(events), 4)
        openat = next(e for e in events if e["syscall"] == "openat")
        self.assertEqual(openat["category"], "file")
        self.assertEqual(openat["path"], "/workspace/foo.py")
        conn = next(e for e in events if e["syscall"] == "connect")
        self.assertEqual(conn["category"], "net")
        self.assertEqual(conn["endpoint"], "1.2.3.4:443")
        clone = next(e for e in events if e["syscall"] == "clone")
        self.assertEqual(clone["category"], "process")

    def test_counts_from_events(self) -> None:
        events = parse_strace_events(SAMPLE)
        stats = counts_from_events(events)
        names = {s["syscall"] for s in stats}
        self.assertIn("openat", names)
        self.assertIn("connect", names)


if __name__ == "__main__":
    unittest.main()
