"""strace -c parser unit tests."""

from __future__ import annotations

import unittest

from agent_vigilante.core.strace_profile import parse_strace_c

SAMPLE = """
% time     seconds  usecs/call     calls    errors syscall
------ ----------- ----------- --------- --------- ----------------
 45.00    0.000900         900         2           openat
 30.00    0.000600         100         6           read
 15.00    0.000300          50         6           write
 10.00    0.000200         200         1         1 connect
------ ----------- ----------- --------- --------- ----------------
100.00    0.002000                    15         1 total
"""


class StraceProfileTests(unittest.TestCase):
    def test_parse_sorted_by_calls(self) -> None:
        stats = parse_strace_c(SAMPLE)
        self.assertGreaterEqual(len(stats), 3)
        self.assertEqual(stats[0]["syscall"], "read")
        self.assertEqual(stats[0]["calls"], 6)
        connect = next(s for s in stats if s["syscall"] == "connect")
        self.assertEqual(connect["errors"], 1)
        self.assertAlmostEqual(connect["time_pct"], 10.0)

    def test_empty_input(self) -> None:
        self.assertEqual(parse_strace_c(""), [])


if __name__ == "__main__":
    unittest.main()
