"""Data models for CAN trace frames."""

from dataclasses import dataclass


@dataclass
class CanFrame:
    """A single CAN data frame extracted from a trace file."""
    timestamp: float
    arbitration_id: int
    dlc: int
    data: bytes
    is_fd: bool = False
    is_extended: bool = False
    channel: int = 0
