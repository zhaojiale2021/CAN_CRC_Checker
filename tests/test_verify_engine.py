"""Tests for the DLC gate in VerifyEngine: a frame whose length differs from
the DBC definition is a same-ID message from another bus (mixed traces) and
must be skipped instead of verified with the wrong protection config.

Regression for the radar-tool false CRC errors: a 5-channel bench trace
carried vehicle-CANFD 64B P05 frames colliding with 30B radar P01 message
IDs; the radar-only DBC got assigned to every channel and the CANFD frames
all failed the P01 check.
"""

from __future__ import annotations

from crc_checker.dbc.models import DBCProtectionMap, MessageProtection, SignalInfo
from crc_checker.trace.reader import CanFrame
from crc_checker.verify.engine import VerifyEngine


def _build_map(dlc: int) -> DBCProtectionMap:
    """One message with a CRC group whose DBC-defined DLC is ``dlc``."""
    pm = DBCProtectionMap()
    prot = MessageProtection(frame_id=0x160, frame_name="BCS_2_A", dlc=dlc)
    prot.pair_suffix = "BCS_2"
    prot.checksum_signal = SignalInfo(name="BCS_2_CRC", start_bit=0, length=8)
    pm.messages = {0x160: [prot]}
    return pm


def _frame(dlc: int, data: bytes | None = None, channel: int = 0) -> CanFrame:
    return CanFrame(timestamp=1.0, arbitration_id=0x160, dlc=dlc,
                    data=data or bytes(dlc), channel=channel)


class _Reader:  # pylint: disable=too-few-public-methods
    """Minimal TraceReader stand-in yielding preset frames."""

    def __init__(self, frames):
        self._frames = frames
        self.file_path = "synthetic.blf"

    def frames(self):
        """Yield the preset frames (TraceReader interface)."""
        yield from self._frames


class TestDlcGate:
    """DLC gate: same-ID foreign frames (different length) must be skipped."""

    def test_dlc_mismatch_skipped(self):
        """64B frames are foreign (vehicle CANFD) — no verdicts, counted as skipped."""
        engine = VerifyEngine(_build_map(dlc=32), algorithms=[])
        reader = _Reader([_frame(32), _frame(64), _frame(64)])
        report = engine.run(reader)
        assert not report.verdicts
        assert report.total_frames == 3
        assert report.dlc_mismatch_skipped == 2

    def test_dlc_match_verified(self):
        """Matching-dlc frames still reach the algorithms (no skip counted)."""
        engine = VerifyEngine(_build_map(dlc=32), algorithms=[])
        reader = _Reader([_frame(32)])
        report = engine.run(reader)
        # No algorithms configured → no verdicts, but the group was reached
        assert report.dlc_mismatch_skipped == 0

    def test_unknown_dlc_not_gated(self):
        """Groups with DLC 0 (unknown) verify frames of any length."""
        engine = VerifyEngine(_build_map(dlc=0), algorithms=[])
        reader = _Reader([_frame(8), _frame(64)])
        report = engine.run(reader)
        assert report.dlc_mismatch_skipped == 0

    def test_partial_match_keeps_matching_group(self):
        """Multi-group frames verify with the matching group only."""
        pm = DBCProtectionMap()
        p_radar = MessageProtection(frame_id=0x160, frame_name="BCS_2_A", dlc=32)
        p_radar.pair_suffix = "BCS_2"
        p_radar.checksum_signal = SignalInfo(name="BCS_2_CRC", start_bit=0, length=8)
        p_other = MessageProtection(frame_id=0x160, frame_name="BCS_2_C", dlc=64)
        p_other.pair_suffix = "BCS_2C"
        p_other.checksum_signal = SignalInfo(name="BCS_2C_CRC", start_bit=0, length=8)
        pm.messages = {0x160: [p_radar, p_other]}
        engine = VerifyEngine(pm, algorithms=[])
        reader = _Reader([_frame(64)])
        report = engine.run(reader)
        assert report.dlc_mismatch_skipped == 0

    def test_run_stream_applies_gate(self):
        """run_stream filters the same way (CLI/web share run(); TUI uses run_stream)."""
        engine = VerifyEngine(_build_map(dlc=32), algorithms=[])
        reader = _Reader([_frame(64), _frame(32)])
        assert not list(engine.run_stream(reader))
