"""Unified trace file reader supporting BLF, ASC, MF4, TRC, and other formats via python-can."""

from __future__ import annotations

import can
from crc_checker.trace.models import CanFrame


class TraceReader:
    """Reads CAN trace files in various formats using python-can.

    Supports: BLF, ASC, TRC, MF4, MDF, CSV, LOG
    Uses iterator pattern to handle large files without loading everything into memory.
    """

    def __init__(self, file_path: str):
        self.file_path = file_path
        self._reader = None
        self._total_count: int | None = None

    def __enter__(self):
        self._reader = can.LogReader(self.file_path)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._reader:
            self._reader.stop()
        return False

    def frames(self):
        """Iterate over all valid CAN data frames.

        Yields:
            CanFrame: Each valid data frame from the trace.
            Skips error frames and remote frames.
        """
        if self._reader is None:
            raise RuntimeError(
                "TraceReader must be used as a context manager or opened with open()"
            )

        for msg in self._reader:
            # Skip error frames and remote frames
            if msg.is_error_frame or msg.is_remote_frame:
                continue
            # Skip frames without valid data
            if msg.data is None:
                continue

            yield CanFrame(
                timestamp=msg.timestamp,
                arbitration_id=msg.arbitration_id,
                dlc=msg.dlc,
                data=bytes(msg.data),
                is_fd=getattr(msg, 'is_fd', False),
                is_extended=msg.is_extended_id,
                channel=getattr(msg, 'channel', 0),
            )

    def open(self):
        """Open the reader (non-context-manager usage)."""
        self._reader = can.LogReader(self.file_path)

    def close(self):
        """Close the reader."""
        if self._reader:
            self._reader.stop()
            self._reader = None


def read_trace(file_path: str):
    """Convenience generator to read frames from a trace file."""
    with TraceReader(file_path) as reader:
        yield from reader.frames()
