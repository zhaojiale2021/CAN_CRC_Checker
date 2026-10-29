"""Unified trace file reader supporting BLF, ASC, MF4, TRC, and other formats via python-can."""

from __future__ import annotations

import logging
import re

import can
from can.util import dlc2len
from crc_checker.trace.models import CanFrame

logger = logging.getLogger(__name__)


class _CanoeAscReader(can.ASCReader):  # pylint: disable=too-few-public-methods
    """ASCReader that also accepts CANoe 7.x CANFD lines (id before direction).

    CANoe 7.x writes ``CANFD <ch> <id> <dir> <brs> <esi> [<d>] <dlc> <len> <data>``
    while python-can only expects ``CANFD <ch> <dir> <id> <brs> <esi> <dlc> <len> <data>``.
    Classic CAN lines are unaffected and still go through python-can's own parser.
    """

    def _extract_header(self) -> None:  # pylint: disable=too-many-locals
        # python-can's version breaks on the first non-header line and drops it,
        # so the first data line after a '// version' comment gets swallowed.
        # Stop at the first message line and seek back to it instead.
        while True:
            pos = self.file.tell()
            line = self.file.readline()
            if not line:
                break
            line = line.strip()
            datetime_match = re.match(
                r"date\s+\w+\s+(?P<datetime_string>.+)", line, re.IGNORECASE
            )
            base_match = re.match(
                r"base\s+(?P<base>hex|dec)(?:\s+timestamps\s+"
                r"(?P<timestamp_format>absolute|relative))?",
                line,
                re.IGNORECASE,
            )
            if datetime_match:
                self.date = datetime_match.group("datetime_string")
                if not self.relative_timestamp:
                    self.start_time = self._datetime_to_timestamp(self.date)
            elif base_match:
                self.base = base_match.group("base")
                self._converted_base = self._check_base(self.base)
                self.timestamps_format = base_match.group("timestamp_format") or "absolute"
            elif not line or line.startswith("//"):
                continue
            elif re.match(r"(?P<no_events>no)?\s*internal\s+events\s+logged",
                          line, re.IGNORECASE):
                self.internal_events_logged = line.lower().startswith("internal")
            else:
                # First data line — push it back for __iter__
                self.file.seek(pos)
                break

    def _process_fd_can_frame(self, line: str, msg_kwargs: dict) -> can.Message:  # pylint: disable=too-many-locals
        tokens = line.split(None, 3)
        if tokens[1][:10].lower() == "errorframe":
            # CANFD error frame (python-can's own layout puts the direction first,
            # so it cannot reach its errorframe branch here)
            msg_kwargs["channel"] = int(tokens[0]) - 1
            msg_kwargs["is_error_frame"] = True
            return can.Message(**msg_kwargs)
        if tokens[1] in ("Rx", "Tx"):
            # Standard layout (direction before id) → python-can's own parser
            return super()._process_fd_can_frame(line, msg_kwargs)
        # CANoe 7.x layout: <ch> <id> <dir> <brs> <esi> [<d>] <dlc> <len> <data...>
        channel, can_id_str, direction, rest_of_message = tokens
        msg_kwargs["channel"] = int(channel) - 1
        msg_kwargs["is_rx"] = direction == "Rx"
        self._extract_can_id(can_id_str, msg_kwargs)
        parts = rest_of_message.split(None, 5)
        brs, esi = parts[0], parts[1]
        idx = 2
        if not parts[idx].isdigit():
            idx += 1  # data-frame marker 'd' (FD has no remote frames in practice)
        dlc_str, data_length_str = parts[idx], parts[idx + 1]
        data = parts[idx + 2] if idx + 2 < len(parts) else ""
        msg_kwargs["bitrate_switch"] = brs == "1"
        msg_kwargs["error_state_indicator"] = esi == "1"
        # The DLC code is a decimal 0-15 code, not a hex value ('13' → 32 bytes)
        dlc = int(dlc_str)
        data_length = int(data_length_str)
        if data_length == 0:
            msg_kwargs["is_remote_frame"] = True
            msg_kwargs["dlc"] = dlc
        else:
            if dlc2len(dlc) != data_length:
                logger.warning(
                    "DLC vs Data Length mismatch %d[%d] != %d",
                    dlc,
                    dlc2len(dlc),
                    data_length,
                )
            msg_kwargs["dlc"] = data_length
        self._process_data_string(data, data_length, msg_kwargs)
        return can.Message(**msg_kwargs)


def open_log_reader(file_path: str):
    """Dispatch to the right python-can reader, with CANoe 7.x ASC fallback.

    Use this for any direct trace-file access that needs one python-can
    reader instance (sampling helpers, ...) — never ``can.LogReader`` directly.
    """
    if str(file_path).lower().endswith(".asc"):
        return _CanoeAscReader(file_path)
    return can.LogReader(file_path)


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
        self._reader = open_log_reader(self.file_path)
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
        self._reader = open_log_reader(self.file_path)

    def close(self):
        """Close the reader."""
        if self._reader:
            self._reader.stop()
            self._reader = None


def read_trace(file_path: str):
    """Convenience generator to read frames from a trace file."""
    with TraceReader(file_path) as reader:
        yield from reader.frames()
