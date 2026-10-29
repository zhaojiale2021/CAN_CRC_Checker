"""Trace reader ASC compatibility tests.

CANoe 7.x writes CANFD lines with the id before the direction
(``CANFD <ch> <id> <dir> <brs> <esi> [<d>] <dlc> <len> <data>``) while
python-can only expects ``CANFD <ch> <dir> <id> <brs> <esi> <dlc> <len> <data>``;
the DLC code is a decimal 0-15 code even in hex-base logs. The fixture below
reproduces the header and line ordering of a CANoe 7.0.0 log.
"""

import os
import tempfile
import unittest

from crc_checker.trace.reader import TraceReader

CANOE7_ASC = """date Mon Oct 12 06:42:09 PM 2026
base hex timestamps absolute
// version 7.0.0
0.000000 CANFD 1 1d3 Rx 1 0 d 8 8 78 88 00 00 00 00 0c e6
0.001340 2 300 Rx d 8 be 38 48 bf a0 0a 03 55
0.004238 CANFD 1 1e3 Rx 1 0 d 13 32 {data32}
"""

FD_DATA_32 = " ".join(["00"] * 32)


class TestCanoe7Asc(unittest.TestCase):
    """The _CanoeAscReader fallback for CANoe 7.x FD lines."""

    def _read(self, content):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".asc", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(content)
            path = tmp.name
        try:
            with TraceReader(path) as reader:
                return list(reader.frames())
        finally:
            os.unlink(path)

    def test_canoe7_fd_line(self):
        """FD line with id before direction: id/flags/dlc all land correctly."""
        frames = self._read(CANOE7_ASC.format(data32=FD_DATA_32))
        fd = [f for f in frames if f.is_fd]
        first = fd[0]
        self.assertEqual(first.arbitration_id, 0x1D3)
        self.assertEqual(first.dlc, 8)
        self.assertEqual(first.data.hex(), "7888000000000ce6")
        self.assertEqual(first.channel, 0)  # channel 1 → 0-based

    def test_fd_dlc_code_decimal(self):
        """DLC code 13 → 32 bytes even when the log base is hex ('13' != 0x13)."""
        frames = self._read(CANOE7_ASC.format(data32=FD_DATA_32))
        big = [f for f in frames if f.dlc == 32]
        self.assertEqual(len(big), 1)
        self.assertEqual(big[0].arbitration_id, 0x1E3)
        self.assertEqual(len(big[0].data), 32)

    def test_classic_line(self):
        """Classic CAN line keeps working through python-can's own parser."""
        frames = self._read(CANOE7_ASC.format(data32=FD_DATA_32))
        classic = [f for f in frames if not f.is_fd]
        self.assertEqual(len(classic), 1)
        self.assertEqual(classic[0].arbitration_id, 0x300)
        self.assertEqual(classic[0].channel, 1)  # channel 2 → 0-based
        self.assertEqual(classic[0].data.hex(), "be3848bfa00a0355")


if __name__ == "__main__":
    unittest.main()
