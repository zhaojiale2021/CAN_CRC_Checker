"""Verification data models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VerifyVerdict:
    """Verification result for a single protection algorithm on a single frame."""
    frame_id: int
    timestamp: float
    algorithm: str                # 'crc', 'rolling_counter'
    signal_name: str              # e.g. "Checksum_ACC1"
    expected_value: int
    actual_value: int
    is_pass: bool
    detail: str = ""
    # Signal position info for hex-dump highlighting (set by verifier)
    start_bit: int = 0
    length: int = 0
    byte_order: str = "little_endian"
    dataid: int | None = None       # DataID for this protection group (from E2E config)

    def __str__(self) -> str:
        status = "PASS" if self.is_pass else "FAIL"
        return (f"[{status}] ID=0x{self.frame_id:03X} @ {self.timestamp:.6f}s "
                f"{self.signal_name}: expected=0x{self.expected_value:02X} "
                f"actual=0x{self.actual_value:02X} {self.detail}")


@dataclass
class VerifyReport:
    """Aggregated verification report for a complete trace run."""
    verdicts: list[VerifyVerdict] = field(default_factory=list)
    dbc_path: str = ""                              # backward compat: display string
    dbc_paths: list[str] = field(default_factory=list)  # all DBC source files
    trace_path: str = ""
    total_frames: int = 0
    total_verdicts: int = 0
    _frame_data: dict = field(default_factory=dict)  # (timestamp, frame_id) -> bytes
    _frame_names: dict = field(default_factory=dict)  # frame_id -> frame_name
    _frame_channels: dict = field(default_factory=dict)  # (timestamp, frame_id) -> channel
    _frame_dbc_sources: dict = field(default_factory=dict)  # frame_id -> dbc_source

    def add_frame_data(self, timestamp: float, frame_id: int, data: bytes,
                       channel: int = 0):
        """Store raw frame data and channel for hex-dump display."""
        self._frame_data[(timestamp, frame_id)] = data
        if channel:
            self._frame_channels[(timestamp, frame_id)] = channel

    def get_frame_data(self, timestamp: float, frame_id: int) -> bytes | None:
        return self._frame_data.get((timestamp, frame_id))

    def get_frame_channel(self, timestamp: float, frame_id: int) -> int:
        return self._frame_channels.get((timestamp, frame_id), 0)

    def set_frame_dbc_source(self, frame_id: int, dbc_source: str):
        """Store which DBC file a frame's protection group came from."""
        self._frame_dbc_sources[frame_id] = dbc_source

    def get_frame_dbc_source(self, frame_id: int) -> str:
        return self._frame_dbc_sources.get(frame_id, "")

    def set_frame_name(self, frame_id: int, name: str):
        """Store frame name from DBC."""
        self._frame_names[frame_id] = name

    def get_frame_name(self, frame_id: int) -> str:
        return self._frame_names.get(frame_id, "")

    @property
    def passed(self) -> list[VerifyVerdict]:
        return [v for v in self.verdicts if v.is_pass]

    @property
    def failed(self) -> list[VerifyVerdict]:
        return [v for v in self.verdicts if not v.is_pass]

    @property
    def pass_count(self) -> int:
        return len(self.passed)

    @property
    def fail_count(self) -> int:
        return len(self.failed)

    @property
    def pass_rate(self) -> float:
        if not self.verdicts:
            return 1.0
        return self.pass_count / len(self.verdicts)

    def summary(self) -> dict:
        """Generate a summary grouped by frame_id and signal."""
        # Count failures per frame_id
        frame_stats: dict[int, dict] = {}
        for v in self.verdicts:
            fid = v.frame_id
            if fid not in frame_stats:
                frame_stats[fid] = {"total": 0, "pass": 0, "fail": 0, "signals": {}}
            frame_stats[fid]["total"] += 1
            if v.is_pass:
                frame_stats[fid]["pass"] += 1
            else:
                frame_stats[fid]["fail"] += 1

        return {
            "total_frames": self.total_frames,
            "total_verdicts": self.total_verdicts,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "pass_rate": f"{self.pass_rate:.2%}",
            "frame_stats": frame_stats,
        }
